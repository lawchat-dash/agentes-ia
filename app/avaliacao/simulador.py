"""Simulador: roda uma conversa inteira entre o lead simulado e o atendimento de verdade.

Cada rodada: o lead manda as falas (uma fala picada vira vários webhooks seguidos), o pipeline responde,
os efeitos falsos executam a fila (contrato, assinatura...) e o lead lê tudo o que chegou.

Regras de parada: lead pausado ou encerrado; etapa contrato_assinado; um turno concluído no papel
desqualificado (o catálogo não encerra o lead); etapa em limites.parar_em; o lead saiu; limite de turnos; laço;
trava de desvio do LeadRoteiro; falta no cassete; teto de custo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.avaliacao import checagens, custo, efeitos as efeitos_falsos, leads as leads_simulados, montagem, relogio
from app.avaliacao.cenario import Cenario, Fala
from app.modelo import Modelo


@dataclass
class TurnoSimulado:
    id: str
    situacao: str
    motivo: str
    etapa_antes: str | None
    etapa_depois: str | None
    transferir_para: str = ""
    ferramenta: str = ""
    mensagens: list[str] = field(default_factory=list)       # textos que a IA mandou neste turno
    midias: list[str] = field(default_factory=list)          # mídias que a IA mandou: a URL (ou "[mídia enviada: chave]")
    # Tudo o que a IA mandou, na ordem real: ("texto", texto) ou ("midia", url). Vazio em turnos montados à mão: aí a
    # transcrição usa mensagens e depois midias.
    envios: list[tuple[str, str]] = field(default_factory=list)
    resposta_mensagens: list[dict[str, Any]] = field(default_factory=list)
    reprovacoes: list[list[dict[str, str]]] = field(default_factory=list)   # uma lista por tentativa (travas)
    # Tentativas barradas pela trava: [{"texto": "<texto reprovado>", "reprovacoes": ["<motivo>", ...]}], gravadas pelo
    # turno em saida.contexto["tentativas"]. Vazio quando o turno não grava (versões antigas) ou nada foi barrado.
    tentativas: list[dict[str, Any]] = field(default_factory=list)

    def texto_barrado(self) -> str:
        """O texto da 1ª tentativa barrada (o que o lead NÃO recebeu), ou "" se o turno não gravou."""
        return ler_tentativa(self.tentativas[0])[0] if self.tentativas else ""


def ler_tentativa(tentativa: Any) -> tuple[str, list[str]]:
    """(texto reprovado, motivos) de um item de saida.contexto["tentativas"], aceitando variações do formato."""
    if not isinstance(tentativa, dict):
        return str(tentativa or "").strip(), ["trava"]
    texto = tentativa.get("texto") or ""
    if isinstance(texto, list):
        texto = "\n".join(str(t.get("texto") if isinstance(t, dict) else t) for t in texto)
    motivos = [str(m.get("orientacao") or m.get("codigo") or "") if isinstance(m, dict) else str(m)
               for m in tentativa.get("reprovacoes") or []]
    return str(texto).strip(), [m for m in motivos if m] or ["trava"]


@dataclass
class Rodada:
    n: int
    falas: list[Fala]
    etapa_antes: str | None
    etapa_depois: str | None = None
    estado_depois: str | None = None
    turnos: list[TurnoSimulado] = field(default_factory=list)
    enviadas: list[str] = field(default_factory=list)        # tudo o que o lead recebeu, na ordem
    enviadas_ia: list[str] = field(default_factory=list)
    enviadas_sistema: list[str] = field(default_factory=list)
    eventos: list[dict[str, Any]] = field(default_factory=list)
    fatos_depois: dict[str, Any] = field(default_factory=dict)
    faltas: list[str] = field(default_factory=list)
    chamadas: list[dict[str, Any]] = field(default_factory=list)
    falhas: list[checagens.Falha] = field(default_factory=list)
    trava_sombra: dict[str, int] = field(default_factory=dict)


@dataclass
class Conversa:
    cenario: Cenario
    snapshot: dict[str, Any]
    rodadas: list[Rodada] = field(default_factory=list)
    parada: str = ""
    trajetoria: list[str] = field(default_factory=list)
    estado_final: str | None = None
    etapa_final: str | None = None
    fatos_finais: dict[str, Any] = field(default_factory=dict)
    fatos_historico: list[dict[str, Any]] = field(default_factory=list)
    acoes: list[dict[str, Any]] = field(default_factory=list)
    contratos: list[dict[str, Any]] = field(default_factory=list)
    chamadas: list[dict[str, Any]] = field(default_factory=list)
    custo: dict[str, Any] = field(default_factory=dict)
    falhas: list[checagens.Falha] = field(default_factory=list)
    lead_invalido: str | None = None
    ferramentas: dict[str, int] = field(default_factory=dict)  # zapsign acionado, consultas de CEP, ações da fila
    simulacao: Any = None                                    # montagem.Simulacao (repo, helena, efeitos)

    @property
    def nao_concluida(self) -> str | None:
        """Motivo de a conversa não ter terminado (cortada pelo teto de custo), ou None."""
        return "cortada pelo teto de custo antes de terminar" if self.parada == "teto_de_custo" else None

    @property
    def aprovada(self) -> bool:
        return self.lead_invalido is None and self.nao_concluida is None and checagens.aprovado(self.falhas)

    def trava_sombra(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for r in self.rodadas:
            for codigo, n in r.trava_sombra.items():
                total[codigo] = total.get(codigo, 0) + n
        return dict(sorted(total.items()))

    def codigos(self) -> set[str]:
        return {f.codigo for f in self.falhas}


def _midia(mensagem: Any) -> str:
    """O que identifica a mídia enviada: a URL (o pipeline grava url_midia) ou o "[mídia enviada: chave]"."""
    return (getattr(mensagem, "url_midia", None) or getattr(mensagem, "texto_extraido", None) or "").strip()


def _faltas(modelo: Any) -> list[str]:
    return list(getattr(modelo, "faltas", []) or [])


async def _rodada(sim: montagem.Simulacao, rel: relogio.Relogio, falas: list[Fala], n: int, modelo: Any) -> Rodada:
    repo, helena = sim.repo, sim.helena
    antes_turnos, antes_env, antes_eventos = set(repo.turnos), len(helena.registros), len(repo.eventos)
    antes_chamadas, antes_faltas = len(repo.chamadas), len(_faltas(modelo))
    rodada = Rodada(n=n, falas=falas, etapa_antes=sim.etapa_do_lead())
    for i, fala in enumerate(falas):
        for parte in fala.partes():
            rel.avancar(1)
            url = None
            if fala.tipo == "imagem":
                url = f"https://midia.invalid/{sim.cenario.id.split('[')[0]}/{n}-{i}.jpg"
                sim.visao.descricoes[url] = fala.descricao or ""
            await sim.atendimento.receber(sim.webhook(tipo=fala.tipo, texto=parte or None, quando=rel.agora_utc(), url=url))
    await sim.atendimento.aguardar_esperas()
    await sim.efeitos.consumir()
    rel.avancar(1)

    lead = sim.lead()
    for id_turno, turno in repo.turnos.items():
        if id_turno in antes_turnos:
            continue
        mensagens = [m for m in repo.mensagens.get(lead.id, []) if m.id_turno == id_turno and m.autor == "ia"] if lead else []
        contexto = turno.get("contexto") if isinstance(turno.get("contexto"), dict) else {}
        catalogo = contexto.get("catalogo") or {}
        tentativas = contexto.get("tentativas") if isinstance(contexto.get("tentativas"), list) else []
        rodada.turnos.append(TurnoSimulado(
            id=id_turno, situacao=turno.get("situacao") or "", motivo=turno.get("motivo") or "",
            etapa_antes=turno.get("etapa_antes"), etapa_depois=turno.get("etapa_depois"),
            transferir_para=catalogo.get("transferir_para") or "", ferramenta=catalogo.get("ferramenta") or "",
            mensagens=[m.texto for m in mensagens if m.texto],
            midias=[_midia(m) for m in mensagens if not m.texto],
            envios=[("texto", m.texto) if m.texto else ("midia", _midia(m)) for m in mensagens],
            resposta_mensagens=list((turno.get("resposta") or {}).get("mensagens") or []),
            reprovacoes=list((turno.get("resposta") or {}).get("reprovacoes") or []),
            tentativas=[t for t in tentativas if isinstance(t, (dict, str))]))
    novos = helena.registros[antes_env:]
    rodada.enviadas = [r["texto"] for r in novos]
    rodada.enviadas_ia = [r["texto"] for r in novos if r["origem"] == "ia"]
    rodada.enviadas_sistema = [r["texto"] for r in novos if r["origem"] == "sistema"]
    rodada.eventos = list(repo.eventos[antes_eventos:])
    rodada.chamadas = list(repo.chamadas[antes_chamadas:])
    rodada.faltas = _faltas(modelo)[antes_faltas:]
    rodada.etapa_depois = sim.etapa_do_lead()
    rodada.estado_depois = lead.estado if lead else None
    rodada.fatos_depois = await repo.fatos_vigentes(lead.id) if lead else {}
    return rodada


def _parada(rodada: Rodada, conversa: Conversa, cen: Cenario) -> str | None:
    if rodada.faltas:
        return "cassete_falta"
    if any(f.codigo == "desvio" for f in rodada.falhas):
        return "desvio"
    if rodada.estado_depois in ("pausado", "encerrado"):
        return "contrato_assinado" if rodada.etapa_depois == "contrato_assinado" else f"lead_{rodada.estado_depois}"
    if rodada.etapa_depois == "contrato_assinado":
        return "contrato_assinado"
    if any(t.etapa_antes == "desqualificado" and t.situacao == "respondido" for t in rodada.turnos):
        return "desqualificado"
    if rodada.etapa_depois in cen.limites.parar_em:
        return f"parar_em:{rodada.etapa_depois}"
    if checagens.laco(conversa.rodadas) or checagens.laco_do_lead(conversa.rodadas):
        return "laco"
    return None


def _trajetoria(inicial: str | None, rodadas: list[Rodada]) -> list[str]:
    caminho: list[str] = [inicial] if inicial else []
    for r in rodadas:
        for etapa in [t.etapa_depois for t in r.turnos] + [r.etapa_depois]:
            if etapa and (not caminho or caminho[-1] != etapa):
                caminho.append(etapa)
    return caminho


async def rodar_conversa(cen: Cenario, modelo: Modelo, lead: Any = None, *, real: bool = False,
                         teto: custo.Teto | None = None, snapshot: dict[str, Any] | None = None,
                         modelo_lead: Modelo | None = None, tipo_lead: str | None = None) -> Conversa:
    """Roda a conversa até uma regra de parada e devolve tudo o que aconteceu, já checado."""
    snap = snapshot or cen.carregar_agente()
    conversa = Conversa(cenario=cen, snapshot=snap)
    regras = checagens.Regras(cen, snap)
    lead = lead or leads_simulados.criar(cen.lead, tipo=tipo_lead, modelo=modelo_lead)
    with relogio.congelar(cen.agora) as rel, efeitos_falsos.cep_falso(cen.ferramentas.cep) as cep:
        sim = montagem.montar(cen, modelo, snap, real=real, agora=rel.agora_utc)
        conversa.simulacao = sim
        inicial = sim.etapa_do_lead()
        falas = lead.abrir()
        n = registradas_do_lead = 0
        try:
            while True:
                n += 1
                if n > cen.limites.turnos:
                    conversa.parada = "limite_turnos"
                    break
                reserva = 0.0
                if teto is not None:
                    reservado = teto.reservar()              # reserva antes: conversas em paralelo não furam o teto
                    if reservado is None:
                        conversa.parada = "teto_de_custo"
                        break
                    reserva = reservado
                try:
                    rodada = await _rodada(sim, rel, falas, n, modelo)
                except BaseException:
                    if teto is not None:
                        teto.liberar(reserva)
                    raise
                links = {c.link for c in sim.efeitos.contratos}
                rodada.falhas = checagens.por_turno(rodada, regras, conversa.rodadas, links)
                for fala in falas:
                    if falha := checagens.conferir_espera(fala, rodada, regras):
                        rodada.falhas.append(falha)
                        break
                rodada.trava_sombra = dict(checagens.trava_sombra(rodada, regras))
                conversa.rodadas.append(rodada)
                if teto is not None:
                    teto.registrar(rodada.chamadas, reserva=reserva)
                if parada := _parada(rodada, conversa, cen):
                    conversa.parada = parada
                    break
                reserva_lead = 0.0
                if teto is not None and isinstance(lead, leads_simulados.LeadIA):
                    reservado = teto.reservar(custo.previsto_lead_ia(lead.nome_modelo))   # o lead de IA também gasta
                    if reservado is None:
                        conversa.parada = "teto_de_custo"
                        break
                    reserva_lead = reservado
                try:
                    falas = await lead.responder(rodada.enviadas, rodada=n + 1)
                finally:
                    if teto is not None:
                        do_lead = list(getattr(lead, "chamadas", []))
                        teto.registrar(do_lead[registradas_do_lead:], turnos=0, reserva=reserva_lead)
                        registradas_do_lead = len(do_lead)
                if falas is None:
                    conversa.lead_invalido = getattr(lead, "invalido", None)
                    conversa.parada = "lead_invalido" if conversa.lead_invalido else "lead_saiu"
                    break
        finally:
            await sim.fechar()

        repo = sim.repo
        id_lead = sim.lead().id if sim.lead() else None
        conversa.trajetoria = _trajetoria(inicial, conversa.rodadas)
        conversa.estado_final = sim.lead().estado if id_lead else None
        conversa.etapa_final = sim.etapa_do_lead()
        conversa.fatos_finais = await repo.fatos_vigentes(id_lead) if id_lead else {}
        conversa.fatos_historico = list(repo.fatos.get(id_lead, [])) if id_lead else []
        conversa.acoes = [dict(a) for a in repo.acoes]
        conversa.contratos = [vars(c) for c in sim.efeitos.contratos]
        conversa.chamadas = list(repo.chamadas) + [vars(c) for c in getattr(lead, "chamadas", [])]
        conversa.custo = custo.somar(conversa.chamadas)
        conversa.ferramentas = {"zapsign": sum(1 for r in conversa.rodadas for t in r.turnos if t.ferramenta == "zapsign"),
                                "cep": len(cep.consultas), **sim.efeitos.contagem()}
    conversa.falhas = [f for r in conversa.rodadas for f in r.falhas] + checagens.da_conversa(conversa, regras)
    return conversa
