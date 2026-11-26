"""Memória longa da conversa: a ficha (resumo) do começo da conversa, refeita pela fila.

Como o bloco 11 do Weaver (n8n): a IA vê as 40 últimas mensagens inteiras; o que é mais antigo vira uma
ficha por lead (agentesia_lead_resumo), refeita a cada 20 mensagens antigas novas pela ação de fila
'resumir_conversa', depois do envio. No prompt entra o bloco '# COMEÇO DA CONVERSA' com a ficha e as
mensagens antigas que ainda não entraram nela.

As funções de texto são puras. As que leem e gravam recebem o repositório (memória ou Postgres).
Nada aqui derruba a resposta: se a leitura falhar, a IA responde só com o histórico.
"""

from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("agentesia.memoria")

JANELA = 40                     # mensagens que a IA vê inteiras (mesmo limite do histórico do turno)
RESUMIR_A_CADA = 20             # antigas sem resumo que disparam uma ficha nova
ANTIGAS_NO_PROMPT = 60          # antigas ainda sem resumo que entram no prompt
CORTE_NO_PROMPT = 600           # caracteres de cada antiga no prompt
LER_PARA_RESUMIR = 150          # mensagens lidas por resumo
CORTE_PARA_RESUMIR = 1500       # caracteres de cada mensagem lida para o resumo
CORTE_DA_CONVERSA = 40_000      # caracteres do trecho mandado à IA do resumo
CORTE_DA_FICHA = 4000           # proteção: a ficha pedida tem até 220 palavras
MODELO = "gpt-4.1-mini"
TEMPERATURA = 0.2
MAX_TOKENS = 500
PAPEL = "resumo_conversa"
AUTORES = ("lead", "ia", "humano", "automacao")   # quem entra no resumo (mensagem de 'sistema' fica de fora)

SISTEMA_DO_RESUMO = """Você mantém a ficha de memória de um atendimento de escritório de advocacia pelo WhatsApp. A ficha será lida por outra IA que continua a conversa.
Atualize a ficha juntando a FICHA ANTERIOR com o TRECHO NOVO. Regras:
- Escreva só o que foi DITO na conversa. Nunca invente, nunca conclua, nunca dê opinião jurídica.
- Se o trecho novo corrige algo da ficha anterior, fique com a informação mais nova.
- Mantenha datas, valores, nomes e números exatamente como foram ditos.
- Não copie link de áudio, vídeo ou imagem.
- No máximo 220 palavras. Texto corrido em tópicos curtos, sem título, neste formato:
- Quem é: (nome, idade, cidade, profissão, se informados)
- Caso: (o que aconteceu, quando, sequelas ou doença, benefício buscado)
- Trabalho e INSS: (vínculo na época, carteira assinada, contribuições, benefícios já recebidos ou negados)
- Já respondido: (perguntas da qualificação que o lead já respondeu, com a resposta)
- Dados pessoais já informados: (somente quais dados ele já passou, sem repetir CPF e RG por extenso)
- Combinados e objeções: (o que foi explicado sobre honorários, dúvidas, resistências, o que ficou de mandar)
- Atendimento humano: (se alguém da equipe falou com ele e o que disse)
Deixe de fora o tópico que não tiver informação."""

ESQUEMA_DO_RESUMO = {"type": "object", "additionalProperties": False,
                     "properties": {"resumo": {"type": "string"}}, "required": ["resumo"]}

CABECALHO = ("# COMEÇO DA CONVERSA (mensagens antigas que não aparecem mais no seu histórico)\n"
             "Use para não repetir perguntas já respondidas. Não cite que existe um resumo.")


@dataclass
class ComecoDaConversa:
    """O que a IA sabe do que ficou fora da janela de 40 mensagens."""

    resumo: str = ""
    antigas: list[dict[str, str]] = field(default_factory=list)   # [{autor, texto}] mais recentes, mais antiga primeiro
    pendentes: int = 0               # antigas fora da janela que ainda não entraram na ficha (todas, não só as 60)
    ate_id_mensagem: str | None = None
    falhou: bool = False             # a leitura falhou: a IA responde sem o bloco e não pede resumo

    def precisa_resumir(self) -> bool:
        return not self.falhou and self.pendentes >= RESUMIR_A_CADA


# ---------------------------------------------------------------------------- texto
def _limpo(texto: Any, corte: int | None = None) -> str:
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    return texto[:corte] if corte else texto


def rotulo(autor: str) -> str:
    """Quem falou, como no n8n ('Lead:' e 'Atendimento:'); a fala da equipe aparece como 'Atendente:'."""
    return {"lead": "Lead: ", "humano": "Atendente: "}.get(autor, "Atendimento: ")


def bloco_comeco_da_conversa(comeco: ComecoDaConversa | None) -> str:
    """Bloco '# COMEÇO DA CONVERSA' do prompt (vazio quando não há nada fora da janela)."""
    if comeco is None:
        return ""
    resumo = (comeco.resumo or "").strip()
    antigas = [m for m in comeco.antigas[-ANTIGAS_NO_PROMPT:] if _limpo(m.get("texto"))]   # as mais perto da janela
    if not resumo and not antigas:
        return ""
    bloco = CABECALHO
    if resumo:
        bloco += "\n\n" + resumo
    if antigas:
        bloco += "\n\nMensagens antigas mais recentes:\n" + "\n".join(
            rotulo(m.get("autor", "")) + _limpo(m.get("texto"), CORTE_NO_PROMPT) for m in antigas)
    return bloco


