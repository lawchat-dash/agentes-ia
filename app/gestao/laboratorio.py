"""Laboratório de um agente de verdade: usa a configuração salva do agente,
mas conversa em memória e não envia nada a ninguém."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.banco.memoria import RepositorioMemoria
from app.banco.tipos import Agente, Canal, Escritorio, Etapa
from app.config import Configuracao
from app.modelo import Modelo
from app.pipeline import Atendimento

LIMITE_CONVERSAS = 200
VALIDADE_S = 6 * 3600


class Laboratorios:
    def __init__(self, modelo: Modelo, cfg: Configuracao) -> None:
        self._modelo = modelo
        self._cfg = cfg
        self._conversas: dict[str, tuple[float, RepositorioMemoria, Atendimento, str]] = {}

    def _limpar(self) -> None:
        agora = time.time()
        for chave, (criada, *_resto) in list(self._conversas.items()):
            if agora - criada > VALIDADE_S:
                del self._conversas[chave]
        while len(self._conversas) > LIMITE_CONVERSAS:
            del self._conversas[min(self._conversas, key=lambda k: self._conversas[k][0])]

    @staticmethod
    def _montar(repo: RepositorioMemoria, escritorio: dict[str, Any], agente: dict[str, Any]) -> None:
        """Copia a configuração salva do agente para a memória (a cada mensagem, para valer o que acabou de ser editado)."""
        id_e, id_c = "lab-escritorio", "lab-canal"
        repo.cadastrar(
            Escritorio(id=id_e, nome=escritorio["nome"], config=escritorio.get("config") or {}),
            Canal(id=id_c, id_escritorio=id_e, numero_normalizado="5500000000000"),
            Agente(
                id=agente["id"], id_escritorio=id_e, id_canal=id_c, nome=agente["nome"], produto=agente["produto"],
                situacao="ativo", modo="laboratorio", config=agente.get("config") or {},
                etapas=[Etapa(id=e["id"], codigo=e["codigo"], principal=e["principal"], instrucao=e["instrucao"],
                              modelo=e.get("modelo")) for e in agente["etapas"]],
            ),
        )

    def esquecer(self, id_conversa: str | None) -> None:
        """Recomeçar: a conversa some da memória (a próxima mensagem abre outra)."""
        if id_conversa:
            self._conversas.pop(id_conversa, None)

    async def mensagem(self, *, escritorio: dict[str, Any], agente: dict[str, Any],
                       id_conversa: str | None, texto: str, etapa_inicial: str | None = None) -> dict[str, Any]:
        """Uma mensagem do lead de teste. `agente` pode ser o salvo (aba Laboratório) ou o montado a partir do
        RASCUNHO do produto (assistente e editor: app/gestao/rotas_rascunho.py). etapa_inicial: código da etapa em
        que a conversa nova começa (vazio = a principal, como um lead novo)."""
        self._limpar()
        chave = id_conversa if id_conversa in self._conversas else None
        if chave and self._conversas[chave][3] != agente["id"]:
            chave = None                                     # conversa de outro agente: começa outra
        if chave is None:
            repo = RepositorioMemoria()
            self._montar(repo, escritorio, agente)
            atendimento = Atendimento(repo, self._modelo, self._cfg, helena=None, digitar=False)
            lead = await repo.achar_ou_criar_lead(
                escritorio=repo.escritorios["lab-escritorio"], canal=repo.canais["lab-canal"],
                agente=repo.agentes["lab-canal"], telefone="lab-" + uuid.uuid4().hex[:8], id_sessao=None)
            chave = lead.id + "-" + uuid.uuid4().hex[:6]
            inicio = next((e for e in repo.agentes["lab-canal"].etapas if e.codigo == etapa_inicial), None)
            if inicio is not None:
                repo.leads[lead.id].id_etapa = inicio.id         # "começar na etapa": Closer, Contratos...
            self._conversas[chave] = (time.time(), repo, atendimento, agente["id"])
        _, repo, atendimento, _ = self._conversas[chave]
        self._montar(repo, escritorio, agente)
        lead = next(iter(repo.leads.values()))
        if lead.estado != "ativo":
            lead.estado, lead.motivo_estado = "ativo", None   # no laboratório a conversa sempre continua
        await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto=texto, texto_extraido=None,
                                   url_midia=None, enviada_em=datetime.now(timezone.utc), id_externo=None)
        saida = await atendimento.processar(lead.id, modo="laboratorio")
        lead = await repo.lead(lead.id)
        etapa = repo.agentes["lab-canal"].etapa_por_id(lead.id_etapa) if lead else None
        return {
            "id_conversa": chave,
            "turno": saida.como_dict() if saida else None,
            "etapa": etapa.codigo if etapa else None,
            "estado": saida.estado_lead if saida and saida.estado_lead else "ativo",
            "fatos": await repo.fatos_vigentes(lead.id) if lead else {},
        }
