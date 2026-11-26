"""Busca de endereço pelo CEP (antigo fluxo n8n "BUSCAR CEP FINAL").

Tenta ViaCEP, depois OpenCEP, depois BrasilAPI. CEP "geral" de cidade (sem logradouro) volta como
inválido, porque o contrato precisa de rua. Nunca levanta exceção: quem chama lê `valido`.
Nenhuma fonte respondeu (rede fora, timeout, erro 5xx): `falhou` = True, que não é "CEP não encontrado".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import httpx

FONTES: tuple[tuple[str, str, str], ...] = (
    # (origem, url, campo que prova que achou)
    ("viacep", "https://viacep.com.br/ws/{cep}/json", "localidade"),
    ("opencep", "https://opencep.com/v1/{cep}", "localidade"),
    ("brasilapi", "https://brasilapi.com.br/api/cep/v1/{cep}", "city"),
)


@dataclass(frozen=True)
class Endereco:
    cep: str
    valido: bool
    mensagem: str
    tipo: str = ""            # "rua" ou "geral"
    logradouro: str = ""
    bairro: str = ""
    cidade: str = ""
    uf: str = ""
    origem: str = ""
    falhou: bool = False      # nenhuma fonte respondeu: a busca pode ser refeita depois

    def como_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def limpar_cep(valor: object) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def achar_cep(texto: str) -> str | None:
    """Acha um CEP escrito pelo lead ("12345-678", "12.345-678", "12345678")."""
    m = re.search(r"(?<!\d)(\d{2})\.?(\d{3})-?(\d{3})(?!\d)", texto or "")
    return "".join(m.groups()) if m else None


async def _buscar(cliente: httpx.AsyncClient, url: str) -> tuple[dict | None, bool]:
    """(dados, respondeu). Respondeu = a fonte deu uma resposta de verdade (200, ou 4xx de "não achei"); rede fora,
    timeout, 429/5xx ou corpo que não é JSON não contam: sem nenhuma resposta, o CEP não pode ser dado como inexistente."""
    try:
        resposta = await cliente.get(url)
        if resposta.status_code == 429 or resposta.status_code >= 500:
            return None, False
        if resposta.status_code != 200:
            return None, True
        dados = resposta.json()
        return (dados if isinstance(dados, dict) else None), True
    except (httpx.HTTPError, ValueError):
        return None, False


async def _pegar(cliente: httpx.AsyncClient, url: str) -> dict | None:
    return (await _buscar(cliente, url))[0]


def _texto(dados: dict, *chaves: str) -> str:
    for chave in chaves:
        valor = dados.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


async def consultar(cep_bruto: object, *, cliente: httpx.AsyncClient | None = None, timeout: float = 6.0) -> Endereco:
    cep = limpar_cep(cep_bruto)
    if len(cep) != 8:
        return Endereco(cep=str(cep_bruto or ""), valido=False, mensagem="CEP inválido: precisa ter 8 dígitos.")

    proprio = cliente is None
    cliente = cliente or httpx.AsyncClient(timeout=timeout, headers={"Accept": "application/json"})
    try:
        responderam = 0
        for origem, modelo, prova in FONTES:
            dados, respondeu = await _buscar(cliente, modelo.format(cep=cep))
            responderam += respondeu
            if not dados or dados.get("erro") or not dados.get(prova):
                continue
            logradouro = _texto(dados, "logradouro", "street")
            if not logradouro:
                return Endereco(cep=cep, valido=False, tipo="geral", origem=origem,
                                cidade=_texto(dados, "localidade", "city"), uf=_texto(dados, "uf", "state"),
                                mensagem="CEP geral da cidade, sem rua. Peça o CEP da rua.")
            return Endereco(cep=cep, valido=True, tipo="rua", mensagem="CEP válido (rua).", origem=origem,
                            logradouro=logradouro, bairro=_texto(dados, "bairro", "neighborhood"),
                            cidade=_texto(dados, "localidade", "city"), uf=_texto(dados, "uf", "state"))
        if not responderam:
            return Endereco(cep=cep, valido=False, falhou=True,
                            mensagem="Busca de CEP indisponível no momento (nenhuma fonte respondeu).")
        return Endereco(cep=cep, valido=False, mensagem="CEP não encontrado em nenhuma fonte.")
    finally:
        if proprio:
            await cliente.aclose()
