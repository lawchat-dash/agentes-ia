"""Produto Auxílio-Acidente: fatos, regras de qualificação e período de graça.

Tudo aqui é função pura: mesma entrada, mesma saída, sem IA e sem banco.
É o código, e não o modelo, que decide se o lead qualifica e para qual etapa vai.

ATENÇÃO: as regras vieram dos fluxos e prompts atuais e precisam da validação do
advogado responsável antes de irem para produção.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PRODUTO = "auxilio_acidente"

SIM_NAO = ("sim", "nao")

# Fatos que o extrator pode devolver e os valores aceitos em cada um.
# None = texto livre; "int:a-b" = número inteiro no intervalo.
FATOS: dict[str, tuple[str, ...] | str | None] = {
    "nome": None,
    "acidente_descricao": None,
    "acidente_mes": "int:1-12",
    "acidente_ano": "int:1950-2100",
    "sequela": ("sim", "nao", "nao_sabe"),
    "sequela_descricao": None,
    "auxilio_doenca": SIM_NAO,
    "vinculo_na_data": (
        "clt", "desempregado", "mei_autonomo_ci", "rural",
        "servidor_estatutario", "nunca_trabalhou", "nao_sabe",
    ),
    "ja_foi_clt": SIM_NAO,
    "aposentado": SIM_NAO,
    "tem_advogado_no_caso": SIM_NAO,
    "demissao_mes": "int:1-12",
    "demissao_ano": "int:1950-2100",
    "demissao_meses_antes_do_acidente": "int:0-600",   # "uns 8 meses antes"
    "demissao_ha_muitos_anos": SIM_NAO,                # "faz anos", sem número
    "seguro_desemprego": SIM_NAO,
    "contribuiu_por_conta_propria": SIM_NAO,           # carnê, MEI, contribuinte individual
    "documentos_rurais": SIM_NAO,
    # Dados do contrato (só pedidos na etapa coleta_dados, com a função de contrato ligada).
    "nome_completo": None, "cpf": None, "rg": None, "estado_civil": None, "profissao": None,
    "cep": None, "endereco": None, "numero_casa": None, "complemento": None, "bairro": None,
    "cidade": None, "uf": None, "email": None, "telefone_contrato": None, "nome_menor": None, "cpf_menor": None,
}

SINAIS = ("nao_sabe_ler", "quer_audio", "quer_videochamada", "cliente_antigo", "outro_beneficio",
          "dificuldade_assinatura", "foto_contrato", "muitas_objecoes", "endereco_sem_falar", "contrato_manual")

INTENCOES = (
    "pediu_humano", "pediu_para_parar", "engano",
    "aceitou_honorarios", "recusou", "diz_que_assinou", "confirmou_dados", "pediu_link",
)

# Como perguntar cada fato que falta (orientação para o agente, não texto pronto).
O_QUE_PERGUNTAR: dict[str, str] = {
    "acidente_descricao": "como foi o acidente (o que aconteceu)",
    "acidente_ano": "quando foi o acidente (mês e ano, pode ser aproximado)",
    "acidente_mes": "em que mês foi o acidente, mais ou menos",
    "sequela": "se ficou com alguma sequela ou limitação depois do acidente",
    "vinculo_na_data": "como estava a situação de trabalho na época do acidente (carteira assinada, desempregado, por conta própria, roça...)",
    "aposentado": "se já é aposentado",
    "tem_advogado_no_caso": "se já tem advogado cuidando deste caso",
    "documentos_rurais": "se tem documentos do trabalho na roça (bloco de produtor, contrato, declaração do sindicato...)",
    "demissao_quando": "quando saiu do último emprego de carteira assinada (pode ser aproximado)",
    "demissao_mes": "em que mês saiu do último emprego, mais ou menos",
    "seguro_desemprego": "se recebeu seguro-desemprego quando saiu do emprego",
    "contribuiu_por_conta_propria": "se pagou INSS por conta própria depois de sair (carnê, MEI)",
    "nome_completo": "o nome completo, como está no documento",
    "cpf": "o CPF",
    "cep": "o CEP de onde mora",
    "endereco": "o nome da rua ou avenida onde mora",
    "numero_casa": "o número da casa (ou se é sem número)",
    "bairro": "o bairro",
    "cidade": "a cidade",
    "uf": "o estado (a sigla, como MG ou SP)",
    "email": "o e-mail (se tiver)",
    "estado_civil": "o estado civil",
    "profissao": "a profissão",
    "rg": "o RG",
    "telefone_contrato": "o telefone com DDD",
    "nome_menor": "o nome completo do(a) menor",
    "cpf_menor": "o CPF do(a) menor",
}


def validar_valor(chave: str, valor: Any) -> Any | None:
    """Devolve o valor normalizado, ou None se a chave ou o valor não forem aceitos."""
    if chave not in FATOS:
        return None
    regra = FATOS[chave]
    if chave == "uf":
        # Sigla, sempre: "Minas gerais" gravado em uf travava o contrato (cortava "MI") e o CEP não corrigia.
        from app.contrato.dados import normalizar_uf
        return normalizar_uf(valor)
    if regra is None:
        texto = str(valor).strip()
        return texto[:500] if texto else None
    if isinstance(regra, str) and regra.startswith("int:"):
        minimo, maximo = (int(x) for x in regra[4:].split("-"))
        try:
            numero = int(str(valor).strip())
        except ValueError:
            return None
        return numero if minimo <= numero <= maximo else None
    texto = str(valor).strip().lower()
    return texto if texto in regra else None


@dataclass(frozen=True)
class Regras:
    """Parâmetros que o escritório pode ajustar."""

    prazo_sem_seguro_meses: int = 12
    prazo_com_seguro_meses: int = 24
    rural_sem_documentos: str = "analise_manual"       # ou "periodo_graca"
    sequela_nao_sabe: str = "analise_manual"           # ou "qualificado"
    perguntar_advogado: bool = True
    perguntar_aposentado: bool = True


@dataclass(frozen=True)
class Decisao:
    """Resultado de uma função de decisão, gravado junto com o turno."""

    funcao: str
    resultado: str                 # faltam_dados, qualificado, precisa_periodo_graca,
                                   # desqualificado, analise_manual, dentro, fora
    motivo: str = ""
    faltam: tuple[str, ...] = ()
    conta: dict[str, Any] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return {
            "funcao": self.funcao, "resultado": self.resultado, "motivo": self.motivo,
            "faltam": list(self.faltam), "conta": self.conta,
        }


def decidir_qualificacao(fatos: dict[str, Any], regras: Regras = Regras()) -> Decisao:
    f = "decidir_qualificacao"

    # 1. O que desqualifica vale assim que aparece, mesmo com dados faltando.
    if fatos.get("aposentado") == "sim":
        return Decisao(f, "desqualificado", "aposentado")
    if fatos.get("vinculo_na_data") == "servidor_estatutario":
        return Decisao(f, "desqualificado", "servidor_estatutario")
    if fatos.get("tem_advogado_no_caso") == "sim":
        return Decisao(f, "desqualificado", "ja_tem_advogado")
    if fatos.get("sequela") == "nao":
        return Decisao(f, "desqualificado", "sem_sequela")
    if fatos.get("vinculo_na_data") == "nunca_trabalhou":
        return Decisao(f, "desqualificado", "nunca_trabalhou")

    # 2. O que falta perguntar, na ordem da conversa.
    ordem = ["acidente_descricao", "acidente_ano", "sequela", "vinculo_na_data"]
    if regras.perguntar_aposentado:
        ordem.append("aposentado")
    if regras.perguntar_advogado:
        ordem.append("tem_advogado_no_caso")
    faltam = [chave for chave in ordem if fatos.get(chave) in (None, "")]
    if fatos.get("vinculo_na_data") == "rural" and fatos.get("documentos_rurais") is None:
        faltam.append("documentos_rurais")
    if faltam:
        return Decisao(f, "faltam_dados", faltam=tuple(faltam))

    # 3. Com tudo respondido, decide.
    if fatos["sequela"] == "nao_sabe" and regras.sequela_nao_sabe != "qualificado":
        return Decisao(f, "analise_manual", "sequela_incerta")

    vinculo = fatos["vinculo_na_data"]
    if vinculo == "clt":
        return Decisao(f, "qualificado", "clt_na_data")
    if vinculo == "rural":
        if fatos["documentos_rurais"] == "sim":
            return Decisao(f, "qualificado", "rural_com_documentos")
        if regras.rural_sem_documentos == "periodo_graca":
            return Decisao(f, "precisa_periodo_graca", "rural_sem_documentos")
        return Decisao(f, "analise_manual", "rural_sem_documentos")
    if vinculo in ("desempregado", "mei_autonomo_ci"):
        return Decisao(f, "precisa_periodo_graca", vinculo)
    return Decisao(f, "analise_manual", "vinculo_incerto")


def _intervalo_meses_entre_demissao_e_acidente(fatos: dict[str, Any]) -> tuple[int, float] | None:
    """Menor e maior número de meses possíveis entre a demissão e o acidente."""
    if fatos.get("demissao_meses_antes_do_acidente") is not None:
        n = int(fatos["demissao_meses_antes_do_acidente"])
        margem = max(1, round(n * 0.15))               # "uns 8 meses" = de 7 a 9
        return max(0, n - margem), n + margem

    acidente_ano = fatos.get("acidente_ano")
    demissao_ano = fatos.get("demissao_ano")
    if acidente_ano is not None and demissao_ano is not None:
        acidente_mes = fatos.get("acidente_mes")
        demissao_mes = fatos.get("demissao_mes")
        acidente_min = int(acidente_ano) * 12 + (int(acidente_mes) if acidente_mes else 1)
        acidente_max = int(acidente_ano) * 12 + (int(acidente_mes) if acidente_mes else 12)
        demissao_min = int(demissao_ano) * 12 + (int(demissao_mes) if demissao_mes else 1)
        demissao_max = int(demissao_ano) * 12 + (int(demissao_mes) if demissao_mes else 12)
        return max(0, acidente_min - demissao_max), max(0, acidente_max - demissao_min)

    if fatos.get("demissao_ha_muitos_anos") == "sim":
        return 36, float("inf")
    return None


def calcular_periodo_graca(fatos: dict[str, Any], regras: Regras = Regras()) -> Decisao:
    """Diz se o acidente caiu dentro do período de graça depois da demissão.

    Aceita datas aproximadas: decide quando a margem permite e só pede o mês
    quando o caso fica perto do limite. A IA nunca cita esses prazos ao lead.
    """
    f = "calcular_periodo_graca"
    intervalo = _intervalo_meses_entre_demissao_e_acidente(fatos)
    if intervalo is None:
        return Decisao(f, "faltam_dados", faltam=("demissao_quando",))
    menor, maior = intervalo

    seguro = fatos.get("seguro_desemprego")
    prazo_menor = regras.prazo_com_seguro_meses if seguro == "sim" else regras.prazo_sem_seguro_meses
    prazo_maior = regras.prazo_sem_seguro_meses if seguro == "nao" else regras.prazo_com_seguro_meses
    conta = {
        "meses_minimo": menor,
        "meses_maximo": None if maior == float("inf") else maior,
        "seguro_desemprego": seguro,
        "prazo_aplicado": prazo_menor if seguro in SIM_NAO else None,
    }

    if maior <= prazo_menor:
        return Decisao(f, "dentro", "dentro_do_prazo", conta=conta)

    if menor > prazo_maior:
        # Fora do prazo. Antes de desqualificar, confere se contribuiu por conta própria.
        contribuiu = fatos.get("contribuiu_por_conta_propria")
        if contribuiu is None:
            return Decisao(f, "faltam_dados", faltam=("contribuiu_por_conta_propria",), conta=conta)
        if contribuiu == "sim":
            return Decisao(f, "analise_manual", "contribuiu_por_conta_propria", conta=conta)
        return Decisao(f, "fora", "qualidade_de_segurado", conta=conta)

    # Zona de dúvida: falta saber do seguro ou a data está imprecisa.
    if seguro not in SIM_NAO:
        return Decisao(f, "faltam_dados", faltam=("seguro_desemprego",), conta=conta)
    if fatos.get("demissao_mes") is None:
        return Decisao(f, "faltam_dados", faltam=("demissao_mes",), conta=conta)
    if fatos.get("acidente_mes") is None:
        return Decisao(f, "faltam_dados", faltam=("acidente_mes",), conta=conta)
    return Decisao(f, "analise_manual", "perto_do_limite", conta=conta)


# Etapas do funil. As terminais não têm conversa de IA depois da mensagem de passagem.
ETAPAS = ("sdr", "periodo_graca", "closer", "coleta_dados", "analise_manual", "desqualificado")
ETAPAS_TERMINAIS = ("analise_manual", "desqualificado")
# Com a função de contrato ligada: o lead assina pelo link e o contrato assinado encerra a conversa da IA.
ETAPAS_CONTRATO = ("assinatura", "contrato_assinado")
ORDEM_PEDIDO_CONTRATO = ("nome_completo", "cpf", "cep", "endereco", "numero_casa", "bairro", "cidade", "uf")


@dataclass(frozen=True)
class Passo:
    """Para onde o lead vai neste turno e por quê."""

    etapa: str
    motivo: str
    decisoes: tuple[Decisao, ...]
    faltam: tuple[str, ...] = ()


def decidir_etapa(
    etapa_atual: str,
    fatos: dict[str, Any],
    intencoes: dict[str, bool] | None = None,
    regras: Regras = Regras(),
) -> Passo:
    """Transição de etapa decidida só pelos fatos. Só anda para frente."""
    intencoes = intencoes or {}
    decisoes: list[Decisao] = []

    if etapa_atual in ("sdr", "periodo_graca"):
        qualificacao = decidir_qualificacao(fatos, regras)
        decisoes.append(qualificacao)
        if qualificacao.resultado == "desqualificado":
            return Passo("desqualificado", qualificacao.motivo, tuple(decisoes))
        if qualificacao.resultado == "analise_manual":
            return Passo("analise_manual", qualificacao.motivo, tuple(decisoes))
        if qualificacao.resultado == "faltam_dados":
            # Em período de graça, uma pergunta da qualificação ainda pode estar aberta.
            return Passo(etapa_atual, "faltam_dados", tuple(decisoes), qualificacao.faltam)
        if qualificacao.resultado == "qualificado":
            return Passo("closer", qualificacao.motivo, tuple(decisoes))

        # precisa_periodo_graca: já tenta resolver neste mesmo turno.
        periodo = calcular_periodo_graca(fatos, regras)
        decisoes.append(periodo)
        if periodo.resultado == "dentro":
            return Passo("closer", "periodo_de_graca_dentro", tuple(decisoes))
        if periodo.resultado == "fora":
            return Passo("desqualificado", periodo.motivo, tuple(decisoes))
        if periodo.resultado == "analise_manual":
            return Passo("analise_manual", periodo.motivo, tuple(decisoes))
        return Passo("periodo_graca", "faltam_dados", tuple(decisoes), periodo.faltam)

    if etapa_atual == "closer":
        if intencoes.get("aceitou_honorarios"):
            return Passo("coleta_dados", "aceitou_honorarios", ())
        return Passo("closer", "em_andamento", ())

    return Passo(etapa_atual, "sem_mudanca", ())