def montar_pedido(anterior: str | None, trecho: list[dict[str, Any]]) -> tuple[str, str]:
    """Sistema e conteúdo do pedido de resumo: a ficha anterior mais o trecho novo (cortado em 40.000 caracteres)."""
    conversa = "\n".join(rotulo(m.get("autor", "")) + _limpo(m.get("texto"), CORTE_PARA_RESUMIR) for m in trecho)
    conversa = conversa[:CORTE_DA_CONVERSA]
    usuario = "FICHA ANTERIOR:\n" + ((anterior or "").strip() or "(vazia)") + "\n\nTRECHO NOVO:\n" + conversa
    return SISTEMA_DO_RESUMO, usuario


def acao_de_resumo(id_lead: str, comeco: ComecoDaConversa | None) -> dict[str, Any] | None:
    """Ação de fila 'resumir_conversa' quando juntaram 20 ou mais antigas sem resumo; None quando não precisa.

    A chave muda quando a ficha avança ou quando juntam mais 20 antigas: o mesmo pedido não entra duas vezes.
    """
    if comeco is None or not comeco.precisa_resumir():
        return None
    marca = comeco.ate_id_mensagem or "inicio"
    return {"tipo": "resumir_conversa", "chave_unica": f"{id_lead}:resumir_conversa:{marca}:{comeco.pendentes // RESUMIR_A_CADA}",
            "dados": {"pendentes": comeco.pendentes}}


# ---------------------------------------------------------------------------- banco
async def ler_comeco(repo: Any, id_lead: str) -> ComecoDaConversa:
    """Ficha e antigas sem resumo para o prompt. Falha na leitura não derruba a resposta."""
    try:
        dados = await repo.comeco_da_conversa(id_lead, janela=JANELA, limite=ANTIGAS_NO_PROMPT, corte=CORTE_NO_PROMPT)
    except Exception:
        log.warning("não deu para ler o começo da conversa do lead %s", id_lead, exc_info=True)
        return ComecoDaConversa(falhou=True)
    return ComecoDaConversa(resumo=dados.get("resumo") or "", antigas=list(dados.get("antigas") or []),
                            pendentes=int(dados.get("pendentes") or 0), ate_id_mensagem=dados.get("ate_id_mensagem"))


async def pedir_resumo_se_preciso(repo: Any, *, id_escritorio: str, id_lead: str, id_turno: str | None,
                                  comeco: ComecoDaConversa | None) -> bool:
    """Depois do envio: põe 'resumir_conversa' na fila se juntaram 20 ou mais antigas sem resumo."""
    acao = acao_de_resumo(id_lead, comeco)
    if not acao:
        return False
    try:
        await repo.enfileirar_acoes(id_escritorio=id_escritorio, id_lead=id_lead, id_turno=id_turno, acoes=[acao])
    except Exception:
        log.warning("não deu para pedir o resumo da conversa do lead %s", id_lead, exc_info=True)
        return False
    return True


def _extras_do_modelo(modelo: Any) -> dict[str, Any]:
    """Temperatura 0,2 e até 500 tokens de saída, quando o modelo aceita esses ajustes."""
    try:
        parametros = inspect.signature(modelo.gerar).parameters
    except (TypeError, ValueError):
        return {}
    extras: dict[str, Any] = {}
    if "temperatura" in parametros:
        extras["temperatura"] = TEMPERATURA
    if "max_tokens" in parametros:
        extras["max_tokens"] = MAX_TOKENS
    return extras


async def resumir(repo: Any, modelo: Any, id_lead: str) -> tuple[dict[str, Any], list[Any]]:
    """Refaz a ficha do lead: lê até 150 antigas ainda sem resumo, pede o resumo e grava.

    Devolve (resultado, chamadas de IA). Erro da IA sobe como ErroModelo (a fila tenta de novo).
    """
    trecho = await repo.trecho_para_resumir(id_lead, janela=JANELA, limite=LER_PARA_RESUMIR, corte=CORTE_PARA_RESUMIR)
    mensagens = [m for m in trecho.get("mensagens") or [] if _limpo(m.get("texto"))]
    if not mensagens:
        return {"resumo": "nada_para_resumir"}, []
    sistema, conteudo = montar_pedido(trecho.get("resumo"), mensagens)
    resultado = await modelo.gerar(papel=PAPEL, sistema=sistema, conteudo=conteudo, esquema=ESQUEMA_DO_RESUMO,
                                   modelo=MODELO, esforco="low", **_extras_do_modelo(modelo))
    chamadas = list(resultado.chamadas)
    ficha = str(resultado.dados.get("resumo") or "").strip()[:CORTE_DA_FICHA]
    if not ficha:                                   # como no n8n: só grava se a IA devolveu texto
        return {"resumo": "vazio"}, chamadas
    tokens = sum(c.tokens_entrada + c.tokens_cache + c.tokens_saida for c in chamadas) or None
    usado = next((c.modelo for c in reversed(chamadas) if c.sucesso and c.modelo), MODELO)
    await repo.gravar_resumo(id_lead=id_lead, resumo=ficha, ate_id_mensagem=mensagens[-1]["id"],
                             quantidade=len(mensagens), modelo=usado, tokens=tokens)
    return {"resumo": "feito", "mensagens": len(mensagens), "caracteres": len(ficha)}, chamadas
