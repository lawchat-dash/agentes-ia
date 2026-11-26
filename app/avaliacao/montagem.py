"""Montagem da simulação (nível C): o mesmo atendimento de produção, entrando por `receber()`.

É o único caminho que exercita filtro, mensagens picadas, `_acoes_do_contrato`, CEP e follow-up. O modo
"laboratorio" do pipeline pula contrato e automações, então fica só para a conversa livre do painel.

A configuração do agente entra pela mesma montagem do Laboratório (`Laboratorios._montar`), com três ajustes:
modo teste (com o telefone do cenário como número de teste e espera zero), conta da Helena falsa para o webhook
achar o escritório, e token/canal falsos para o envio passar pela Helena falsa.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.avaliacao.efeitos import EfeitosFalsos, HelenaFalsa, VisaoDoCenario
from app.banco.memoria import RepositorioMemoria
from app.config import Configuracao
from app.modelo import Modelo
from app.pipeline import Atendimento

CONTA = "conta-avaliacao"
SESSAO = "sessao-avaliacao"
SEGREDO = "segredo-avaliacao"
ID_ESCRITORIO, ID_CANAL = "lab-escritorio", "lab-canal"      # ids que Laboratorios._montar usa
NUMERO_CANAL = "5500000000000"
# Regras do filtro sem rajada nem atraso: a simulação manda dezenas de mensagens em segundos.
FILTRO_DA_SIMULACAO = {"atraso_maximo_min": 10 ** 6, "rajada": {"mensagens": 10 ** 6, "segundos": 1}}


@dataclass
class Simulacao:
    cenario: Any
    snapshot: dict[str, Any]
    repo: RepositorioMemoria
    atendimento: Atendimento
    helena: HelenaFalsa
    efeitos: EfeitosFalsos
    visao: VisaoDoCenario
    http: httpx.AsyncClient
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    @property
    def telefone(self) -> str:
        return self.cenario.lead.telefone

    def lead(self) -> Any:
        return next((l for l in self.repo.leads.values() if l.telefone == self.telefone), None)

    def agente(self) -> Any:
        return self.repo.agentes[ID_CANAL]

    def etapa_do_lead(self) -> str | None:
        lead = self.lead()
        etapa = self.agente().etapa_por_id(lead.id_etapa) if lead else self.agente().principal()
        return etapa.codigo if etapa else None

    def webhook(self, *, tipo: str, texto: str | None, quando: datetime, url: str | None = None) -> dict[str, Any]:
        """Webhook da Helena como o lead mandaria (MESSAGE_RECEIVED, FROM_HUB), com id determinístico."""
        n = next(self._ids)
        detalhes: dict[str, Any] = {"from": "+" + self.telefone, "to": "+" + NUMERO_CANAL}
        if self.cenario.lead.nome_whatsapp:
            detalhes["contactName"] = self.cenario.lead.nome_whatsapp
        tipo_helena = {"texto": "TEXT", "audio": "AUDIO", "imagem": "IMAGE"}[tipo]
        if tipo == "audio":
            detalhes["transcription"] = {"text": texto or ""}
            texto = None
        if url:
            detalhes["file"] = {"publicUrl": url, "name": url.rsplit("/", 1)[-1], "mimeType": "image/jpeg"}
        return {
            "eventType": "MESSAGE_RECEIVED",
            "content": {"id": f"wamid-aval-{n}", "companyId": CONTA, "sessionId": SESSAO, "type": tipo_helena,
                        "text": texto, "direction": "FROM_HUB", "origin": "GATEWAY",
                        "timestamp": quando.isoformat(), "details": detalhes},
        }

    async def fechar(self) -> None:
        await self.atendimento.aguardar_esperas()
        await self.http.aclose()


def _sem_rede(pedido: httpx.Request) -> httpx.Response:
    return httpx.Response(404, request=pedido)


def configuracao(snapshot: dict[str, Any], real: bool = False) -> Configuracao:
    """Configuração do atendimento simulado. Igual em todos os modos (`real` não muda nada de propósito).

    modelo_falso fica sempre False: o modelo injetado já é o roteirizado, o cassete ou o de verdade. Se dependesse
    do modo, o auditor (desligado pelo modelo_falso no pipeline) rodaria ao gravar e sumiria ao tocar o cassete.
    """
    modelos = (snapshot["agente"].get("config") or {}).get("modelos") or {}
    return Configuracao(banco_url=None, helena_url="http://helena.invalid", modelo_padrao=modelos.get("etapa") or "gpt-4.1-mini",
                        modelo_falso=False, espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0,
                        segundos_por_letra=0, max_reprocessos=2, espera_midia_s=30)


def montar(cen: Any, modelo: Modelo, snapshot: dict[str, Any] | None = None, *, real: bool = False,
           agora: Any = None) -> Simulacao:
    """Repositório em memória com o agente do snapshot, Helena falsa, efeitos falsos e o atendimento pronto."""
    from app.gestao.laboratorio import Laboratorios

    snap = snapshot or cen.carregar_agente()
    repo = RepositorioMemoria()
    Laboratorios._montar(repo, snap["escritorio"], snap["agente"])            # mesma montagem do Laboratório
    agente = repo.agentes[ID_CANAL]
    agente.modo = "teste"                                                     # passa pelo filtro de numeros_teste
    escritorio = repo.escritorios[ID_ESCRITORIO]
    escritorio.config = {**escritorio.config, "numeros_teste": [cen.lead.telefone], "espera_teste_s": 0,
                         "filtro": FILTRO_DA_SIMULACAO}
    escritorio.id_segredo_helena = SEGREDO
    repo.segredos[SEGREDO] = "token-de-teste"
    repo.contas[CONTA] = ID_ESCRITORIO
    canal = repo.canais[ID_CANAL]
    canal.numero_normalizado, canal.id_canal_helena = NUMERO_CANAL, "canal-avaliacao"

    helena = HelenaFalsa()
    efeitos = EfeitosFalsos(repo, helena, cen.ferramentas, agora=agora)
    repo.fatos_do_sistema = efeitos.fatos_do_sistema                         # contrato gerado/assinado, como no Postgres
    visao = VisaoDoCenario()
    http = httpx.AsyncClient(transport=httpx.MockTransport(_sem_rede))        # nenhuma mídia sai para a rede
    atendimento = Atendimento(repo, modelo, configuracao(snap, real), helena, digitar=False, visao=visao,
                              http_midia=http, vetorizador=None)
    # Na simulação a falha da IA é o que se quer medir (e o relógio é congelado): sem nova tentativa adiada.
    atendimento.esperas_nova_tentativa_ia = ()
    return Simulacao(cen, snap, repo, atendimento, helena, efeitos, visao, http)
