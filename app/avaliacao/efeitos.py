"""Efeitos falsos da simulação: Helena, ZapSign, CEP e visão de mentira, sem rede e sem Postgres.

`EfeitosFalsos.consumir()` roda depois de cada `aguardar_esperas()` e faz com a fila `repo.acoes` o que o
`app.acoes.Executor` faria (o Executor exige pool asyncpg). Conferido contra `Executor._gerar_contrato`,
`_verificar_assinatura`, `_reenviar_link` e `_enviar_mensagem`:
  - gerar_contrato: valida de novo os dados da ação; dado ruim pede a correção; mesmo hash reenvia o mesmo link;
    senão gera a versão N, manda "Segue o link de contrato" e move o lead para `assinatura`;
  - verificar_assinatura: assinado move para `contrato_assinado` com o lead `encerrado` e manda a confirmação;
    não assinado manda o link de novo ("pendente");
  - reenviar_link: manda o mesmo link;
  - enviar_mensagem: entrega pela Helena falsa.
O que o Executor manda ao lead volta no webhook como mensagem de API: aqui fica gravado com autor 'automacao'.
"""

from __future__ import annotations

import contextvars
import itertools
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.canal.helena import ErroHelena
from app.contrato import dados as cdados
from app.ferramentas.cep import Endereco, limpar_cep
from app.modelo import Chamada

LINK_FALSO = "https://zapsign.invalid/doc/{n}"
URL_CONTRATO = re.compile(r"https://zapsign\.invalid/\S+")


# ---------------------------------------------------------------------------- Helena
class HelenaFalsa:
    """Guarda o que seria enviado ao lead. `registros` diz quem mandou: a IA (pipeline) ou o sistema (ações)."""

    def __init__(self, falhar: bool = False) -> None:
        self.enviadas: list[str] = []
        self.registros: list[dict[str, Any]] = []
        self.ids: list[str] = []
        self.falhar = falhar
        self._seq = itertools.count(1)

    async def enviar(self, *, token: str, id_sessao: str, id_canal: str | None, texto: str | None = None,
                     url_arquivo: str | None = None, origem: str = "ia") -> str:
        if self.falhar:
            raise ErroHelena("HTTP 500")
        conteudo = texto or url_arquivo or ""
        self.enviadas.append(conteudo)
        self.ids.append(f"env-{next(self._seq)}")
        self.registros.append({"texto": conteudo, "origem": origem, "id": self.ids[-1], "arquivo": url_arquivo is not None})
        return self.ids[-1]


# ---------------------------------------------------------------------------- CEP
class CepFalso:
    """Mesma assinatura de app.ferramentas.cep.consultar, com a tabela do cenário. Nunca levanta exceção."""

    def __init__(self, tabela: dict[str, dict[str, str]]) -> None:
        self.tabela = {limpar_cep(chave): valor for chave, valor in (tabela or {}).items()}
        self.consultas: list[str] = []

    async def __call__(self, cep_bruto: object, *, cliente: Any = None, timeout: float = 6.0) -> Endereco:
        cep = limpar_cep(cep_bruto)
        self.consultas.append(cep)
        if len(cep) != 8:
            return Endereco(cep=str(cep_bruto or ""), valido=False, mensagem="CEP inválido: precisa ter 8 dígitos.")
        achado = self.tabela.get(cep)
        if not achado:
            return Endereco(cep=cep, valido=False, mensagem="CEP não encontrado em nenhuma fonte.")
        return Endereco(cep=cep, valido=True, tipo="rua", mensagem="CEP válido (rua).", origem="cenario",
                        logradouro=achado.get("logradouro", ""), bairro=achado.get("bairro", ""),
                        cidade=achado.get("cidade", ""), uf=achado.get("uf", ""))


_cep_atual: contextvars.ContextVar[CepFalso | None] = contextvars.ContextVar("cep_da_avaliacao", default=None)
_trava = threading.Lock()
_instalados = 0
_original: dict[str, Any] = {}


async def _consultar(cep_bruto: object, **extra: Any) -> Endereco:
    falso = _cep_atual.get()
    if falso is None:                                   # fora da simulação: o de verdade
        return await _original["consultar"](cep_bruto, **extra)
    return await falso(cep_bruto, **extra)


