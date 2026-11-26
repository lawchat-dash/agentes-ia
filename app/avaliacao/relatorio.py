"""Relatório da bateria: resultado.json (contrato com o painel), relatorio.md e uma transcrição por rodada.

Fica em avaliacao/resultados/AAAA-MM-DD_HHMM_<agente>/ (no .gitignore). O resultado.json não tem horário nem
duração: tocar o cassete duas vezes dá o mesmo arquivo, byte a byte.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.avaliacao.cenario import PASTA_RESULTADOS

if TYPE_CHECKING:
    from app.avaliacao.juiz import Parecer
    from app.avaliacao.simulador import Conversa


# ---------------------------------------------------------------------------- contrato (pydantic)
class FalhaJ(BaseModel):
    codigo: str
    gravidade: str
    turno: int | None = None
    evidencia: str = ""


class CustoJ(BaseModel):
    por_papel: dict[str, float] = Field(default_factory=dict)
    total_usd: float = 0.0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache: int = 0
    chamadas: int = 0


class CriterioJ(BaseModel):
    nome: str
    nota: int | None = None
    evidencia: str = ""
    violou_regra: bool = False


class JuizJ(BaseModel):
    criterios: list[CriterioJ] = Field(default_factory=list)
    media: float | None = None
    revisar: list[str] = Field(default_factory=list)
    confirmadas: list[str] = Field(default_factory=list)
    sem_evidencia: list[str] = Field(default_factory=list)
    erro: str | None = None


class LinhaJ(BaseModel):
    turno: int
    autor: str                       # lead | ia | sistema
    etapa: str | None = None
    tipo: str = "texto"
    texto: str = ""
    transferiu_para: str | None = None
    ferramenta: str | None = None
    barrada_por: list[str] = Field(default_factory=list)   # não vazio = tentativa barrada pela trava (o lead NÃO recebeu)


class RodadaJ(BaseModel):
    n: int
    aprovado: bool
    invalida: str | None = None      # rodada inválida (lead de IA, cortada pelo teto): não conta como aprovada
    trajetoria: list[str] = Field(default_factory=list)
    parada: str = ""
    estado_final: str | None = None
    falhas: list[FalhaJ] = Field(default_factory=list)
    trava_sombra: dict[str, int] = Field(default_factory=dict)
    ferramentas: dict[str, int] = Field(default_factory=dict)
    contratos: list[dict[str, Any]] = Field(default_factory=list)
    custo: CustoJ = Field(default_factory=CustoJ)
    juiz: JuizJ | None = None
    transcricao: list[LinhaJ] = Field(default_factory=list)


class CenarioJ(BaseModel):
    id: str
    descricao: str = ""
    aprovado: bool | None = None     # None = não rodou (sem cassete, teto...)
    taxa: str = "0/0"
    pulado: str | None = None
    por_checagem: dict[str, str] = Field(default_factory=dict)   # código -> "x/N rodadas"
    rodadas: list[RodadaJ] = Field(default_factory=list)


class AgenteJ(BaseModel):
    id: str
    nome: str
    hash_prompts: str


class Bateria(BaseModel):
    versao: int = 1
    agente: AgenteJ
    modo: str
    rodadas: int
    custo_total_usd: float = 0.0
    custo_por_papel: dict[str, float] = Field(default_factory=dict)
    parou_no_teto: bool = False
    cenarios: list[CenarioJ] = Field(default_factory=list)


# ---------------------------------------------------------------------------- montagem
def hash_prompts(snapshot: dict[str, Any]) -> str:
    agente = snapshot["agente"]
    corpo = {"etapas": [(e.get("codigo"), e.get("instrucao") or "", e.get("modelo")) for e in agente.get("etapas") or []],
             "config": agente.get("config") or {}, "escritorio": snapshot["escritorio"].get("nome")}
    return hashlib.sha256(json.dumps(corpo, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def agente_j(snapshot: dict[str, Any]) -> AgenteJ:
    agente = snapshot["agente"]
    return AgenteJ(id=str(agente.get("id")), nome=str(agente.get("nome")), hash_prompts=hash_prompts(snapshot))


def transcricao(conversa: "Conversa") -> list[LinhaJ]:
    """O que aconteceu, turno a turno. A tentativa barrada pela trava entra antes da resposta enviada, marcada."""
    from app.avaliacao.simulador import ler_tentativa

    linhas: list[LinhaJ] = []
    for r in conversa.rodadas:
        for fala in r.falas:
            texto = fala.texto_corrido() if fala.tipo != "imagem" else f"{fala.texto or ''} [imagem: {fala.descricao}]".strip()
            linhas.append(LinhaJ(turno=r.n, autor="lead", etapa=r.etapa_antes, tipo=fala.tipo, texto=texto))
        for t in r.turnos:
            for tentativa in t.tentativas:
                texto, motivos = ler_tentativa(tentativa)
                linhas.append(LinhaJ(turno=r.n, autor="ia", etapa=t.etapa_antes, texto=texto, barrada_por=motivos))
            transferiu = t.etapa_depois if t.etapa_depois and t.etapa_depois != t.etapa_antes else None
            # Textos e mídias na ordem em que saíram (o PTV.mp4 do T1, o áudio "Como Funciona", o vídeo de honorários):
            # sem a mídia, "Conseguiu entender certinho?" parecia vir sem explicação antes.
            envios = list(getattr(t, "envios", None) or []) or \
                [("texto", x) for x in t.mensagens] + [("midia", x) for x in getattr(t, "midias", None) or []]
            if not envios and (transferiu or t.ferramenta):
                envios = [("texto", "")]
            for i, (tipo, texto) in enumerate(envios):
                ultima = i == len(envios) - 1
                linhas.append(LinhaJ(turno=r.n, autor="ia", etapa=t.etapa_antes, tipo="midia" if tipo == "midia" else "texto",
                                     texto=texto, transferiu_para=transferiu if ultima else None,
                                     ferramenta=(t.ferramenta or None) if ultima else None))
        for texto in r.enviadas_sistema:
            linhas.append(LinhaJ(turno=r.n, autor="sistema", etapa=r.etapa_depois, texto=texto))
    return linhas


def juiz_j(parecer: "Parecer | None") -> JuizJ | None:
    if parecer is None:
        return None
    return JuizJ(criterios=[CriterioJ(nome=c.nome, nota=c.nota, evidencia=c.evidencia, violou_regra=c.violou_regra)
                            for c in parecer.criterios],
                 media=parecer.media, revisar=parecer.revisar, confirmadas=parecer.confirmadas,
                 sem_evidencia=parecer.sem_evidencia, erro=parecer.erro)


def rodada_j(conversa: "Conversa", n: int, parecer: "Parecer | None" = None) -> RodadaJ:
    return RodadaJ(
        n=n, aprovado=conversa.aprovada, invalida=conversa.lead_invalido or conversa.nao_concluida,
        trajetoria=conversa.trajetoria,
        parada=conversa.parada, estado_final=conversa.estado_final,
        falhas=[FalhaJ(**f.como_dict()) for f in conversa.falhas], trava_sombra=conversa.trava_sombra(),
        ferramentas=dict(sorted(conversa.ferramentas.items())),
        contratos=[{"versao": c["versao"], "situacao": c["situacao"], "campos": sorted(c["dados"])} for c in conversa.contratos],
        custo=CustoJ(**conversa.custo), juiz=juiz_j(parecer), transcricao=transcricao(conversa))


def _desviou(falha: FalhaJ) -> bool:
    """A falha de trajetória mostra um desvio (a vista não é prefixo da esperada), não só uma conversa curta."""
    if falha.codigo != "trajetoria":
        return False
    m = re.search(r"vista (\[.*?\]) \| esperada (\[.*?\])", falha.evidencia)
    if not m:
        return False
    try:
        vista, alvo = ast.literal_eval(m.group(1)), ast.literal_eval(m.group(2))
    except (ValueError, SyntaxError):
        return False
    return vista != alvo[:len(vista)]


def cenario_j(caso: Any, rodadas: list[RodadaJ], pulado: str | None = None) -> CenarioJ:
    """Critério: falha crítica em qualquer rodada reprova; falha alta tolera no máximo 1 em 3 rodadas.

    Rodada inválida (lead sem assunto, anti-cooperação do lead de IA, cortada pelo teto de custo) não conta como
    aprovada, mas o que a IA disse antes da invalidação vale: falha crítica ou alta nela entra na conta (a rodada passa
    a contar). Sem isso, uma promessa no t4 seguida de perguntas fora do cartão sumia do resultado (no gravar e no
    cassete só há 1 rodada) e o cenário saía "pulado".
    """
    from app.avaliacao.checagens import ALTA, CRITICA, DO_FIM_DA_CONVERSA

    def contam(r: RodadaJ) -> list[FalhaJ]:
        """Na rodada inválida, as checagens do fim da conversa não contam: ela não chegou ao fim. A trajetória que
        DESVIOU (a vista não é prefixo da esperada) conta: não é a conversa curta, é a IA indo para o lugar errado (sc14:
        lead CLT mandado ao período de graça, e o cartão sem assunto para a demissão invalidava a rodada)."""
        return [f for f in r.falhas if not r.invalida or f.codigo not in DO_FIM_DA_CONVERSA or _desviou(f)]

    validas = [r for r in rodadas if not r.invalida]
    cortadas = [r for r in rodadas if r.parada == "teto_de_custo"]
    graves = [r for r in rodadas if r.invalida and any(f.gravidade in (CRITICA, ALTA) for f in contam(r))]
    base = validas + graves
    criticas = any(f.gravidade == CRITICA for r in base for f in contam(r))
    if pulado or not base:
        motivo = ("conversa cortada pelo teto de custo antes de terminar" if cortadas
                  else "todas as rodadas foram inválidas: " + next((r.invalida for r in rodadas if r.invalida), "?"))
        return CenarioJ(id=caso.id, descricao=caso.descricao, aprovado=None, taxa=f"0/{len(rodadas)}",
                        pulado=pulado or motivo, rodadas=rodadas)
    com_alta = sum(1 for r in base if any(f.gravidade == ALTA for f in contam(r)))
    aprovado = not criticas and bool(validas) and com_alta <= len(base) // 3
    contadas = base
    por_checagem: Counter[str] = Counter()
    for r in contadas:
        for codigo in {f.codigo for f in contam(r)}:
            por_checagem[codigo] += 1
    return CenarioJ(id=caso.id, descricao=caso.descricao, aprovado=aprovado,
                    taxa=f"{sum(1 for r in validas if r.aprovado)}/{len(validas)}",
                    por_checagem={c: f"{x}/{len(contadas)}" for c, x in sorted(por_checagem.items())}, rodadas=rodadas)


def fechar(bateria: Bateria) -> Bateria:
    """Soma o custo da bateria inteira por papel."""
    por_papel: dict[str, float] = {}
    for c in bateria.cenarios:
        for r in c.rodadas:
            for papel, usd in r.custo.por_papel.items():
                por_papel[papel] = round(por_papel.get(papel, 0.0) + usd, 6)
    bateria.custo_por_papel = dict(sorted(por_papel.items()))
    bateria.custo_total_usd = round(sum(por_papel.values()), 6)
    return bateria


# ---------------------------------------------------------------------------- arquivos
def nome_de_arquivo(texto: str) -> str:
    return re.sub(r"[^\w.-]+", "-", texto).strip("-") or "sem_nome"


def resultado_json(bateria: Bateria) -> str:
    return bateria.model_dump_json(indent=2) + "\n"


def _trajetoria_comum(cenario: CenarioJ) -> str:
    contagem = Counter(" > ".join(r.trajetoria) for r in cenario.rodadas)
    return contagem.most_common(1)[0][0] if contagem else "-"


def markdown(bateria: Bateria) -> str:
    linhas = [f"# Avaliação do agente {bateria.agente.nome}", "",
              f"Modo **{bateria.modo}**, {bateria.rodadas} rodada(s) por cenário. Prompts `{bateria.agente.hash_prompts}`. "
              f"Custo total: US$ {bateria.custo_total_usd:.4f}." + (" **A bateria parou no teto de custo.**" if bateria.parou_no_teto else ""),
              "", "| Cenário | Resultado | Taxa | Trajetória mais comum | Custo médio (US$) | Juiz (média) |",
              "|---|---|---|---|---|---|"]
    for c in bateria.cenarios:
        resultado = "pulado" if c.aprovado is None else ("aprovado" if c.aprovado else "**reprovado**")
        custo = sum(r.custo.total_usd for r in c.rodadas) / len(c.rodadas) if c.rodadas else 0.0
        notas = [r.juiz.media for r in c.rodadas if r.juiz and r.juiz.media is not None]
        juiz = f"{sum(notas) / len(notas):.2f}" if notas else "-"
        linhas.append(f"| {c.id} | {resultado} | {c.taxa} | {_trajetoria_comum(c)} | {custo:.4f} | {juiz} |")
    pulados = [c for c in bateria.cenarios if c.pulado]
    if pulados:
        linhas += ["", "## Pulados", ""] + [f"- {c.id}: {c.pulado}" for c in pulados]

    graves = [(c, r, f) for c in bateria.cenarios for r in c.rodadas for f in r.falhas if f.gravidade in ("critica", "alta")]
    linhas += ["", "## Falhas críticas e altas", ""]
    if not graves:
        linhas.append("Nenhuma.")
    for c, r, f in graves:
        arquivo = f"transcricoes/{nome_de_arquivo(c.id)}_{r.n}.md"
        linhas.append(f"- **{f.codigo}** ({f.gravidade}) em [{c.id} rodada {r.n}, turno {f.turno}]({arquivo}): {f.evidencia[:300]}")
    medias = Counter(f.codigo for c in bateria.cenarios for r in c.rodadas for f in r.falhas if f.gravidade == "media")
    if medias:
        linhas += ["", "## Métricas (gravidade média)", ""] + [f"- {codigo}: {n}" for codigo, n in medias.most_common()]

    sombra: Counter[str] = Counter()
    for c in bateria.cenarios:
        for r in c.rodadas:
            sombra.update(r.trava_sombra)
    respostas, barradas = sombra.pop("_respostas", 0), sombra.pop("_barradas", 0)
    linhas += ["", "## Trava sombra", ""]
    if respostas:
        motivos = ", ".join(f"{codigo} ({n})" for codigo, n in sombra.most_common(5)) or "nenhum"
        linhas.append(f"Se as travas completas estivessem ligadas no catálogo, {100 * barradas / respostas:.0f}% das "
                      f"{respostas} respostas teriam sido barradas, principalmente por: {motivos}.")
    else:
        linhas.append("Sem respostas do catálogo para conferir.")
    linhas += ["", "## Custo por papel", "", "| Papel | US$ |", "|---|---|"]
    linhas += [f"| {papel} | {usd:.4f} |" for papel, usd in bateria.custo_por_papel.items()] or ["| - | 0 |"]
    revisar = [(c.id, r.n, item) for c in bateria.cenarios for r in c.rodadas if r.juiz for item in r.juiz.revisar]
    if revisar:
        linhas += ["", "## Revisar manualmente (juiz sem confirmação objetiva)", ""]
        linhas += [f"- {cid} rodada {n}: {item}" for cid, n, item in revisar]
    return "\n".join(linhas) + "\n"


def transcricao_md(cenario: CenarioJ, rodada: RodadaJ) -> str:
    linhas = [f"# {cenario.id} — rodada {rodada.n}", "", cenario.descricao, "",
              f"Resultado: **{'aprovada' if rodada.aprovado else 'reprovada'}** · parada `{rodada.parada}` · "
              f"trajetória {' > '.join(rodada.trajetoria)} · US$ {rodada.custo.total_usd:.4f}", ""]
    if rodada.invalida:
        linhas += [f"Rodada inválida: {rodada.invalida}", ""]
    por_turno: dict[int, list[FalhaJ]] = {}
    for f in rodada.falhas:
        por_turno.setdefault(f.turno or 0, []).append(f)
    atual = None
    for linha in rodada.transcricao:
        if linha.turno != atual:
            if atual is not None:
                linhas += [f"> ⚠ **{f.codigo}** ({f.gravidade}): {f.evidencia[:300]}" for f in por_turno.get(atual, [])]
            atual = linha.turno
            linhas += ["", f"### Turno {linha.turno}"]
        rotulo = {"lead": "**Lead**", "ia": f"**IA** [{linha.etapa}]", "sistema": "*Sistema*"}[linha.autor]
        tipo = f" ({linha.tipo})" if linha.tipo != "texto" else ""
        texto = linha.texto.replace("\n", " / ")
        if linha.barrada_por:
            linhas.append(f"- ~~IA [{linha.etapa}]~~ barrada pela trava, não enviada ({'; '.join(linha.barrada_por)}): "
                          f"~~{texto}~~")
            continue
        extra = (f" → **passou para {linha.transferiu_para}**" if linha.transferiu_para else "") + \
                (f" · **ferramenta {linha.ferramenta}**" if linha.ferramenta else "")
        linhas.append(f"- {rotulo}{tipo}: {texto}{extra}")
    if atual is not None:
        linhas += [f"> ⚠ **{f.codigo}** ({f.gravidade}): {f.evidencia[:300]}" for f in por_turno.get(atual, [])]
    gerais = por_turno.get(0, [])
    if gerais:
        linhas += ["", "### Falhas da conversa"] + [f"- **{f.codigo}** ({f.gravidade}): {f.evidencia[:300]}" for f in gerais]
    return "\n".join(linhas) + "\n"


def gravar(bateria: Bateria, pasta: Path | None = None, quando: datetime | None = None) -> Path:
    """Escreve resultado.json, relatorio.md e transcricoes/<cenario>_<n>.md. Devolve a pasta."""
    if pasta is None:
        marca = (quando or datetime.now()).strftime("%Y-%m-%d_%H%M")
        pasta = PASTA_RESULTADOS / f"{marca}_{nome_de_arquivo(bateria.agente.id)}"
    (pasta / "transcricoes").mkdir(parents=True, exist_ok=True)
    (pasta / "resultado.json").write_text(resultado_json(bateria), encoding="utf-8")
    (pasta / "relatorio.md").write_text(markdown(bateria), encoding="utf-8")
    for c in bateria.cenarios:
        for r in c.rodadas:
            (pasta / "transcricoes" / f"{nome_de_arquivo(c.id)}_{r.n}.md").write_text(transcricao_md(c, r), encoding="utf-8")
    return pasta
