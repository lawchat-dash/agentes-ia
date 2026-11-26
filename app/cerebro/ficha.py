"""Ficha do caso para a passagem para humano (leva 1, item B2).

Montada em código, sem chamar a IA: quem abre a conversa na Helena sabe, sem ler tudo, quem é o lead, em que etapa
está, o que ele já respondeu, por que a IA saiu e o que ainda falta descobrir. Vai na nota da Helena e no detalhe do
evento da passagem (campo "ficha"), para os avisos à equipe poderem usar.

Privacidade: CPF só mascarado ("***.***.***-12"); RG, endereço, e-mail, telefone e dados do menor nunca entram;
dado de saúde só como resposta curta (sequela: sim/não), nunca o texto livre (descrição do acidente, laudo, CID).
"""

from __future__ import annotations

import re
from typing import Any

LIMITE = 1500

ROTULOS_MOTIVO = {
    "pediu_humano": "o lead pediu para falar com uma pessoa",
    "trava_persistente": "a IA foi barrada duas vezes pelas travas de segurança",
    "pedido_repetido": "a IA ia repetir um pedido que o lead já respondeu",
    "analise_manual": "caso para a equipe avaliar",
    "sinal": "o lead precisa de atenção da equipe",
    "formato_invalido": "a IA respondeu fora do formato",
    "trocas_demais": "a IA trocou de etapa vezes demais em 24 h",
    "fora_do_tema_repetido": "o lead insistiu em assunto fora do tema",
    "contrato_correcao_repetida": "o contrato pediria a mesma correção de novo",
    "faltam_fatos": "a IA não conseguiu confirmar o que falta para passar o lead",
}

ROTULOS_FATO = {
    "nome": "Nome", "nome_completo": "Nome completo", "aposentado": "Aposentado", "tem_advogado_no_caso": "Advogado no caso",
    "sequela": "Sequela ou limitação", "acidente_ano": "Ano do acidente", "acidente_mes": "Mês do acidente",
    "acidente_quando_incerto": "Não lembra quando foi o acidente", "auxilio_doenca": "Recebeu auxílio-doença",
    "vinculo_na_data": "Trabalho na data do acidente", "ja_foi_clt": "Já trabalhou de carteira",
    "documentos_rurais": "Documentos rurais", "aceite_honorarios": "Aceitou os honorários",
    "demissao_ano": "Ano em que saiu do emprego", "demissao_mes": "Mês em que saiu do emprego",
    "demissao_meses_antes_do_acidente": "Meses entre a saída e o acidente", "demissao_ha_muitos_anos": "Saiu faz anos",
    "seguro_desemprego": "Recebeu seguro-desemprego", "contribuiu_por_conta_propria": "Pagou INSS por conta própria",
    "cidade": "Cidade", "uf": "Estado", "estado_civil": "Estado civil", "profissao": "Profissão", "cpf": "CPF",
}
ROTULOS_VALOR = {"sim": "sim", "nao": "não", "nao_sabe": "não sabe", "clt": "carteira assinada", "desempregado": "desempregado",
                 "mei_autonomo_ci": "MEI / autônomo", "rural": "trabalho rural", "servidor_estatutario": "servidor público",
                 "nunca_trabalhou": "nunca trabalhou"}
# Nunca na ficha: documento, contato, endereço e texto livre de saúde.
FORA_DA_FICHA = {"rg", "endereco", "numero_casa", "complemento", "bairro", "cep", "email", "telefone_contrato", "telefone",
                 "nome_menor", "cpf_menor", "cpfdomenor", "nomecompletomenor", "acidente_descricao", "sequela_descricao",
                 "laudo", "cid", "doenca", "diagnostico", "condicao_saude", "descricao_sequela"}


def mascarar_cpf(valor: Any) -> str:
    digitos = re.sub(r"\D", "", str(valor or ""))
    return f"***.***.***-{digitos[-2:]}" if len(digitos) >= 2 else "***"


def _campo(lead: Any, *nomes: str) -> Any:
    for nome in nomes:
        valor = lead.get(nome) if isinstance(lead, dict) else getattr(lead, nome, None)
        if valor not in (None, ""):
            return valor
    return None


def _rotulo_motivo(motivo: str | None) -> str:
    bruto = str(motivo or "").strip()
    base, _, resto = bruto.partition(":")
    if base == "analise_manual" and resto in ROTULOS_MOTIVO:
        return ROTULOS_MOTIVO[resto]
    if base == "sinal" and resto:
        return f"{ROTULOS_MOTIVO['sinal']} ({resto.replace('_', ' ').replace(',', ', ')})"
    return ROTULOS_MOTIVO.get(base) or bruto.replace("_", " ") or "passagem para a equipe"


def _rotulo_fato(chave: str) -> str:
    return ROTULOS_FATO.get(chave) or chave.replace("_", " ").capitalize()


def _valor(chave: str, valor: Any) -> str:
    if chave == "cpf":
        return mascarar_cpf(valor)
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return ROTULOS_VALOR.get(texto.lower(), texto)[:80]


def montar_ficha(lead: Any, fatos: dict[str, Any] | None, etapa: str | None, motivo: str | None,
                 ultima_pergunta_ia: str | None, faltando: list[str] | tuple[str, ...] | None) -> str:
    """Texto curto da ficha. `lead`: dict ou objeto com nome e benefício/produto (nome, beneficio ou produto);
    `fatos`: fatos vigentes (as marcas do motor, que começam com "_", ficam fora); `faltando`: chaves de fatos (ou
    rótulos prontos) que a IA ainda precisava descobrir."""
    fatos = {k: v for k, v in (fatos or {}).items() if not str(k).startswith("_") and v not in (None, "", [], {})}
    nome = _campo(lead, "nome", "nome_contato") or fatos.get("nome") or fatos.get("nome_completo") or "sem nome"
    beneficio = _campo(lead, "beneficio", "produto")
    # Em blocos separados por linha em branco e um fato por linha: na nota da LawChat fica fácil de ler.
    linhas = [f"📋 Ficha do caso: {_rotulo_motivo(motivo)}", "",
              f"👤 Lead: {str(nome)[:80]}" + (f" | Benefício: {str(beneficio)[:60]}" if beneficio else "")
              + f" | Etapa: {etapa or '-'}"]
    confirmados = [f"{_rotulo_fato(k)}: {_valor(k, v)}" for k, v in fatos.items()
                   if k not in FORA_DA_FICHA and k not in ("nome",) and not isinstance(v, (dict, list))]
    if confirmados:
        linhas += ["", "✅ Já respondeu:"] + [f"• {c}" for c in confirmados]
    if faltando:
        linhas += ["", "❓ Falta descobrir: " + ", ".join(dict.fromkeys(_rotulo_fato(str(f)) if str(f) in ROTULOS_FATO
                                                                      else str(f) for f in faltando))]
    if ultima_pergunta_ia:
        linhas += ["", "💬 Última pergunta da IA: " + re.sub(r"\s+", " ", str(ultima_pergunta_ia)).strip()[:200]]
    texto = "\n".join(linhas)
    return texto if len(texto) <= LIMITE else texto[:LIMITE - 1].rstrip() + "…"