@contextmanager
def cep_falso(tabela: dict[str, dict[str, str]], monkeypatch: Any = None) -> Iterator[CepFalso]:
    """Troca app.ferramentas.cep.consultar pela tabela do cenário (o pipeline importa dentro da função)."""
    global _instalados
    from app.ferramentas import cep as modulo

    falso = CepFalso(tabela)
    if monkeypatch is not None:
        monkeypatch.setattr(modulo, "consultar", falso)
        yield falso
        return
    with _trava:
        _instalados += 1
        if _instalados == 1:
            _original["consultar"] = modulo.consultar
            modulo.consultar = _consultar
    marca = _cep_atual.set(falso)
    try:
        yield falso
    finally:
        _cep_atual.reset(marca)
        with _trava:
            _instalados -= 1
            if _instalados == 0:
                modulo.consultar = _original.pop("consultar")


# ---------------------------------------------------------------------------- visão
class VisaoDoCenario:
    """Descreve imagem com o texto pronto do cenário (dia 1). A fase 2 troca por VisaoGravada."""

    def __init__(self) -> None:
        self.descricoes: dict[str, str] = {}

    async def descrever_imagem(self, url: str, mime: str | None, legenda: str | None) -> tuple[str, Chamada]:
        return self.descricoes.get(url, "imagem sem descrição no cenário"), Chamada(papel="visao", modelo="cenario")


# ---------------------------------------------------------------------------- ações da fila
@dataclass
class ContratoFalso:
    versao: int
    link: str
    dados: dict[str, str]
    hash: str
    situacao: str = "gerado"                            # gerado | substituido | assinado


