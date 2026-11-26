"""Interface comum de produto: o que o motor precisa saber de qualquer agente.

Um produto diz quais campos a IA extrai, quais etapas existem, como perguntar cada
campo e como decidir a etapa a partir dos fatos. Há dois tipos:

  * pronto  (AuxilioAcidente): regras em código, validadas pela LawChat;
  * próprio (ProdutoLivre):    regras montadas pelo cliente no painel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.cerebro import auxilio_acidente as aa

INTENCOES_BASE = ("pediu_humano", "pediu_para_parar", "engano")

DESCRICAO_INTENCOES_BASE = {
    "pediu_humano": "pede para falar com uma pessoa, atendente ou advogado",
    "pediu_para_parar": "pede para não receber mais mensagens",
    "engano": "diz que foi engano ou que não procurou o escritório",
}


@dataclass(frozen=True)
class EtapaDoProduto:
    codigo: str
    nome: str
    tipo: str = "conversa"                    # conversa | terminal
    instrucao_padrao: str = ""


class Produto(Protocol):
    codigo: str
    nome: str
    contexto: str                             # quem é o lead, em uma frase (para o extrator)
    etapas: list[EtapaDoProduto]
    sinais: tuple[str, ...]
    intencoes: tuple[str, ...]
    termos_proibidos: tuple[str, ...]
    etapas_com_valores: tuple[str, ...]          # onde a IA pode citar valores (honorários)
    etapas_com_dados_pessoais: tuple[str, ...]   # onde a IA pode pedir CPF, RG, endereço
    objetivo: str
    nunca: tuple[str, ...]                       # expressões proibidas definidas pelo cliente

    def esquema_extrator(self) -> dict[str, Any]: ...
    def guia_do_extrator(self) -> str: ...
    def validar_valor(self, chave: str, valor: Any) -> Any | None: ...
    def o_que_perguntar(self, chave: str) -> str: ...
    def decidir_etapa(self, etapa: str, fatos: dict[str, Any], intencoes: dict[str, bool]) -> aa.Passo: ...
    def motivo_simples(self, motivo: str) -> str: ...
    def etapa_inicial(self) -> str: ...


def esquema_extrator(chaves: list[str], sinais: tuple[str, ...], intencoes: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "fatos": {"type": "array", "items": {
                "type": "object",
                "properties": {"chave": {"type": "string", "enum": chaves},
                               "valor": {"type": "string"}, "trecho": {"type": "string"}},
                "required": ["chave", "valor", "trecho"], "additionalProperties": False}},
            "sinais": {"type": "array", "items": {"type": "string", "enum": list(sinais) or ["nenhum"]}},
            "intencoes": {"type": "object",
                          "properties": {n: {"type": "boolean"} for n in intencoes},
                          "required": list(intencoes), "additionalProperties": False},
        },
        "required": ["fatos", "sinais", "intencoes"],
        "additionalProperties": False,
    }


# ============================================================================ agente pronto
@dataclass
class AuxilioAcidente:
    regras: aa.Regras = field(default_factory=aa.Regras)
    codigo: str = "auxilio_acidente"
    nome: str = "Auxílio-Acidente"
    contexto: str = "uma pessoa que sofreu um acidente e procura o escritório de advocacia previdenciária"
    sinais: tuple[str, ...] = aa.SINAIS
    intencoes: tuple[str, ...] = aa.INTENCOES
    termos_proibidos: tuple[str, ...] = ("qualidade de segurado", "periodo de graca", "12 meses", "24 meses", "36 meses")
    etapas_com_valores: tuple[str, ...] = ("closer",)
    etapas_com_dados_pessoais: tuple[str, ...] = ("coleta_dados", "assinatura")
    objetivo: str = ""
    nunca: tuple[str, ...] = ()
    contrato: bool = False                        # função "Gerar contrato na ZapSign" ligada no agente
    # Campos obrigatórios do modelo ZapSign do agente (vazio = padrão do contrato). Sem eles, um modelo que exige e-mail
    # (ou RG, estado civil) dava "dados_confirmados" sem o campo e o pipeline não gerava nada: laço mudo.
    obrigatorios_contrato: tuple[str, ...] | None = None

    @property
    def etapas(self) -> list[EtapaDoProduto]:
        from app.cerebro.agente import INSTRUCOES
        nomes = {"sdr": "Primeiro atendimento", "periodo_graca": "Período de graça", "closer": "Proposta e honorários",
                 "coleta_dados": "Dados do contrato", "analise_manual": "Análise da equipe", "desqualificado": "Encerramento",
                 "assinatura": "Assinatura do contrato", "contrato_assinado": "Contrato assinado"}
        codigos = aa.ETAPAS + (aa.ETAPAS_CONTRATO if self.contrato else ())
        terminais = aa.ETAPAS_TERMINAIS + ("contrato_assinado",)
        instrucao = lambda c: INSTRUCOES.get("coleta_dados_contrato" if (c == "coleta_dados" and self.contrato) else c, "")  # noqa: E731
        return [EtapaDoProduto(c, nomes[c], "terminal" if c in terminais else "conversa", instrucao(c)) for c in codigos]

    def etapa_inicial(self) -> str:
        return "sdr"

    def esquema_extrator(self) -> dict[str, Any]:
        return esquema_extrator(list(aa.FATOS), self.sinais, self.intencoes)

    def guia_do_extrator(self) -> str:
        from app.cerebro.extrator import GUIA_AUXILIO_ACIDENTE
        return GUIA_AUXILIO_ACIDENTE

    def validar_valor(self, chave: str, valor: Any) -> Any | None:
        return aa.validar_valor(chave, valor)

    def o_que_perguntar(self, chave: str) -> str:
        return aa.O_QUE_PERGUNTAR.get(chave, chave)

    def decidir_etapa(self, etapa: str, fatos: dict[str, Any], intencoes: dict[str, bool]) -> aa.Passo:
        if self.contrato and etapa == "coleta_dados":
            return self._coleta_do_contrato(fatos, intencoes)
        if self.contrato and etapa == "assinatura":
            if intencoes.get("diz_que_assinou"):
                return aa.Passo("assinatura", "diz_que_assinou", ())
            if intencoes.get("confirmou_dados"):
                # Corrigiu um dado e confirmou: o pipeline pede versão nova (mesmos dados = mesmo link).
                passo = self._coleta_do_contrato(fatos, intencoes)
                if passo.motivo == "dados_confirmados":
                    return aa.Passo("assinatura", "dados_confirmados", ())
            return aa.Passo("assinatura", "aguardando_assinatura", ())
        return aa.decidir_etapa(etapa, fatos, intencoes, self.regras)

    def _coleta_do_contrato(self, fatos: dict[str, Any], intencoes: dict[str, bool]) -> aa.Passo:
        """Pede o que falta na ordem; completo, pede confirmação; confirmado, o pipeline gera o contrato."""
        from app.contrato import dados as cdados

        _, erros = cdados.validar_dados(cdados.dados_dos_fatos(fatos), None,
                                        self.obrigatorios_contrato or cdados.OBRIGATORIOS_PADRAO)
        # O telefone vem da conversa (o pipeline e a ação gerar_contrato completam com o número do WhatsApp).
        invalidos = [cdados.CAMPOS.get(e.campo, e.campo) for e in erros if e.campo != "telefone"]
        # Os do padrão na ordem de sempre; os extras do modelo (e-mail, RG, estado civil...) depois, na ordem do modelo.
        faltam = tuple(f for f in aa.ORDEM_PEDIDO_CONTRATO if f in invalidos) + tuple(
            f for f in invalidos if f not in aa.ORDEM_PEDIDO_CONTRATO)
        if faltam:
            return aa.Passo("coleta_dados", "faltam_dados_contrato", (), faltam)
        if intencoes.get("confirmou_dados"):
            return aa.Passo("coleta_dados", "dados_confirmados", ())
        return aa.Passo("coleta_dados", "confirmar_dados", ())

    def motivo_simples(self, motivo: str) -> str:
        from app.cerebro.agente import MOTIVOS_SIMPLES
        return MOTIVOS_SIMPLES.get(motivo, "o caso não se encaixa na atuação do escritório")


# ============================================================================ escolher
def carregar(codigo: str | None, config: dict[str, Any] | None) -> Produto:
    """Produto do agente a partir do que está salvo nele."""
    config = config or {}
    if codigo == "catalogo":
        from app.cerebro import catalogo
        return catalogo.carregar(config)
    if codigo == "proprio":
        from app.cerebro.produto_livre import ProdutoLivre
        return ProdutoLivre.da_definicao(config.get("definicao") or {})
    return AuxilioAcidente(aa.Regras(**(config.get("regras") or {})),
                           contrato=bool((config.get("funcoes") or {}).get("contrato_zapsign")))
