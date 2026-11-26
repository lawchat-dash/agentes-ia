"""Bateria de avaliação: o ponto único usado pelo CLI, pelo pytest e (no futuro) pelo painel.

Modos:
  falso    modelo roteirizado (app/avaliacao/falso.py): prova o motor, custo zero
  cassete  toca avaliacao/cassetes/<id>.jsonl: código em volta da IA com respostas reais congeladas, custo zero
  real     modelo de verdade (só com teto de custo e chave); não grava
  gravar   modelo de verdade gravando o cassete e a transcrição para revisão (1 rodada por cenário)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from app.avaliacao import checagens, custo, falso, relatorio, simulador
from app.avaliacao.cassete import ModeloGravador
from app.avaliacao.cenario import PASTA_CASSETES, PASTA_TRANSCRICOES, Cenario
from app.modelo import PRECOS_USD_POR_MILHAO, Modelo

MODOS = ("falso", "cassete", "real", "gravar")
CHAVES = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


class ErroDeExecucao(RuntimeError):
    pass


def caminho_do_cassete(caso: Cenario, pasta: Path = PASTA_CASSETES) -> Path:
    return pasta / f"{relatorio.nome_de_arquivo(caso.id)}.jsonl"


def modelo_do_auditor(caso: Cenario) -> str | None:
    """O modelo do auditor neste cenário (como o pipeline escolhe), ou None se o cenário desliga o auditor."""
    config = caso.carregar_agente()["agente"].get("config") or {}
    if config.get("auditor") is False:
        return None
    return (config.get("modelos") or {}).get("auditor") or os.environ.get("AGENTESIA_MODELO_AUDITOR", "gpt-6-luna")


def modelos_usados(casos: list[Cenario], *, juiz: bool = False, lead: str = "cartao") -> set[str]:
    nomes: set[str] = set()
    for caso in casos:
        config = caso.carregar_agente()["agente"].get("config") or {}
        modelos = config.get("modelos") or {}
        nomes |= {modelos.get("etapa") or "gpt-4.1-mini", modelos.get("extrator") or "gpt-4.1-mini"}
        if (auditor := modelo_do_auditor(caso)) is not None:
            nomes.add(auditor)
    if juiz:
        nomes.add("gpt-4.1")
    if lead == "ia":
        nomes.add("gpt-4.1-mini")
    return nomes


def exigir_modo_real(casos: list[Cenario], teto_usd: float | None, *, juiz: bool = False, lead: str = "cartao") -> None:
    """Sem teto ou sem chave, o modo real não roda (e nada é chamado)."""
    if teto_usd is None:
        raise ErroDeExecucao("o modo real exige --teto-usd (ex.: --teto-usd 2)")
    if teto_usd <= 0:
        raise ErroDeExecucao("--teto-usd precisa ser maior que zero")
    from app.config import carregar

    carregar()                                               # lê o .env local, sem sobrescrever o ambiente
    faltam = sorted({CHAVES["anthropic" if m.startswith("claude-") else "openai"] for m in modelos_usados(casos, juiz=juiz, lead=lead)}
                    - {chave for chave in CHAVES.values() if os.environ.get(chave)})
    if faltam:
        raise ErroDeExecucao("o modo real precisa da chave " + " e ".join(faltam) + " no ambiente ou no .env")


async def _uma_conversa(caso: Cenario, n: int, modo: str, *, teto: custo.Teto | None, lead: str, juiz: bool,
                        modelo_real: Modelo | None, pasta_cassetes: Path, roteiros: dict[str, Any] | None,
                        conversas: list[Any] | None) -> relatorio.RodadaJ:
    snapshot = caso.carregar_agente()
    gravador: ModeloGravador | None = None
    if modo == "falso":
        roteiro = (roteiros or {}).get(caso.id)
        modelo: Modelo = falso.modelo_para(caso, snapshot, roteiro)
    elif modo == "cassete":
        gravador = ModeloGravador(None, caminho_do_cassete(caso, pasta_cassetes), "tocar")
        modelo = gravador
    else:
        assert modelo_real is not None
        gravador = ModeloGravador(modelo_real, caminho_do_cassete(caso, pasta_cassetes), "gravar" if modo == "gravar" else "desligado")
        modelo = gravador
    try:
        conversa = await simulador.rodar_conversa(
            caso, modelo, real=modo in ("real", "gravar"), teto=teto, snapshot=snapshot,
            tipo_lead=lead if modo == "real" else "cartao", modelo_lead=modelo_real)   # o cassete grava só com o cartão
    except BaseException:
        if gravador is not None:
            gravador.descartar()                            # erro no meio: o cassete anterior fica como estava
        raise
    cassete_completo = True
    if modo == "gravar" and gravador is not None:
        motivo_incompleto = conversa.nao_concluida or conversa.lead_invalido
        if motivo_incompleto:
            cassete_completo = False
            gravador.descartar()
            conversa.falhas.append(checagens.Falha(
                "cassete_nao_gravado", checagens.MEDIA, None,
                f"{motivo_incompleto}: o cassete e a transcrição anteriores foram mantidos"))
        else:
            gravador.confirmar()
    parecer = None
    if juiz and modo in ("real", "gravar") and modelo_real is not None:
        from app.avaliacao import juiz as juiz_ia

        reserva = teto.reservar(custo.previsto_juiz()) if teto is not None else 0.0
        if reserva is not None:
            try:
                parecer = await juiz_ia.julgar(modelo_real, conversa)
            finally:
                if teto is not None:
                    teto.registrar(parecer.chamadas if parecer else [], turnos=0, reserva=reserva)
            conversa.chamadas += [vars(c) for c in parecer.chamadas]
            conversa.custo = custo.somar(conversa.chamadas)
    if conversas is not None:
        conversas.append(conversa)
    rodada = relatorio.rodada_j(conversa, n, parecer)
    if modo == "gravar" and cassete_completo:
        PASTA_TRANSCRICOES.mkdir(parents=True, exist_ok=True)
        cen = relatorio.CenarioJ(id=caso.id, descricao=caso.descricao, rodadas=[rodada])
        (PASTA_TRANSCRICOES / f"{relatorio.nome_de_arquivo(caso.id)}.md").write_text(
            relatorio.transcricao_md(cen, rodada), encoding="utf-8")
    return rodada


async def rodar_bateria(casos: list[Cenario], modo: str = "cassete", rodadas: int = 1, teto_usd: float | None = None,
                        paralelo: int = 1, lead: str = "cartao", juiz: bool = False, *, modelo_real: Modelo | None = None,
                        pasta_cassetes: Path = PASTA_CASSETES, roteiros: dict[str, Any] | None = None,
                        conversas: list[Any] | None = None) -> relatorio.Bateria:
    """Roda cada caso N vezes e devolve a Bateria (o contrato do resultado.json)."""
    if modo not in MODOS:
        raise ErroDeExecucao(f"modo desconhecido: {modo} (use {', '.join(MODOS)})")
    if not casos:
        raise ErroDeExecucao("nenhum cenário para rodar")
    teto: custo.Teto | None = None
    if modo in ("real", "gravar"):
        exigir_modo_real(casos, teto_usd, juiz=juiz, lead=lead)
        if modelo_real is None:
            from app.modelo import ModeloPorNome

            modelo_real = ModeloPorNome()
        estimado = estimar(casos, 1)
        turnos = sum(c["turnos"] for c in estimado.por_cenario) or 1
        teto = custo.Teto(float(teto_usd), estimativa_turno_usd=estimado.total_usd / turnos)  # type: ignore[arg-type]
    elif teto_usd is not None:
        teto = custo.Teto(float(teto_usd))
    if modo in ("cassete", "gravar"):
        rodadas = 1                                         # o cassete é determinístico: uma rodada basta
    snapshot = casos[0].carregar_agente()
    trava = asyncio.Semaphore(max(1, paralelo))
    pulados: dict[str, str] = {}

    async def uma(caso: Cenario, n: int) -> tuple[str, int, relatorio.RodadaJ | None]:
        if modo == "cassete" and not caminho_do_cassete(caso, pasta_cassetes).exists():
            pulados[caso.id] = f"sem cassete: grave com `python -m app.avaliacao gravar {caso.id.split('[')[0]} --teto-usd 1`"
            return caso.id, n, None
        if modo == "falso" and (roteiros or {}).get(caso.id) is None and falso.roteiro_de(caso.id) is None:
            pulados[caso.id] = "sem roteiro do modelo falso para este cenário"
            return caso.id, n, None
        async with trava:
            if teto is not None and teto.parou:
                pulados.setdefault(caso.id, "a bateria parou no teto de custo")
                return caso.id, n, None
            return caso.id, n, await _uma_conversa(caso, n, modo, teto=teto, lead=lead, juiz=juiz, modelo_real=modelo_real,
                                                   pasta_cassetes=pasta_cassetes, roteiros=roteiros, conversas=conversas)

    feitos = await asyncio.gather(*(uma(caso, n) for caso in casos for n in range(1, rodadas + 1)))
    bateria = relatorio.Bateria(agente=relatorio.agente_j(snapshot), modo=modo, rodadas=rodadas,
                                parou_no_teto=bool(teto and teto.parou))
    for caso in casos:
        dele = sorted((n, r) for cid, n, r in feitos if cid == caso.id and r is not None)
        bateria.cenarios.append(relatorio.cenario_j(caso, [r for _, r in dele], pulado=None if dele else pulados.get(caso.id)))
    return relatorio.fechar(bateria)


def estimar(casos: list[Cenario], rodadas: int = 1, *, juiz: bool = False, lead: str = "cartao") -> custo.Estimativa:
    """Quanto o modo real custaria, sem chamar a API: roda o modelo roteirizado e mede os pedidos."""
    modelo_nome = ((casos[0].carregar_agente()["agente"].get("config") or {}).get("modelos") or {}).get("etapa") or "gpt-4.1-mini"
    estimativa = custo.Estimativa(modelo=modelo_nome, rodadas=rodadas)

    async def medir() -> None:
        for caso in casos:
            auditor = modelo_do_auditor(caso)
            if auditor is not None and auditor not in PRECOS_USD_POR_MILHAO:
                raise ErroDeExecucao(f"{caso.id}: o auditor usaria {auditor}, sem preço em app/modelo.py; fixe "
                                     "config.modelos.auditor no snapshot do agente (ex.: gpt-4.1-mini)")
            roteiro = falso.roteiro_de(caso.id)
            if roteiro is not None:
                modelo = falso.modelo_para(caso, roteiro=roteiro)
                conversa = await simulador.rodar_conversa(caso, modelo)
                pedidos, turnos = modelo.pedidos, len(conversa.rodadas)
            else:                                           # sem roteiro: 2 chamadas por turno, prompt do tamanho do snapshot
                turnos = min(len(caso.lead.assuntos) + len(caso.lead.falas) + 3, caso.limites.turnos)
                sistema = _tamanho_do_sistema(caso)
                pedidos = [{"papel": p, "sistema": "x" * (sistema if p == "etapa" else 12000), "conteudo": "x" * 8000}
                           for _ in range(turnos) for p in ("extrator", "etapa")]
            conta = custo.estimar_pedidos(pedidos, modelo_nome, juiz=juiz, lead_ia=lead == "ia", modelo_auditor=auditor)
            estimativa.por_cenario.append({"id": caso.id, "turnos": turnos, "chamadas": conta["chamadas"], "auditor": auditor,
                                           "tokens_entrada": conta["tokens_entrada"], "usd_conversa": conta["usd"],
                                           "usd_conversa_cache": conta["usd_cache"]})

    _rodar(medir())
    estimativa.total_usd = round(sum(c["usd_conversa"] for c in estimativa.por_cenario) * rodadas, 4)
    estimativa.total_com_cache_usd = round(sum(c["usd_conversa_cache"] for c in estimativa.por_cenario) * rodadas, 4)
    return estimativa


def _tamanho_do_sistema(caso: Cenario) -> int:
    """Caracteres do sistema da etapa na estimativa sem roteiro: a média dos prompts das etapas da trajetória esperada
    (ou de todas) mais ~10 mil do que o motor acrescenta (regras fixas do atendimento, formato, ferramentas, dados do
    escritório, fatos), nunca menos que 12 mil. Os prompts reais do Sousa e Costa têm de 7 a 21 mil caracteres: os 12 mil
    fixos subestimavam o custo; com as regras fixas do motor (6 a 9 mil) o prompt enxuto não cai no piso."""
    etapas = {e.get("codigo"): len(e.get("instrucao") or "") for e in caso.carregar_agente()["agente"].get("etapas") or []}
    caminho = [e for e in (caso.esperado.trajetoria or []) if etapas.get(e)] or [e for e, n in etapas.items() if n]
    if not caminho:
        return 12000
    return max(12000, round(sum(etapas[e] for e in caminho) / len(caminho)) + 10000)


def _rodar(corrotina: Any) -> Any:
    """Roda a corrotina mesmo se já houver um loop (pytest-asyncio): numa thread separada."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(corrotina)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(1) as executor:
        return executor.submit(asyncio.run, corrotina).result()
