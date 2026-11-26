"""Ativação completa de um agente: prepara tudo na Helena e aqui, confere, e só então liga.

Passos, na ordem (cada um volta com situacao ok | feito | aviso | erro | pulado):
  helena       a conta responde com o token guardado no cofre
  canal        o número do agente ainda existe na Helena e está conectado (sincroniza os canais)
  webhook      a assinatura de webhook do escritório existe, aponta para a URL dele e tem os eventos certos
  alcance      a URL pública do webhook chega mesmo neste servidor (não bloqueia: proxy pode impedir o teste)
  etapas       o agente tem etapas e o produto carrega (agente próprio com definição válida)
  modelo_ia    há chave para o provedor do modelo escolhido
  crm          painel escolhido e colunas usadas nas automações existem nele (se a função CRM estiver ligada)
  equipe       a equipe de transferência existe na Helena (se a função de transferir estiver ligada)
  teste        em modo teste, há número de teste

`aplicar=False` só confere (nada muda na Helena). `aplicar=True` sincroniza canais, cria ou corrige o
webhook e grava o resultado. Quem liga o agente é a rota, se não houver erro.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from app.canal.helena import normalizar_telefone
from app.canal.helena_conta import EVENTOS_DO_ATENDIMENTO, NOME_DA_ASSINATURA, ErroHelenaApi, HelenaConta
from app.canal.webhook import url_do_escritorio
from app.cerebro import produto as produtos
from app.gestao.repositorio import RepositorioGestao

PROVEDOR_DO_MODELO = (("gpt-", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"), ("claude-", "anthropic"))
CHAVE_DO_PROVEDOR = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


@dataclass
class Passo:
    codigo: str
    titulo: str
    situacao: str = "pendente"          # ok | feito | aviso | erro | pulado | pendente
    detalhe: str = ""

    def __call__(self, situacao: str, detalhe: str = "") -> "Passo":
        self.situacao, self.detalhe = situacao, detalhe
        return self


@dataclass
class Resultado:
    passos: list[Passo] = field(default_factory=list)

    @property
    def pronto(self) -> bool:
        return not any(p.situacao == "erro" for p in self.passos)

    @property
    def pendencias(self) -> list[str]:
        return [f"{p.titulo}: {p.detalhe}" for p in self.passos if p.situacao == "erro"]

    def como_dict(self) -> dict[str, Any]:
        return {"pronto": self.pronto, "passos": [asdict(p) for p in self.passos],
                "conferido_em": datetime.now(timezone.utc).isoformat()}


def provedor_do_modelo(modelo: str) -> str:
    return next((p for prefixo, p in PROVEDOR_DO_MODELO if modelo.startswith(prefixo)), "openai")


async def _alcance(url: str, http: httpx.AsyncClient | None) -> tuple[bool, str]:
    proprio = http is None
    http = http or httpx.AsyncClient(timeout=6)
    try:
        resposta = await http.post(url + "&teste=1", json={})
        if resposta.status_code == 200 and resposta.json().get("feito") == "teste":
            return True, "o endereço público chega neste servidor"
        return False, f"o endereço respondeu {resposta.status_code}"
    except (httpx.HTTPError, ValueError) as erro:
        return False, f"não foi possível chamar o endereço ({type(erro).__name__})"
    finally:
        if proprio:
            await http.aclose()


async def preparar(
    *,
    repo: RepositorioGestao,
    id_escritorio: str,
    agente: dict[str, Any],
    modo: str,
    aplicar: bool,
    helena_de: Callable[[str], Awaitable[HelenaConta]],
    http: httpx.AsyncClient | None = None,
) -> Resultado:
    r = Resultado()
    passo = lambda codigo, titulo: (r.passos.append(p := Passo(codigo, titulo)), p)[1]  # noqa: E731
    config = agente.get("config") or {}
    funcoes = config.get("funcoes") or {}
    integracoes = await repo.integracoes(id_escritorio)

    # 1. Helena
    p_helena = passo("helena", "Conta da Helena")
    helena: HelenaConta | None = None
    canais_helena: list[dict[str, Any]] = []
    try:
        helena = await helena_de(id_escritorio)
        canais_helena = await helena.canais()
        p_helena("ok", f"token aceito; {len(canais_helena)} números na conta")
    except ErroHelenaApi as erro:
        p_helena("erro", "a Helena recusou o token" if erro.motivo == "token_recusado" else f"a Helena não respondeu ({erro.motivo})")
    except Exception as erro:                       # sem token no cofre etc.
        p_helena("erro", getattr(erro, "detail", None) or str(erro) or "cadastre o token em Integrações")

    # 2. Canal
    p_canal = passo("canal", "Número de WhatsApp")
    if helena is None:
        p_canal("pulado", "depende da Helena")
    else:
        if aplicar:
            await repo.sincronizar_canais(id_escritorio, [
                {**c, "numero_normalizado": normalizar_telefone(c["numero"]) or c["numero"]} for c in canais_helena if c["id"]])
        do_agente = next((c for c in canais_helena if c["id"] == agente.get("id_canal_helena")), None)
        numero = agente.get("numero_canal") or ""
        if not do_agente:
            p_canal("erro", f"o número {numero} não existe mais nesta conta da Helena; escolha outro número no agente")
        elif not do_agente["ativo"]:
            p_canal("erro", f"o número {numero} está desconectado na Helena; reconecte o WhatsApp lá e tente de novo")
        else:
            tipo = "API oficial" if do_agente["tipo"] == "oficial" else "não oficial"
            p_canal("feito" if aplicar else "ok", f"{do_agente['numero_formatado'] or numero} conectado ({tipo})")

    # 3. Webhook
    p_webhook = passo("webhook", "Recebimento das mensagens (webhook)")
    url = url_do_escritorio(id_escritorio)
    integracao_helena = integracoes.get("helena") or {}
    id_assinatura = (integracao_helena.get("config") or {}).get("id_assinatura")
    if not url:
        p_webhook("erro", "o servidor não tem endereço público (AGENTESIA_URL_PUBLICA e AGENTESIA_WEBHOOK_SEGREDO)")
    elif helena is None:
        p_webhook("pulado", "depende da Helena")
    else:
        try:
            if aplicar:
                assinatura = await helena.garantir_assinatura(url, id_assinatura)
                await repo.salvar_integracao(id_escritorio, "helena", situacao="ok",
                                             config={"id_assinatura": assinatura["id"], "webhook_conectado": True})
                p_webhook("ok" if assinatura["acao"] == "ja_estava_certa" else "feito",
                          {"criada": "assinatura criada na Helena", "corrigida": "assinatura corrigida na Helena",
                           "ja_estava_certa": "assinatura já estava certa"}[assinatura["acao"]])
            else:
                atuais = await helena.assinaturas()
                nossa = next((a for a in atuais if a["id"] == id_assinatura), None) or \
                    next((a for a in atuais if a["nome"] == NOME_DA_ASSINATURA), None)
                certa = bool(nossa and nossa["url"] == url and nossa["ativa"]
                             and set(EVENTOS_DO_ATENDIMENTO) <= set(nossa["eventos"]))
                p_webhook("ok" if certa else "aviso",
                          "assinatura certa" if certa else "será criada ou corrigida na ativação")
        except ErroHelenaApi as erro:
            p_webhook("erro", f"a Helena não aceitou a assinatura ({erro.motivo})")

    # 4. Alcance da URL pública
    p_alcance = passo("alcance", "Endereço público responde")
    if not url:
        p_alcance("pulado", "sem endereço público")
    else:
        chegou, detalhe = await _alcance(url, http)
        p_alcance("ok" if chegou else "aviso", detalhe if chegou else
                  detalhe + ". Se a Helena também não alcançar, as mensagens não chegam.")

    # 5. Etapas
    p_etapas = passo("etapas", "Etapas e instruções")
    try:
        produto = produtos.carregar(agente.get("produto") or "auxilio_acidente", config)
        codigos = {e["codigo"] for e in agente.get("etapas") or []}
        faltam = [e.codigo for e in produto.etapas if e.codigo not in codigos]
        if not codigos:
            p_etapas("erro", "o agente não tem etapas")
        elif faltam:
            p_etapas("erro", "etapas da definição sem cadastro: " + ", ".join(faltam))
        else:
            p_etapas("ok", f"{len(codigos)} etapas")
    except Exception as erro:
        p_etapas("erro", f"a definição do agente não carrega: {erro}")

    # 6. Modelo de IA
    p_modelo = passo("modelo_ia", "Chave do modelo de IA")
    modelo = (config.get("modelos") or {}).get("etapa") or os.environ.get("AGENTESIA_MODELO", "gpt-4.1")
    provedor = provedor_do_modelo(modelo)
    # Uma chave só, a da LawChat (.env): chave própria do escritório (BYOK) não vale mais (docs/COBRANCA_TOKENS.md).
    if os.environ.get(CHAVE_DO_PROVEDOR[provedor]):
        p_modelo("ok", f"{modelo} com a chave da LawChat")
    else:
        p_modelo("erro", f"sem chave da {'OpenAI' if provedor == 'openai' else 'Anthropic'} para o modelo {modelo}")

    # 7. CRM
    p_crm = passo("crm", "CRM da Helena")
    if not funcoes.get("crm"):
        if ((integracoes.get("crm") or {}).get("config") or {}).get("id_painel"):
            # O escritório escolheu o painel, mas o agente não move card nem troca etiqueta: antes saía "pulado", calado.
            p_crm("aviso", "CRM configurado mas a função Etapa do CRM está desligada no agente")
        else:
            p_crm("pulado", "função desligada")
    elif helena is None:
        p_crm("pulado", "depende da Helena")
    else:
        crm = (integracoes.get("crm") or {}).get("config") or {}
        if not crm.get("id_painel"):
            p_crm("aviso", "sem painel escolhido em Integrações: os cards não se movem até escolher")
        else:
            try:
                painel = next((x for x in await helena.paineis() if x["id"] == crm["id_painel"]), None)
            except ErroHelenaApi as erro:
                painel, _ = None, p_crm("erro", f"não deu para ler os painéis ({erro.motivo})")
            if p_crm.situacao != "erro":
                if not painel:
                    p_crm("erro", f"o painel {crm.get('titulo_painel') or ''} não existe mais na Helena")
                else:
                    colunas = {e["id"] for e in painel["etapas"]}
                    usadas = {g: (regra or {}).get("coluna_crm") for g, regra in (config.get("automacoes") or {}).items()}
                    sumidas = sorted(g for g, c in usadas.items() if c and c not in colunas)
                    p_crm("erro", "colunas que não existem mais no painel, usadas em: " + ", ".join(sumidas)) if sumidas \
                        else p_crm("ok", f"painel {painel['titulo']} com {len(colunas)} colunas")

    # 8. Equipe de transferência
    p_equipe = passo("equipe", "Equipe que recebe as transferências")
    if not funcoes.get("transferir_humano"):
        p_equipe("pulado", "função desligada")
    elif not config.get("id_equipe_transferencia"):
        p_equipe("aviso", "nenhuma equipe escolhida: a conversa vai para a fila geral da Helena")
    elif helena is None:
        p_equipe("pulado", "depende da Helena")
    else:
        try:
            equipes = await helena.equipes()
            achada = next((e for e in equipes if e["id"] == config["id_equipe_transferencia"]), None)
            p_equipe("ok", achada["nome"]) if achada else p_equipe("erro", "a equipe escolhida não existe mais na Helena")
        except ErroHelenaApi as erro:
            p_equipe("aviso", f"não deu para conferir as equipes ({erro.motivo})")

    # 9. Contrato (ZapSign)
    p_contrato = passo("contrato", "Contrato na ZapSign")
    if not funcoes.get("contrato_zapsign"):
        p_contrato("pulado", "função desligada")
    else:
        zapsign = integracoes.get("zapsign") or {}
        modelos = [m for m in (zapsign.get("config") or {}).get("modelos") or [] if m.get("id_modelo")]
        if zapsign.get("situacao") != "ok":
            p_contrato("erro", "cadastre e teste o token da ZapSign em Integrações")
        elif not modelos:
            p_contrato("erro", "escolha o modelo de contrato em Integrações > ZapSign")
        else:
            p_contrato("ok", f"{len(modelos)} modelo(s); lembre de colar o webhook de assinatura na ZapSign")

    # 10. Números de teste
    p_teste = passo("teste", "Números de teste")
    if modo != "teste":
        p_teste("pulado", "em produção a IA responde a todos")
    elif agente.get("numeros_teste"):
        p_teste("ok", f"{len(agente['numeros_teste'])} número(s): só eles recebem resposta")
    else:
        p_teste("erro", "cadastre pelo menos um número de teste")

    return r
