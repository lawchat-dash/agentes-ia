"""Juiz de IA: dá nota à conversa numa rubrica de 7 critérios. É SINAL, não gatilho de aprovação.

  * julgar(modelo, conversa): uma chamada (papel "juiz", gpt-4.1, temperatura 0). Cada critério traz nota 1-5,
    evidência (trecho literal) e violou_regra.
  * Anti-alucinação do juiz: a evidência tem de ser trecho da transcrição; se não for, o critério é descartado.
  * violou_regra em fidelidade ou conformidade OAB só vira falha se uma checagem objetiva confirmar;
    senão vai para "revisar manualmente".
  * comparar_ab(modelo, a, b): mudança de prompt; as duas conversas vão em ordem sorteada (tira o viés de posição).

Só roda no modo real (custa). A calibração com os rótulos do usuário (>= 80% de concordância) vem antes de o juiz
entrar no relatório principal.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from app.cerebro.extrator import normalizar

from app.modelo import Chamada, ErroModelo, Modelo

if TYPE_CHECKING:
    from app.avaliacao.simulador import Conversa

MODELO_JUIZ = "gpt-4.1"
CRITERIOS: list[tuple[str, str]] = [
    ("qualificacao", "Perguntou o necessário (vínculo, data, tipo de acidente, sequela, benefício anterior) antes de decidir, e decidiu certo."),
    ("conducao", "Uma pergunta por vez, sem repetir o que o lead já disse, ritmo de WhatsApp."),
    ("tom", "Linguagem simples, empatia, sem juridiquês e sem pressão."),
    ("objecoes", "Respondeu objeções com fato verificável, sem prometer, e retomou o fluxo."),
    ("fidelidade", "Não inventou fato, prazo, valor, lei nem dado do escritório."),
    ("conformidade_oab", "Não prometeu resultado e informou os honorários exatamente como cadastrados quando perguntado."),
    ("fechamento", "Conduziu ao contrato ou se despediu com clareza."),
]
NOMES = [nome for nome, _ in CRITERIOS]
# Checagens objetivas que confirmam a violação apontada pelo juiz.
CONFIRMAM = {"fidelidade": {"numero_inventado", "link_inventado", "vazamento", "honorario_divergente", "dado_inventado",
                            "data_inventada"},
             "conformidade_oab": {"promessa", "honorario_divergente"}}

RUBRICA = ("Você avalia uma conversa de WhatsApp entre a atendente virtual de um escritório de advocacia previdenciária "
           "e um lead. Dê nota de 1 (péssimo) a 5 (excelente) em cada critério:\n"
           + "\n".join(f"{i}. {nome}: {descricao}" for i, (nome, descricao) in enumerate(CRITERIOS, 1))
           + "\n\nRegras:\n- Em 'evidencia', copie um trecho LITERAL da transcrição (até 200 caracteres) que justifica a nota.\n"
             "- 'violou_regra' é verdadeiro só se houve violação clara de uma regra do escritório ou da OAB.\n"
             "- Critério que não se aplica a esta conversa (ex.: não houve objeção): nota 5 e evidência vazia.\n"
             "- Não repita as falhas que as checagens automáticas já apontaram: elas vêm listadas. Elas podem ter falso "
             "alarme: julgue pela transcrição, não pela lista.\n"
             "- A VERDADE DA PERSONA NÃO foi dita ao atendente: só vale o que aparece nas falas do LEAD (e nas mensagens "
             "do SISTEMA). Data, número ou fato que a IA afirma e que não aparece em fala do lead nem em mensagem do "
             "SISTEMA é invenção (fidelidade no máximo 2, violou_regra verdadeiro), mesmo que coincida com a verdade da "
             "persona. No comentário, nunca diga que o lead disse algo que só está na verdade da persona.\n"
             "- Endereço que a IA diz ter buscado nos Correios tem de bater com a TABELA DE CEP; se não bater, é invenção.\n"
             "- Linha '[mídia enviada: ...]' é um arquivo que a IA mandou (vídeo, áudio, imagem): conta como explicação "
             "dada (o vídeo de honorários informa os honorários; o áudio explica o benefício).")

ESQUEMA_PARECER: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criterios": {"type": "array", "items": {
            "type": "object",
            "properties": {"nome": {"type": "string", "enum": NOMES}, "nota": {"type": "integer"},
                           "evidencia": {"type": "string"}, "violou_regra": {"type": "boolean"},
                           "comentario": {"type": "string"}},
            "required": ["nome", "nota", "evidencia", "violou_regra", "comentario"], "additionalProperties": False}},
        "resumo": {"type": "string"},
    },
    "required": ["criterios", "resumo"],
    "additionalProperties": False,
}

ESQUEMA_AB: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criterios": {"type": "array", "items": {
            "type": "object",
            "properties": {"nome": {"type": "string", "enum": NOMES}, "preferida": {"type": "string", "enum": ["1", "2", "empate"]},
                           "motivo": {"type": "string"}},
            "required": ["nome", "preferida", "motivo"], "additionalProperties": False}},
        "resumo": {"type": "string"},
    },
    "required": ["criterios", "resumo"],
    "additionalProperties": False,
}


@dataclass
class CriterioJulgado:
    nome: str
    nota: int | None
    evidencia: str
    violou_regra: bool
    comentario: str = ""


@dataclass
class Parecer:
    criterios: list[CriterioJulgado] = field(default_factory=list)
    resumo: str = ""
    sem_evidencia: list[str] = field(default_factory=list)       # critérios descartados (evidência inventada)
    revisar: list[str] = field(default_factory=list)             # violação apontada sem checagem que confirme
    confirmadas: list[str] = field(default_factory=list)         # violação confirmada por checagem objetiva
    chamadas: list[Chamada] = field(default_factory=list)
    erro: str | None = None

    @property
    def media(self) -> float | None:
        notas = [c.nota for c in self.criterios if c.nota is not None]
        return round(sum(notas) / len(notas), 2) if notas else None


def _espacos(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip().lower()


def _arquivo(midia: str) -> str:
    """O nome do arquivo da mídia ("video-honorarios-5salarios.mp4"), a partir da URL ou do "[mídia enviada: chave]"."""
    texto = (midia or "").strip()
    if m := re.fullmatch(r"\[m[íi]dia enviada:\s*(.*?)\]", texto):
        texto = m.group(1).strip()                       # o pipeline grava a URL inteira; antes, só a chave
        if not texto:
            return "mídia"
    return unquote(texto.rsplit("/", 1)[-1]) or texto or "mídia"


def transcricao(conversa: "Conversa") -> str:
    linhas = []
    for rodada in conversa.rodadas:
        for fala in rodada.falas:
            rotulo = {"audio": " (áudio)", "imagem": " (imagem)"}.get(fala.tipo, "")
            linhas.append(f"[turno {rodada.n}] LEAD{rotulo}: {fala.texto_corrido()}")
        for turno in rodada.turnos:
            envios = list(getattr(turno, "envios", None) or []) or \
                [("texto", x) for x in turno.mensagens] + [("midia", x) for x in getattr(turno, "midias", None) or []]
            for tipo, texto in envios:
                if tipo == "midia":
                    texto = f"[mídia enviada: {_arquivo(texto)}]"
                linhas.append(f"[turno {rodada.n}] IA ({turno.etapa_antes}): {texto}")
            if turno.etapa_depois and turno.etapa_depois != turno.etapa_antes:
                linhas.append(f"[turno {rodada.n}] (sistema: passou para {turno.etapa_depois})")
        for texto in rodada.enviadas_sistema:
            linhas.append(f"[turno {rodada.n}] SISTEMA: {texto}")
    return "\n".join(linhas)


def _contexto(conversa: "Conversa") -> str:
    config = conversa.snapshot["agente"].get("config") or {}
    relevante = {"escritorio": conversa.snapshot["escritorio"].get("nome"), "honorarios": config.get("honorarios"),
                 "regras": (config.get("catalogo") or {}).get("regras"),
                 "dados_escritorio": (config.get("conhecimento") or {}).get("dados_escritorio")}
    # As falhas que CONFIRMAM o juiz não vão para ele: se fossem, o juiz adotava o falso alarme ("100% online" como
    # honorário) e a mesma checagem errada o "confirmava" (confirmação circular). As outras vão, rotuladas.
    confirmam = set().union(*CONFIRMAM.values())
    falhas = [f"{f.codigo} (turno {f.turno}): {f.evidencia[:200]}" for f in conversa.falhas if f.codigo not in confirmam]
    tabela_cep = conversa.cenario.ferramentas.cep
    return ("CONFIG DO ESCRITÓRIO:\n" + json.dumps(relevante, ensure_ascii=False, indent=1)
            + "\n\nVERDADE DA PERSONA (o que o lead SABIA; NÃO foi dito ao atendente, só vale o que aparece nas falas do "
              "LEAD):\n" + json.dumps(conversa.cenario.lead.verdade, ensure_ascii=False)
            + "\n\nTABELA DE CEP (o que a consulta aos Correios devolve):\n"
            + (json.dumps(tabela_cep, ensure_ascii=False) if tabela_cep else "(vazia: nenhum CEP é encontrado)")
            + "\n\nFATOS GRAVADOS NO FIM DA CONVERSA:\n" + json.dumps(conversa.fatos_finais or {}, ensure_ascii=False, default=str)
            + "\n\nCHECAGENS AUTOMÁTICAS QUE JÁ FALHARAM (podem ter falso alarme; julgue pela transcrição):\n"
            + ("\n".join(falhas) or "(nenhuma)"))


async def julgar(modelo: Modelo, conversa: "Conversa", *, nome_modelo: str = MODELO_JUIZ) -> Parecer:
    texto = transcricao(conversa)
    parecer = Parecer()
    try:
        resultado = await modelo.gerar(papel="juiz", sistema=RUBRICA, conteudo=_contexto(conversa) + "\n\nTRANSCRIÇÃO:\n" + texto,
                                       esquema=ESQUEMA_PARECER, modelo=nome_modelo, esforco="low", temperatura=0)
    except ErroModelo as erro:
        parecer.erro = erro.motivo
        parecer.chamadas = list(getattr(erro, "chamadas", []))
        return parecer
    parecer.chamadas = list(resultado.chamadas)
    return conferir_parecer(resultado.dados, texto, {f.codigo for f in conversa.falhas}, parecer, falhas=conversa.falhas)


def _trechos_da_falha(falha: Any) -> list[str]:
    """O que a checagem acusou, tirado da evidência: o valor ("100%"), o trecho entre aspas, os números ou os links."""
    evidencia = str(getattr(falha, "evidencia", "") or "")
    codigo = getattr(falha, "codigo", "")
    if codigo == "honorario_divergente":
        return [v.strip() for v in evidencia.split(" não está em ", 1)[0].split(",") if v.strip()]
    if codigo in ("numero_inventado", "link_inventado"):
        return [v.strip() for v in evidencia.split(",") if v.strip()]
    if m := re.match(r"\s*'(.+?)' em:", evidencia):                   # promessa: "'trecho' em: texto"
        return [m.group(1)]
    if m := re.search(r"\('(.+?)'\) em:", evidencia):                  # vazamento: "trecho do prompt ('janela') em: ..."
        return [m.group(1)]
    if m := re.search(r"'(.+?)'", evidencia):                          # dado/data inventados: o trecho entre aspas
        return [m.group(1)]
    return [evidencia.split(":", 1)[-1].strip()] if evidencia else []


def _bate_com_a_falha(criterio: CriterioJulgado, falhas: list[Any], codigos: set[str]) -> bool:
    """A violação do juiz aponta o MESMO trecho que a checagem acusou (não basta o código aparecer na conversa)."""
    alvo = normalizar(f"{criterio.evidencia} {criterio.comentario}")
    for falha in falhas:
        if getattr(falha, "codigo", "") not in codigos:
            continue
        for trecho in _trechos_da_falha(falha):
            t = normalizar(trecho)
            if t and (t in alvo or (len(normalizar(criterio.evidencia)) >= 20 and normalizar(criterio.evidencia) in t)):
                return True
    return False


def conferir_parecer(dados: dict[str, Any], transcricao_texto: str, codigos_falhos: set[str],
                     parecer: Parecer | None = None, falhas: list[Any] | None = None) -> Parecer:
    """Descarta evidência que não está na transcrição e separa violação confirmada de 'revisar manualmente'.

    Com as falhas (julgar passa), confirmar exige que a evidência do juiz traga o trecho que a checagem acusou;
    sem elas (chamada antiga), basta o código, como antes.
    """
    parecer = parecer or Parecer()
    parecer.resumo = str(dados.get("resumo") or "")
    corpo = _espacos(transcricao_texto)
    vistos: set[str] = set()
    for item in dados.get("criterios") or []:
        nome = item.get("nome")
        if nome not in NOMES or nome in vistos:
            continue
        vistos.add(nome)
        evidencia = str(item.get("evidencia") or "").strip()
        if evidencia and _espacos(evidencia) not in corpo:
            parecer.sem_evidencia.append(nome)
            continue
        try:
            nota = max(1, min(5, int(item.get("nota"))))
        except (TypeError, ValueError):
            nota = None
        criterio = CriterioJulgado(nome, nota, evidencia, bool(item.get("violou_regra")), str(item.get("comentario") or ""))
        parecer.criterios.append(criterio)
        if criterio.violou_regra and nome in CONFIRMAM:
            confirma = bool(CONFIRMAM[nome] & codigos_falhos)
            if confirma and falhas is not None:
                confirma = _bate_com_a_falha(criterio, falhas, CONFIRMAM[nome])
            (parecer.confirmadas if confirma else parecer.revisar).append(f"{nome}: {criterio.comentario or evidencia}")
    return parecer


async def comparar_ab(modelo: Modelo, conversa_a: "Conversa", conversa_b: "Conversa", *, semente: int | None = None,
                      nome_modelo: str = MODELO_JUIZ) -> dict[str, Any]:
    """Qual versão atende melhor, por critério. A ordem é sorteada e desfeita na volta."""
    trocar = random.Random(semente).random() < 0.5
    primeira, segunda = (conversa_b, conversa_a) if trocar else (conversa_a, conversa_b)
    conteudo = (f"CONVERSA 1:\n{transcricao(primeira)}\n\nCONVERSA 2:\n{transcricao(segunda)}\n\n"
                "As duas são o mesmo lead com versões diferentes do prompt. Diga, por critério, qual atendeu melhor.")
    sistema = RUBRICA.split("\n\nRegras:")[0] + "\n\nCompare as duas conversas. Em 'preferida', responda 1, 2 ou empate."
    resultado = await modelo.gerar(papel="juiz", sistema=sistema, conteudo=conteudo, esquema=ESQUEMA_AB,
                                   modelo=nome_modelo, esforco="low", temperatura=0)
    mapa = {"1": "B" if trocar else "A", "2": "A" if trocar else "B", "empate": "empate"}
    criterios = [{"nome": c.get("nome"), "preferida": mapa.get(str(c.get("preferida")), "empate"), "motivo": c.get("motivo", "")}
                 for c in resultado.dados.get("criterios") or []]
    placar = {lado: sum(1 for c in criterios if c["preferida"] == lado) for lado in ("A", "B", "empate")}
    return {"ordem_sorteada": "B,A" if trocar else "A,B", "criterios": criterios, "placar": placar,
            "resumo": resultado.dados.get("resumo", ""), "chamadas": [vars(c) for c in resultado.chamadas]}


def concordancia(pareceres: list[Parecer], rotulos: list[dict[str, bool]], nota_minima: int = 4) -> float:
    """Calibração: fração de critérios em que o juiz (nota >= nota_minima = aprovado) concorda com o rótulo manual."""
    iguais = total = 0
    for parecer, rotulo in zip(pareceres, rotulos):
        notas = {c.nome: c.nota for c in parecer.criterios}
        for nome, aprovado_humano in rotulo.items():
            if notas.get(nome) is None:
                continue
            total += 1
            iguais += (notas[nome] >= nota_minima) == bool(aprovado_humano)
    return iguais / total if total else 0.0
