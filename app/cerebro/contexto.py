"""O que o sistema sabe e entrega pronto à IA: a data de hoje, a situação do contrato e as contas.

No n8n o agente usava a tool Calculator e lia "A data de hoje é ..." no topo do prompt. Aqui a conta é
feita no código e entra como fato do sistema; a data vem de um relógio que os testes podem fixar.
Tudo é função pura (a data entra por parâmetro quando o teste quer).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.cerebro import auxilio_acidente as aa

FUSO = "America/Sao_Paulo"
DIAS_DA_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")


def agora_em_brasilia(agora: datetime | None = None) -> datetime:
    """Momento no fuso de Brasília (America/Sao_Paulo). Sem fuso no valor, ele é tratado como horário de Brasília."""
    from app.notificacoes import fuso

    local = fuso(FUSO)
    if agora is None:
        return datetime.now(local)
    return agora.replace(tzinfo=local) if agora.tzinfo is None else agora.astimezone(local)


def linha_de_hoje(agora: datetime | None = None) -> str:
    """'Hoje é 24/11/2026 (terça-feira), horário de Brasília 14:30.' (mesma ideia do 'A data de hoje é' do n8n)."""
    momento = agora_em_brasilia(agora)
    return (f"Hoje é {momento.strftime('%d/%m/%Y')} ({DIAS_DA_SEMANA[momento.weekday()]}), "
            f"horário de Brasília {momento.strftime('%H:%M')}. Sempre considere esta data como a data atual.")


# ---------------------------------------------------------------------------- contrato
def _data(valor: datetime | None) -> str | None:
    return agora_em_brasilia(valor).strftime("%d/%m/%Y %H:%M") if valor else None


def texto_do_contrato(situacao: str | None, *, versao: int | None = None, link: str | None = None,
                      gerado_em: datetime | None = None, assinado_em: datetime | None = None) -> str:
    """Situação do contrato para os fatos do sistema, como o bloco 'Fatos e resumo' do n8n.

    Assinado: diz que já foi assinado e quando. Gerado e não assinado: versão, data e o link vigente.
    """
    if situacao == "assinado":
        quando = _data(assinado_em)
        return f"JÁ ASSINADO pelo lead{' em ' + quando if quando else ''} (versão {versao})."
    if situacao == "gerado":
        quando = _data(gerado_em)
        texto = f"já foi gerado (versão {versao}){' em ' + quando if quando else ''} e AINDA NÃO foi assinado."
        if link:
            texto += f" Link: {link} (o sistema reenvia o link se pedirem)"
        return texto
    return "não gerado"


# ---------------------------------------------------------------------------- calculadora
# Fatos que a conta usa; o extrator do catálogo pede estes quando o papel de período de graça está ativo.
# Seguro-desemprego e contribuição por conta própria entram para a calculadora dizer se a pessoa estava coberta: sem eles,
# quem comparava os meses com o prazo era o modelo, de cabeça, e desqualificava quem estava dentro (16 meses com seguro).
FATOS_DO_PERIODO = ("acidente_mes", "acidente_ano", "demissao_mes", "demissao_ano",
                    "demissao_meses_antes_do_acidente", "demissao_ha_muitos_anos",
                    "seguro_desemprego", "contribuiu_por_conta_propria")


def _meses(n: float) -> str:
    return f"{int(n)} {'mês' if int(n) == 1 else 'meses'}"


def meses_entre_saida_e_acidente(fatos: dict[str, Any]) -> str | None:
    """Meses entre a saída do último emprego e o acidente, a partir do que o lead disse. None = falta dado.

    Usa a mesma conta do produto Auxílio-Acidente (aceita datas aproximadas e devolve a faixa possível).
    """
    try:
        if fatos.get("demissao_meses_antes_do_acidente") not in (None, ""):
            n = int(fatos["demissao_meses_antes_do_acidente"])
            return f"cerca de {_meses(n)} (o lead disse quanto tempo antes do acidente saiu do emprego)"
        intervalo = aa._intervalo_meses_entre_demissao_e_acidente(
            {chave: fatos.get(chave) for chave in FATOS_DO_PERIODO if fatos.get(chave) not in (None, "")})
    except (TypeError, ValueError):
        return None
    if intervalo is None:
        return None
    menor, maior = intervalo
    if maior == float("inf"):
        return f"mais de {_meses(menor)} (o lead disse que saiu do emprego faz anos)"
    if maior == 0 and fatos.get("demissao_ano") not in (None, "") and fatos.get("acidente_ano") not in (None, ""):
        acidente_ate = int(fatos["acidente_ano"]) * 12 + int(fatos.get("acidente_mes") or 12)
        saida_desde = int(fatos["demissao_ano"]) * 12 + int(fatos.get("demissao_mes") or 1)
        if acidente_ate < saida_desde:
            if fatos.get("vinculo_na_data") in SEM_CARTEIRA_NA_DATA:
                return SAIDA_DEPOIS_DO_ACIDENTE
            return "nenhum: o acidente foi ANTES da saída do último emprego (ainda estava empregado na data do acidente)"
    if menor == maior:
        return _meses(menor)
    return f"entre {int(menor)} e {_meses(maior)} (datas aproximadas; falta o mês exato)"


CHAVE_COBERTURA = "cobertura pelo INSS na data do acidente (calculado pelo sistema)"
# Na data do acidente o lead não tinha carteira (MEI, autônomo, desempregado): uma saída DEPOIS do acidente não cobre nada.
SEM_CARTEIRA_NA_DATA = ("mei_autonomo_ci", "desempregado", "nunca_trabalhou")
SAIDA_DEPOIS_DO_ACIDENTE = ("a saída informada é DEPOIS do acidente, e na data do acidente o lead não tinha carteira "
                            "assinada: pergunte qual foi o último emprego de carteira assinada ANTES do acidente (mês e "
                            "ano, pode ser aproximado). Se não teve nenhum antes, ele não estava coberto")


def _saida_depois_sem_carteira(fatos: dict[str, Any]) -> bool:
    try:
        if fatos.get("vinculo_na_data") not in SEM_CARTEIRA_NA_DATA:
            return False
        if fatos.get("demissao_ano") in (None, "") or fatos.get("acidente_ano") in (None, ""):
            return False
        acidente_ate = int(fatos["acidente_ano"]) * 12 + int(fatos.get("acidente_mes") or 12)
        saida_desde = int(fatos["demissao_ano"]) * 12 + int(fatos.get("demissao_mes") or 1)
        return acidente_ate < saida_desde
    except (TypeError, ValueError):
        return False


def cobertura_na_data_do_acidente(fatos: dict[str, Any], regras: aa.Regras | None = None) -> tuple[str, str] | None:
    """(resultado, texto) da conta do período de graça, sem citar prazo em meses. None = falta a data da saída.

    resultado: dentro | fora | falta_seguro | perto_do_limite. A decisão do que fazer com isso (contribuição por conta
    própria mantém ou não a cobertura, por exemplo) fica com o roteiro do escritório: aqui só vai a conta."""
    if _saida_depois_sem_carteira(fatos):
        return "falta_saida_antes", "ainda não dá para saber: falta o último emprego de carteira ANTES do acidente"
    dados = {chave: fatos.get(chave) for chave in FATOS_DO_PERIODO if fatos.get(chave) not in (None, "")}
    try:
        decisao = aa.calcular_periodo_graca(dados, regras or aa.Regras())
    except (TypeError, ValueError):
        return None
    if decisao.resultado == "dentro":
        return "dentro", "coberta na data do acidente"
    if decisao.resultado == "fora" or "contribuiu_por_conta_propria" in decisao.faltam \
            or decisao.motivo == "contribuiu_por_conta_propria":
        return "fora", "não coberta pelas datas"
    if "seguro_desemprego" in decisao.faltam:
        return "falta_seguro", ("depende de ter recebido seguro-desemprego (falta saber). Se o lead não lembrar, pergunte "
                                "uma vez de outro jeito (\"depois que saiu, você recebeu umas parcelas do governo por "
                                "alguns meses?\"); se continuar sem saber, siga para o Closer: a equipe confere no CNIS "
                                "depois do contrato")
    if decisao.resultado == "analise_manual":
        return "perto_do_limite", "perto do limite: peça análise humana"
    falta = {"demissao_mes": "falta o mês em que saiu do emprego", "acidente_mes": "falta o mês do acidente"}
    if decisao.resultado == "faltam_dados" and any(f in falta for f in decisao.faltam):
        return "perto_do_limite", "perto do limite (" + "; ".join(falta[f] for f in decisao.faltam if f in falta) + ")"
    return None


def fatos_da_calculadora(fatos: dict[str, Any], agora: datetime | None = None,
                         regras: aa.Regras | None = None) -> dict[str, str]:
    """Fatos calculados pelo código para o papel de período de graça (antiga tool Calculator).

    Tudo sai como FATO, nunca como ordem: o SDR de todo escritório tem a calculadora."""
    saida: dict[str, str] = {}
    meses = meses_entre_saida_e_acidente(fatos)
    if meses:
        saida["meses entre a saída do último emprego e o acidente (calculado pelo sistema)"] = meses
        if cobertura := cobertura_na_data_do_acidente(fatos, regras):
            saida[CHAVE_COBERTURA] = cobertura[1]
    tem_demissao = any(fatos.get(c) not in (None, "") for c in FATOS_DO_PERIODO if c.startswith("demissao"))
    if tem_demissao and not meses and fatos.get("acidente_ano") in (None, ""):
        saida["data do acidente (calculado pelo sistema)"] = "não informada pelo lead (sem ela não há conta)"
    hoje = agora_em_brasilia(agora)
    try:
        if fatos.get("acidente_ano") not in (None, "") and fatos.get("acidente_mes") not in (None, ""):
            desde = (hoje.year * 12 + hoje.month) - (int(fatos["acidente_ano"]) * 12 + int(fatos["acidente_mes"]))
            if desde >= 0:
                saida["meses desde o acidente até hoje (calculado pelo sistema)"] = _meses(desde)
            if desde == 0:
                # O mês de hoje como data do acidente quase sempre é "até hoje dói" lido como data.
                saida["data do acidente igual ao mês atual (calculado pelo sistema)"] = "confirme com o lead"
        dito = fatos.get("demissao_meses_antes_do_acidente")
        if dito not in (None, "") and all(fatos.get(c) not in (None, "") for c in
                                          ("acidente_mes", "acidente_ano", "demissao_mes", "demissao_ano")):
            pelas_datas = (int(fatos["acidente_ano"]) * 12 + int(fatos["acidente_mes"])
                           - int(fatos["demissao_ano"]) * 12 - int(fatos["demissao_mes"]))
            if abs(pelas_datas - int(dito)) > 2:
                saida["conflito nas datas (calculado pelo sistema)"] = (
                    f"o lead disse {_meses(int(dito))} entre a saída e o acidente, mas as datas dão {_meses(max(0, pelas_datas))}: confirme")
    except (TypeError, ValueError):
        pass
    return saida


# ---------------------------------------------------------------------------- calculadora do Salário-Maternidade
# Família salario_maternidade (catalogo.FATOS_MATERNIDADE). Duas contas, só com mês e ano (nunca o dia):
#   1. cobertura na data do evento (parto, adoção/guarda, perda): carteira ativa no parto e rural com documento estão
#      cobertas sem conta; sem carteira ativa (saiu, MEI, autônoma, facultativa, desempregada), o período de graça:
#      12 meses depois da última contribuição ou da saída, +12 com 10 anos ou mais de contribuição, +12 com
#      seguro-desemprego ou registro no SINE, no máximo 36. Meses = (ano_evento - ano_ultima) * 12 + (mes_evento -
#      mes_ultima); empate = dentro. Não há carência (STF, ADI 2.110; IN 188/2025).
#   2. prazo de 5 anos desde o evento até hoje: passou de 5 anos = fora; faltando qualquer coisa = dentro.
# Gestante (ainda não teve o bebê) não tem conta: nunca vai para o Período de Graça e nunca é desqualificada de imediato.
CHAVE_COBERTURA_EVENTO = "cobertura pelo INSS na data do evento (calculado pelo sistema)"
CHAVE_PRAZO_5_ANOS = "prazo de 5 anos (calculado pelo sistema)"
CARTEIRA_ATIVA_NO_PARTO = ("clt_ativa", "domestica", "intermitente")
GRACA_BASE, GRACA_EXTENSAO, GRACA_MAXIMO = 12, 12, 36
PRAZO_DO_PEDIDO_MESES = 60
_EXTENSOES = (("dez_anos_contribuicao", "ter contribuído 10 anos ou mais"),
              ("seguro_desemprego", "ter recebido seguro-desemprego ou ter registro no SINE"))


def _mes_indice(valor: Any) -> int | None:
    """"MM/AAAA" -> ano * 12 + mês (para subtrair). None quando não é mês e ano."""
    from app.cerebro.catalogo import mes_ano

    normal = mes_ano(valor)
    if normal is None:
        return None
    mes, ano = normal.split("/")
    return int(ano) * 12 + int(mes)


def _gestante(fatos: dict[str, Any]) -> bool:
    return str(fatos.get("situacao") or "").strip().lower() == "gestante"


def periodo_de_graca_maternidade(fatos: dict[str, Any]) -> dict[str, Any] | None:
    """Conta da cobertura na data do evento. None = falta dado (ou gestante: sem conta).

    {"resultado": dentro | fora | depende | confirmar, "texto": linha do sistema (sem números), "meses": meses entre a
    última contribuição e o evento (None sem conta), "prazo": meses de período de graça que já valem}."""
    if _gestante(fatos):
        return None
    categoria = str(fatos.get("categoria") or "").strip().lower()
    sem_conta = {"meses": None, "prazo": None}
    if categoria == "estatutaria":
        return {"resultado": "fora", **sem_conta,
                "texto": "não coberta pelo INSS: concursada/estatutária tem regime próprio"}
    if categoria in CARTEIRA_ATIVA_NO_PARTO:
        return {"resultado": "dentro", **sem_conta,
                "texto": "coberta na data do evento (carteira ativa no parto: não precisa de conta)"}
    if categoria == "rural":
        documento = str(fatos.get("rural_tem_documento") or "").strip().lower()
        if documento == "sim":
            return {"resultado": "dentro", **sem_conta,
                    "texto": "coberta na data do evento (trabalhadora rural com documento)"}
        if documento == "nao":
            return {"resultado": "fora", **sem_conta,
                    "texto": "não comprovada: trabalhadora rural sem nenhum documento, próprio ou de parente"}
        return {"resultado": "depende", **sem_conta,
                "texto": "depende de ter algum documento do trabalho rural, próprio ou de parente (falta saber)"}
    evento, ultima = _mes_indice(fatos.get("evento_mes_ano")), _mes_indice(fatos.get("ultima_contribuicao_mes_ano"))
    if evento is None or ultima is None:
        return None
    meses = evento - ultima
    if meses < 0:
        return {"resultado": "confirmar", "meses": meses, "prazo": None,
                "texto": ("a última contribuição informada é DEPOIS do evento: confirme se ela contribuía na época do "
                          "evento; se tinha parado antes, pergunte quando parou (mês e ano)")}
    valores = {chave: str(fatos.get(chave) or "").strip().lower() for chave, _ in _EXTENSOES}
    prazo = min(GRACA_MAXIMO, GRACA_BASE + GRACA_EXTENSAO * sum(v == "sim" for v in valores.values()))
    if meses <= prazo:
        return {"resultado": "dentro", "meses": meses, "prazo": prazo,
                "texto": "coberta na data do evento (dentro do período de graça)"}
    faltam = [rotulo for chave, rotulo in _EXTENSOES if valores[chave] not in ("sim", "nao")]
    if meses <= min(GRACA_MAXIMO, prazo + GRACA_EXTENSAO * len(faltam)):
        basta_uma = meses <= prazo + GRACA_EXTENSAO
        return {"resultado": "depende", "meses": meses, "prazo": prazo,
                "texto": "depende de " + (" ou " if basta_uma else " e ").join(faltam) + " (falta saber)"}
    return {"resultado": "fora", "meses": meses, "prazo": prazo,
            "texto": "não coberta pelas datas (fora do período de graça)"}


def prazo_de_5_anos(fatos: dict[str, Any], agora: datetime | None = None) -> dict[str, Any] | None:
    """Prazo de 5 anos desde o evento até hoje (só mês e ano). None = sem a data do evento, ou gestante.

    {"resultado": dentro | fora | confirmar, "texto": linha do sistema, "meses": meses desde o evento}. No mês em que
    fecham os 5 anos o dia não se sabe: ainda vale (faltando qualquer coisa = dentro)."""
    evento = _mes_indice(fatos.get("evento_mes_ano"))
    if evento is None or _gestante(fatos):
        return None
    hoje = agora_em_brasilia(agora)
    desde = hoje.year * 12 + hoje.month - evento
    if desde < 0:
        return {"resultado": "confirmar", "meses": desde,
                "texto": "a data do evento informada é no futuro: confirme o mês e o ano"}
    if desde < PRAZO_DO_PEDIDO_MESES:
        return {"resultado": "dentro", "meses": desde, "texto": "dentro do prazo de 5 anos"}
    if desde == PRAZO_DO_PEDIDO_MESES:
        return {"resultado": "dentro", "meses": desde,
                "texto": "dentro do prazo de 5 anos, mas é o último mês (dar entrada logo)"}
    return {"resultado": "fora", "meses": desde, "texto": "passou de 5 anos do evento (fora do prazo)"}


def fatos_da_calculadora_maternidade(fatos: dict[str, Any], agora: datetime | None = None) -> dict[str, str]:
    """Linhas "(sistema)" do Salário-Maternidade para os papéis com a calculadora (SDR e Período de Graça). Só aparecem
    com dados; tudo sai como FATO, nunca como ordem."""
    saida: dict[str, str] = {}
    if cobertura := periodo_de_graca_maternidade(fatos):
        saida[CHAVE_COBERTURA_EVENTO] = cobertura["texto"]
    if prazo := prazo_de_5_anos(fatos, agora):
        saida[CHAVE_PRAZO_5_ANOS] = prazo["texto"]
    return saida