@dataclass
class EfeitosFalsos:
    repo: Any
    helena: HelenaFalsa
    ferramentas: Any                                    # cenario.Ferramentas
    agora: Any = None                                   # () -> datetime (relógio da simulação)
    contratos: list[ContratoFalso] = field(default_factory=list)
    registro: list[dict[str, Any]] = field(default_factory=list)
    _vistas: int = 0

    # ---- fatos do sistema, como o Postgres responde (o repositório em memória diz sempre "não gerado")
    async def fatos_do_sistema(self, id_lead: str) -> dict[str, Any]:
        from app.cerebro import contexto

        lead = self.repo.leads.get(id_lead)
        if not lead:
            return {}
        vigente = next((c for c in reversed(self.contratos) if c.situacao in ("assinado", "gerado")), None)
        texto = contexto.texto_do_contrato(vigente.situacao if vigente else None, versao=vigente.versao if vigente else None,
                                           link=vigente.link if vigente else None)
        return {"telefone": lead.telefone, "contrato": texto}

    # ---- fila
    async def consumir(self) -> int:
        """Executa as ações novas da fila, inclusive as que nascem aqui (mensagem ao lead). Devolve quantas."""
        feitas = 0
        while self._vistas < len(self.repo.acoes):
            acao = self.repo.acoes[self._vistas]
            self._vistas += 1
            tratar = getattr(self, "_" + acao["tipo"], None)
            resultado = await tratar(acao) if tratar else {"ignorada": True}
            self.registro.append({"tipo": acao["tipo"], "chave_unica": acao["chave_unica"], "resultado": resultado})
            feitas += 1
        return feitas

    def _lead(self, acao: dict[str, Any]) -> Any:
        return self.repo.leads.get(acao.get("id_lead") or "")

    async def _enfileirar(self, lead: Any, tipo: str, chave: str, dados: dict[str, Any]) -> None:
        await self.repo.enfileirar_acoes(id_escritorio=lead.id_escritorio, id_lead=lead.id, id_turno=None,
                                         acoes=[{"tipo": tipo, "chave_unica": chave, "dados": dados}])

    async def _mensagem_ao_lead(self, lead: Any, chave: str, texto: str) -> None:
        if lead.id_sessao_helena:
            await self._enfileirar(lead, "enviar_mensagem", chave, {"texto": texto})

    async def _mover(self, lead: Any, codigo: str, **campos: Any) -> bool:
        agente = self.repo.agentes.get(lead.id_canal)
        etapa = agente.etapa(codigo) if agente else None
        if not etapa:
            return False
        await self.repo.atualizar_lead(lead.id, id_etapa=etapa.id, **campos)
        return True

    async def _enviar_mensagem(self, acao: dict[str, Any]) -> dict[str, Any]:
        lead = self._lead(acao)
        if not lead or not lead.id_sessao_helena:
            return {"erro": "lead sem atendimento da Helena"}
        dados = acao.get("dados") or {}
        texto, arquivo = dados.get("texto"), dados.get("url_arquivo")
        id_externo = await self.helena.enviar(token="token-de-teste", id_sessao=lead.id_sessao_helena, id_canal=None,
                                              texto=texto, url_arquivo=arquivo, origem="sistema")
        await self.repo.gravar_mensagem(lead=lead, autor="automacao", tipo="texto" if texto else "video", texto=texto,
                                        texto_extraido=None if texto else f"[mídia enviada: {arquivo}]",
                                        url_midia=arquivo, enviada_em=self._agora(), id_externo=id_externo)
        return {"id_mensagem": id_externo}

    def _agora(self) -> Any:
        from datetime import datetime, timezone

        return self.agora() if self.agora else datetime.now(timezone.utc)

    async def _gerar_contrato(self, acao: dict[str, Any]) -> dict[str, Any]:
        lead = self._lead(acao)
        dados = acao.get("dados") or {}
        chave_base = f"{lead.id}:contrato:{(dados.get('hash') or '')[:16]}"
        valido, erros = cdados.validar_dados(dados.get("dados") or {}, lead.telefone, cdados.OBRIGATORIOS_PADRAO)
        if erros:
            await self._mensagem_ao_lead(lead, f"{chave_base}:corrigir", cdados.pedir_correcao(erros))
            return {"situacao": "dado_invalido", "campos": [e.campo for e in erros]}
        hash_dados = cdados.hash_dados(valido)
        if any(c.situacao == "assinado" for c in self.contratos):
            await self._mensagem_ao_lead(lead, f"{chave_base}:ja", cdados.texto({}, "ja_assinado"))
            return {"situacao": "ja_assinado"}
        atual = next((c for c in reversed(self.contratos) if c.situacao == "gerado"), None)
        if atual and atual.hash == hash_dados:
            await self._mensagem_ao_lead(lead, f"{chave_base}:mesmo", cdados.texto({}, "mesmo_link", link=atual.link))
            return {"situacao": "mesmo_link", "versao": atual.versao}
        if atual:
            atual.situacao = "substituido"
        versao = len(self.contratos) + 1
        contrato = ContratoFalso(versao=versao, link=LINK_FALSO.format(n=versao), dados=valido, hash=hash_dados)
        self.contratos.append(contrato)
        texto = cdados.texto({}, "link" if versao == 1 else "nova_versao", link=contrato.link)
        await self._mensagem_ao_lead(lead, f"{lead.id}:contrato:v{versao}:link", texto)
        await self._mover(lead, "assinatura")
        return {"situacao": "gerado", "versao": versao, "link": contrato.link}

    async def _verificar_assinatura(self, acao: dict[str, Any]) -> dict[str, Any]:
        lead = self._lead(acao)
        contrato = next((c for c in reversed(self.contratos) if c.situacao in ("assinado", "gerado", "substituido")), None)
        if not contrato:
            return {"resultado": "sem_contrato"}
        verificacao = (acao.get("dados") or {}).get("origem") == "verificacao"
        base = f"{lead.id}:assinatura:{contrato.versao}"
        if contrato.situacao == "assinado":
            if verificacao:
                await self._mensagem_ao_lead(lead, f"{base}:ja:{acao['chave_unica']}", cdados.texto({}, "ja_assinado"))
            return {"resultado": "ja_estava_assinado"}
        if self.ferramentas.zapsign.assina:
            contrato.situacao = "assinado"
            await self._mover(lead, "contrato_assinado", estado="encerrado", motivo_estado="contrato_assinado")
            await self._mensagem_ao_lead(lead, f"{base}:confirmacao", cdados.texto({}, "pos_assinatura"))
            return {"resultado": "assinado", "versao": contrato.versao}
        if verificacao:
            await self._mensagem_ao_lead(lead, f"{base}:pendente:{acao['chave_unica']}",
                                         cdados.texto({}, "pendente", link=contrato.link))
        return {"resultado": "nao_assinado"}

    async def _reenviar_link(self, acao: dict[str, Any]) -> dict[str, Any]:
        lead = self._lead(acao)
        contrato = next((c for c in reversed(self.contratos) if c.situacao == "gerado"), None)
        if not contrato:
            return {"reenviado": False, "motivo": "sem_contrato_gerado"}
        await self._mensagem_ao_lead(lead, f"{acao['chave_unica']}:mensagem", cdados.texto({}, "mesmo_link", link=contrato.link))
        return {"reenviado": True, "versao": contrato.versao}

    def contagem(self) -> dict[str, int]:
        """Quantas ações de cada tipo passaram pela fila."""
        saida: dict[str, int] = {}
        for item in self.registro:
            saida[item["tipo"]] = saida.get(item["tipo"], 0) + 1
        return saida
