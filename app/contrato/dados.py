"""Dados do contrato: validação, variáveis do modelo da ZapSign e textos. Tudo puro (sem banco, sem rede)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
       "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
# Nome do estado (minúsculo, sem acento) -> sigla. O lead escreve "Minas gerais": sem a tabela, o contrato cortava "MI",
# pedia o estado de novo e, com o mesmo valor repetido, a conversa ia para a equipe (contrato_correcao_repetida).
NOMES_UF = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso": "MT",
    "mato grosso do sul": "MS", "minas gerais": "MG", "minas": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
    "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}


def normalizar_uf(valor: Any) -> str | None:
    """Sigla do estado a partir do que o lead escreveu: "MG", "mg.", "Minas Gerais", "minas gerais/MG", "Estado de SP".
    None = não reconhecido (o contrato pede o estado de novo)."""
    import unicodedata

    texto = unicodedata.normalize("NFD", str(valor or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn").lower()
    texto = re.sub(r"[^a-z]+", " ", texto).strip()
    texto = re.sub(r"^(?:estado|est|uf)(?: d[eoa])? ", "", texto)
    if not texto:
        return None
    if texto.upper() in UFS:
        return texto.upper()
    # O nome mais longo que aparece inteiro ("mato grosso do sul" antes de "mato grosso").
    for nome in sorted(NOMES_UF, key=len, reverse=True):
        if re.search(rf"\b{nome}\b", texto):
            return NOMES_UF[nome]
    partes = texto.split()
    siglas = {p.upper() for p in partes if p.upper() in UFS}
    return siglas.pop() if len(siglas) == 1 and len(partes) <= 3 else None


def formatar_cpf(valor: Any) -> str | None:
    """CPF válido formatado (000.000.000-00), em qualquer formato de entrada. None = dígitos não conferem."""
    if not cpf_valido(valor):
        return None
    c = _digitos(valor)
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"

# Campo do contrato -> fato do lead que o preenche (o extrator usa as chaves da direita).
CAMPOS: dict[str, str] = {
    "nome": "nome_completo", "estado_civil": "estado_civil", "profissao": "profissao", "cpf": "cpf", "rg": "rg",
    "endereco": "endereco", "numero": "numero_casa", "complemento": "complemento", "bairro": "bairro",
    "cidade": "cidade", "estado": "uf", "cep": "cep", "telefone": "telefone_contrato", "email": "email",
    "nomecompletomenor": "nome_menor", "cpfdomenor": "cpf_menor",
}
OBRIGATORIOS_PADRAO = ("nome", "cpf", "endereco", "numero", "bairro", "cidade", "estado", "cep")

PEDIR = {
    "nome": "seu nome completo", "cpf": "o seu CPF", "endereco": "o nome da sua rua ou avenida",
    "numero": "o número da sua casa", "bairro": "o seu bairro", "cidade": "a sua cidade",
    "estado": "o seu estado (a sigla, como MG ou SP)", "cep": "o seu CEP", "email": "o seu e-mail",
    "cpfdomenor": "o CPF do(a) menor", "estado_civil": "o seu estado civil", "profissao": "a sua profissão",
    "rg": "o seu RG", "telefone": "o seu telefone com DDD",
}

# Mapeamento padrão: os 22 nomes do modelo usado pela LawChat (texto exato da variável na ZapSign).
MAPEAMENTO_PADRAO: list[dict[str, str]] = [
    {"variavel": "NOME", "campo": "nome"}, {"variavel": "Estado Civil", "campo": "estado_civil"},
    {"variavel": "Profissão", "campo": "profissao"}, {"variavel": "CPF", "campo": "cpf"},
    {"variavel": "RG", "campo": "rg"}, {"variavel": "Endereço", "campo": "endereco"},
    {"variavel": "Número", "campo": "numero"}, {"variavel": "Complemento", "campo": "complemento"},
    {"variavel": "Bairro", "campo": "bairro"}, {"variavel": "Cidade", "campo": "cidade"},
    {"variavel": "Estado", "campo": "estado"}, {"variavel": "CEP", "campo": "cep"},
    {"variavel": "Telefone", "campo": "telefone"}, {"variavel": "Email", "campo": "email"},
    {"variavel": "DATA", "campo": "@data_geracao"},
    {"variavel": "Qual o nome completo do(a) menor?", "campo": "nomecompletomenor"},
    {"variavel": "Qual o CPF do(a) menor?", "campo": "cpfdomenor"},
]

TEXTOS = {
    "link": "Segue o link de contrato:\n{link}",
    "nova_versao": "Contrato atualizado. Segue o novo link para assinatura:\n{link}",
    "mesmo_link": "Segue novamente o link do seu contrato:\n{link}",
    "imprevisto": "Tive um imprevisto para gerar seu contrato agora. Vou tentar novamente em instantes, tudo bem?",
    "equipe_envia": "Seu contrato será finalizado pela nossa equipe, que vai te enviar o link por aqui em breve.",
    "limite": "Seu contrato já foi atualizado algumas vezes. Para essa nova alteração, nossa equipe vai falar com você por aqui.",
    "ja_assinado": "Seu contrato já está assinado. Está tudo certo por aqui!",
    "pos_assinatura": ("✅ Assinatura confirmada!\n\nAcabamos de verificar e seu contrato foi assinado com sucesso. "
                       "Está tudo certo por aqui! 🎉\n\nA partir de agora, nossa equipe dá andamento ao seu caso e você "
                       "será informado(a) sobre cada nova etapa. Se surgir qualquer dúvida, é só nos chamar por aqui.\n\n"
                       "Obrigado pela confiança! 🤝"),
    "pendente": "Ainda não consta a sua assinatura por aqui. Segue o link novamente:\n{link}",
    "conferir": "Vou pedir para a nossa equipe conferir a sua assinatura e já te retorno.",
    "lembrete": "Oi! Passando para lembrar do seu contrato. É só tocar no link para assinar:\n{link}",
    # Lembrete para quem já abriu o link e não terminou (o lembrete contextual).
    "lembrete_abriu": ("Oi! Vi que você chegou a abrir o contrato, mas a assinatura ainda não foi concluída. Travou em "
                       "alguma etapa, como a selfie ou o código de confirmação? Me conta que eu te ajudo. O link é este:\n{link}"),
    # "Já assinei", mas abriu e não concluiu: pergunta onde travou.
    "travou": ("Conferi aqui e vi que você abriu o contrato, mas a assinatura ainda não foi concluída. Travou em alguma "
               "etapa, como a selfie, a foto do documento ou o código de confirmação? Me conta que eu te ajudo. "
               "Se precisar, o link é este:\n{link}"),
    # Documento cancelado, recusado, excluído ou vencido: nunca o link velho.
    "cancelado": ("Conferi aqui e esse contrato não está mais disponível para assinatura. Nossa equipe vai falar com "
                  "você por aqui para resolver, tudo bem?"),
    # Telefone ou e-mail do signatário trocado sem contrato novo.
    "contato_atualizado": "Pronto, atualizei o seu contato no contrato. O link para assinar continua o mesmo:\n{link}",
}

from app.contrato.resumo import PROMPT_PADRAO as PROMPT_RESUMO  # noqa: E402  (o prompt de fábrica mora em resumo.py)

NOTAS_CAUSA = {
    "sem_credito": "a conta da ZapSign está sem créditos (documentos) no plano. Compre créditos ou mude o plano da ZapSign para a IA voltar a gerar contratos.",
    "plano_pendente": "o plano da ZapSign está com pagamento pendente ou vencido. Regularize o plano para a IA voltar a gerar contratos.",
    "pagamento": "a ZapSign recusou o pedido por falta de pagamento ou de créditos na conta. Regularize a conta da ZapSign para a IA voltar a gerar contratos.",
    "limite": "a conta da ZapSign atingiu o limite de documentos. Aumente o limite ou o plano da ZapSign.",
    "chave": "a ZapSign recusou a chave de acesso cadastrada (inválida, vencida ou sem permissão). Confira a chave em Integrações.",
    "modelo": "a ZapSign não aceitou o pedido (modelo de contrato não encontrado ou alterado). Confira o modelo em Integrações.",
    "sem_integracao": "não há chave da ZapSign ou modelo de contrato cadastrado para este escritório.",
    "fora_do_ar": "a ZapSign não respondeu. O sistema vai tentar de novo sozinho.",
}


@dataclass(frozen=True)
class CampoInvalido:
    campo: str
    pedir: str


def _texto(valor: Any) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def _digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def cpf_valido(valor: Any) -> bool:
    cpf = _digitos(valor)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(cpf[tamanho]):
            return False
    return True


def dados_dos_fatos(fatos: dict[str, Any]) -> dict[str, str]:
    """Campos do contrato a partir dos fatos vigentes do lead."""
    dados = {campo: _texto(fatos.get(fato)) for campo, fato in CAMPOS.items() if _texto(fatos.get(fato))}
    if "nome" not in dados and _texto(fatos.get("nome")) and len(_texto(fatos.get("nome")).split()) >= 2:
        dados["nome"] = _texto(fatos.get("nome"))
    # "sem complemento" é a resposta do lead (para a IA não perguntar de novo), não vai escrito no contrato.
    if re.fullmatch(r"(?i)\s*(sem complemento|n[aã]o tem|nenhum|-)\s*", dados.get("complemento", "")):
        dados.pop("complemento")
    return dados


def validar_dados(brutos: dict[str, Any], telefone_da_conversa: str | None = None,
                  obrigatorios: tuple[str, ...] | list[str] = OBRIGATORIOS_PADRAO) -> tuple[dict[str, str], list[CampoInvalido]]:
    """Normaliza e confere. Devolve (dados prontos para o contrato, o que pedir de novo ao lead)."""
    d = {k: _texto(v) for k, v in (brutos or {}).items()}
    erros: list[CampoInvalido] = []

    def erro(campo: str) -> None:
        if campo in obrigatorios or d.get(campo):
            erros.append(CampoInvalido(campo, PEDIR.get(campo, campo)))

    if not d.get("nome") or len(d["nome"].split()) < 2 or re.search(r"\d", d["nome"]):
        erro("nome")
    if cpf_valido(d.get("cpf")):
        c = _digitos(d["cpf"])
        d["cpf"] = f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
    else:
        erro("cpf")
    if not d.get("endereco") or d["endereco"].replace(" ", "").isdigit():
        erro("endereco")
    if not d.get("numero"):
        erro("numero")
    if not d.get("bairro"):
        erro("bairro")
    if not d.get("cidade") or re.search(r"\d", d["cidade"]):
        erro("cidade")
    bruto = d.get("estado", "").upper()
    d["estado"] = normalizar_uf(d.get("estado")) or (bruto[:2] if bruto[:2] in UFS else bruto)
    if d["estado"] not in UFS:
        erro("estado")
    cep = _digitos(d.get("cep"))
    if len(cep) == 8:
        d["cep"] = f"{cep[:5]}-{cep[5:]}"
    else:
        erro("cep")
    telefone = _digitos(d.get("telefone"))
    if telefone.startswith("55") and len(telefone) in (12, 13):
        telefone = telefone[2:]
    if len(telefone) not in (10, 11):
        telefone = _digitos(telefone_da_conversa)
        if telefone.startswith("55") and len(telefone) in (12, 13):
            telefone = telefone[2:]
    d["telefone"] = telefone if len(telefone) in (10, 11) else ""
    if d.get("email"):
        d["email"] = d["email"].lower().replace(" ", "")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", d["email"]):
            if "email" in obrigatorios:
                erro("email")
            else:
                # Não obrigatório: um "não tenho" (ou texto solto) gravado no campo vira vazio. Pedir a correção
                # travava o lead sem e-mail num laço: o zapsign era chamado de novo e o sistema pedia o e-mail de novo.
                d.pop("email")
    if d.get("cpfdomenor") and (not cpf_valido(d["cpfdomenor"]) or _digitos(d["cpfdomenor"]) == _digitos(d.get("cpf"))):
        # O CPF do(a) menor igual ao do titular (a mãe mandou o próprio CPF de novo) não vai para o contrato.
        erro("cpfdomenor")
    if d.get("estado_civil"):
        d["estado_civil"] = normalizar_estado_civil(d["estado_civil"])
    if d.get("rg"):
        rg = normalizar_rg(d["rg"])
        if rg is None:                       # sem número nenhum ("não tenho", "depois mando")
            d.pop("rg")
            if "rg" in obrigatorios:
                erros.append(CampoInvalido("rg", PEDIR["rg"]))
        else:
            d["rg"] = rg
    d["profissao"] = normalizar_profissao(d.get("profissao")) or "Não informado"
    for campo in obrigatorios:
        if campo not in ("nome", "cpf", "endereco", "numero", "bairro", "cidade", "estado", "cep") and not d.get(campo):
            erro(campo)
    vistos: set[str] = set()
    unicos = [e for e in erros if not (e.campo in vistos or vistos.add(e.campo))]  # type: ignore[func-returns-value]
    return {k: v for k, v in d.items() if v}, unicos


def _sem_acento(valor: Any) -> str:
    import unicodedata

    texto = unicodedata.normalize("NFD", str(valor or ""))
    return re.sub(r"\s+", " ", "".join(c for c in texto if unicodedata.category(c) != "Mn").lower()).strip()


# Estado civil: lista fechada. O gênero sai do que o lead escreveu ("casada" -> "Casada"); sem gênero, "(a)".
_ESTADOS_CIVIS = (
    (r"uniao estavel|amasiad|juntad|moro junto|vivo junto|companheir|convivente", "União estável", "União estável", "União estável"),
    (r"divorciad|divorcio", "Divorciado", "Divorciada", "Divorciado(a)"),
    (r"separad|desquitad", "Separado", "Separada", "Separado(a)"),
    (r"viuv", "Viúvo", "Viúva", "Viúvo(a)"),
    (r"casad", "Casado", "Casada", "Casado(a)"),
    (r"solteir", "Solteiro", "Solteira", "Solteiro(a)"),
)


def normalizar_estado_civil(valor: Any) -> str:
    """Um dos seis da lista; o que não for reconhecido fica como o lead escreveu (não trava o contrato)."""
    texto = _sem_acento(valor)
    for padrao, masculino, feminino, neutro in _ESTADOS_CIVIS:
        achado = re.search(rf"\b(?:{padrao})(\w*)", texto)
        if achado:
            if masculino == feminino:
                return masculino
            palavra = achado.group(0)
            if re.search(r"\(a\)|o\(a\)|/a\b", texto):
                return neutro
            return feminino if palavra.endswith("a") else masculino if palavra.endswith("o") else neutro
    return _texto(valor)


def normalizar_rg(valor: Any) -> str | None:
    """RG sem espaços sobrando e em maiúsculas (o formato muda de estado para estado: pontos, hífen, X e o órgão
    emissor ficam). None = não tem número nenhum."""
    texto = re.sub(r"\s+", " ", str(valor or "")).strip().upper()
    texto = re.sub(r"^(?:RG|R\.G\.?|IDENTIDADE)\s*[:Nº°.]*\s*", "", texto)
    if not re.search(r"\d", texto):
        return None
    return re.sub(r"\s*([.\-/])\s*", r"\1", texto)


# Regra do roteiro (antes só no prompt): "do lar" e quem faz bico contam como desempregado no contrato.
_DESEMPREGADO = re.compile(
    r"^(?:sou |estou |to |tou |atualmente )?(?:do lar|dona de casa|dono de casa|desempregad[oa]s?|sem (?:emprego|trabalho|profissao)"
    r"|nenhuma|nao trabalho|nao tenho (?:emprego|trabalho|profissao)|(?:faco |fazendo |vivo de |so )?bicos?"
    r"|(?:trabalho (?:de|com|fazendo) )?bicos?(?: .*)?)$")


def normalizar_profissao(valor: Any) -> str:
    texto = _texto(valor)
    if not texto:
        return ""
    return "Desempregado" if _DESEMPREGADO.match(_sem_acento(texto)) else texto


def nota_dos_dados(dados: dict[str, str]) -> str:
    """Nota interna organizada com os dados do contrato que o lead terminou de mandar (para a equipe conferir antes ou
    depois da ZapSign). Só os campos preenchidos."""
    def linha(rotulo: str, *campos: str, sep: str = ", ") -> str | None:
        valor = sep.join(dados[c] for c in campos if dados.get(c))
        return f"{rotulo}: {valor}" if valor else None

    rua = ", ".join(x for x in (dados.get("endereco"), dados.get("numero")) if x)
    if dados.get("complemento"):
        rua = f"{rua} ({dados['complemento']})" if rua else dados["complemento"]
    cidade = "/".join(x for x in (dados.get("cidade"), dados.get("estado")) if x)
    blocos = [
        ["📝 Dados do contrato preenchidos pelo lead"],
        [x for x in (linha("👤 Nome", "nome"), linha("🪪 CPF", "cpf"), linha("RG", "rg"),
                     linha("Estado civil", "estado_civil"), linha("Profissão", "profissao")) if x],
        [x for x in (f"🏠 Endereço: {rua}" if rua else None, linha("Bairro", "bairro"),
                     f"Cidade: {cidade}" if cidade else None, linha("CEP", "cep")) if x],
        [x for x in (linha("📞 Telefone", "telefone"), linha("✉️ E-mail", "email")) if x],
        [x for x in (linha("👶 Menor", "nomecompletomenor"), linha("CPF do menor", "cpfdomenor")) if x],
    ]
    return "\n\n".join("\n".join(b) for b in blocos if b)


def hash_dados(dados: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def montar_variaveis(dados: dict[str, str], mapeamento: list[dict[str, str]], agora: datetime) -> list[tuple[str, str]]:
    """Variáveis do modelo: campo do lead, data da geração (@data_geracao) ou texto fixo (@fixo)."""
    saida = []
    for item in mapeamento or MAPEAMENTO_PADRAO:
        variavel = str(item.get("variavel") or "").strip()
        if not variavel:
            continue
        campo = item.get("campo") or ""
        if campo == "@data_geracao":
            valor = agora.strftime("%d-%m-%Y %H:%M")
        elif campo == "@fixo":
            valor = str(item.get("valor") or "")
        else:
            valor = dados.get(campo, "")
        saida.append((variavel, valor))
    return saida


def pedir_correcao(erros: list[CampoInvalido]) -> str:
    pedidos = [e.pedir for e in erros]
    if len(pedidos) == 1:
        return f"Para finalizar seu contrato, preciso confirmar uma informação: {pedidos[0]}. Pode me enviar novamente, por favor?"
    lista = ", ".join(pedidos[:-1]) + " e " + pedidos[-1]
    return f"Para finalizar seu contrato, preciso confirmar algumas informações: {lista}. Pode me enviar novamente, por favor?"


def texto(config: dict[str, Any], chave: str, **valores: Any) -> str:
    """Texto ao lead: o do escritório (config.mensagens) ou o padrão."""
    modelo = ((config or {}).get("mensagens") or {}).get(chave) or TEXTOS[chave]
    try:
        return modelo.format(**valores)
    except (KeyError, IndexError):
        return TEXTOS[chave].format(**valores)
