"""Criar o painel padrão do CRM ("🤖 CRM COMERCIAL IA") pela API interna da Helena, como o fluxo n8n de admin.

ETAPA ARRISCADA: entra como a conta de outra empresa (impersonate). As chamadas seguem À RISCA o n8n em produção
(mesma ordem, endpoints, cabeçalhos e corpo); nada foi acrescentado às chamadas. As travas ficam em volta:

  send-otp      POST {interna}/auth/v2/login/send-otp            Content-Type/Accept json, Origin
                {"email","type":"EMAIL","partnerId"}
  login         POST {interna}/auth/v2/login/authenticate        idem; {"email","grantType":"OTP",
                "internalDeviceId","partnerId","password": código}                         -> accessToken
  empresas      GET  {interna}/core/v5/company?refPartnerId=…&pageSize=50&orderBy=name&includeDetails=PICTUREURL
                Authorization Bearer, Origin, Referer; items[].id == companyId do escritório (senão PARA)
  usuarios      GET  {interna}/core/v1/agent?companyId=…&pageSize=1000   Authorization Bearer;
                email == AGENTESIA_HELENA_ADMIN_EMAIL (senão PARA)
  impersonate   POST {interna}/auth/v2/login/authenticate/impersonate  Authorization Bearer (do login), Origin,
                Referer; {"userId","tenantId": companyId}                                 -> accessToken da conta
  painel        POST {interna}/crm/v1/panel   Authorization Bearer (do impersonate), Accept
                "application/json, text/plain, */*", Referer; corpo = painel_crm_padrao.CORPO_PAINEL_PADRAO
  gravar        id do painel e steps[0..5].id -> SDR, COMERCIAL, CONTRATO, AGUARDANDO_ASSINATURA,
                CONTRATO_ASSINADO, DESQUALIFICADO (ordem do array, igual ao n8n)

Tokens: só em variáveis locais; o do impersonate serve para UMA chamada (o POST do painel) e é descartado. Nunca em
banco, log, exceção ou resposta. Sem repetição automática; timeout de 15 s. Timeout no POST do painel = "incerto".

Configuração (só ambiente; ver .env.example): AGENTESIA_HELENA_INTERNA_URL, AGENTESIA_HELENA_PARCEIRO_EMAIL,
AGENTESIA_HELENA_PARCEIRO_ID, AGENTESIA_HELENA_DEVICE_ID, AGENTESIA_HELENA_PARCEIRO_ORIGEM (Origin/Referer do painel do
parceiro), AGENTESIA_HELENA_ADMIN_EMAIL.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from app.gestao import painel_crm_padrao

TIMEOUT_S = 15
VARIAVEIS = {
    "url": "AGENTESIA_HELENA_INTERNA_URL",
    "email": "AGENTESIA_HELENA_PARCEIRO_EMAIL",
    "parceiro": "AGENTESIA_HELENA_PARCEIRO_ID",
    "dispositivo": "AGENTESIA_HELENA_DEVICE_ID",
    "origem": "AGENTESIA_HELENA_PARCEIRO_ORIGEM",
    "admin": "AGENTESIA_HELENA_ADMIN_EMAIL",
}


class ErroPainelCrm(Exception):
    """Mensagem sempre sem token (as respostas da Helena nunca entram no texto)."""

    def __init__(self, passo: str, mensagem: str, *, incerto: bool = False, status: int | None = None) -> None:
        super().__init__(f"{passo}: {mascarar(mensagem)}")
        self.passo, self.mensagem, self.incerto, self.status = passo, mascarar(mensagem), incerto, status


_PARECE_TOKEN = re.compile(r"(Bearer\s+)?[A-Za-z0-9_\-]{24,}(\.[A-Za-z0-9_\-]+){0,2}")


def mascarar(texto: str) -> str:
    return _PARECE_TOKEN.sub("***", texto or "")


def configuracao() -> dict[str, str]:
    return {chave: (os.environ.get(nome) or "").strip() for chave, nome in VARIAVEIS.items()}


def faltando() -> list[str]:
    return [VARIAVEIS[c] for c, v in configuracao().items() if not v]


def ligado() -> bool:
    return os.environ.get("AGENTESIA_PAINEL_CRM_LIGADO", "").strip() == "1"


def mascarar_email(email: str) -> str:
    nome, _, dominio = (email or "").partition("@")
    return (nome[:2] + "…@" + dominio) if dominio else "…"


def _token(dados: Any) -> str | None:
    if not isinstance(dados, dict):
        return None
    for chave in ("accessToken", "access_token", "token"):
        if isinstance(dados.get(chave), str) and dados[chave]:
            return dados[chave]
    return None


def _referer(origem: str) -> str:
    return origem.rstrip("/") + "/"


class Fluxo:
    """Uma execução (um clique). `andamento` guarda cada passo com situação e detalhe, sem segredo."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.cfg = configuracao()
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT_S)
        self._proprio = http is None
        self.andamento: list[dict[str, str]] = []

    async def fechar(self) -> None:
        if self._proprio:
            await self._http.aclose()

    def marcar(self, passo: str, situacao: str, detalhe: str = "") -> None:
        self.andamento.append({"passo": passo, "situacao": situacao, "detalhe": mascarar(detalhe)})

    async def _chamar(self, passo: str, metodo: str, caminho: str, *, headers: dict[str, str],
                      params: dict[str, Any] | None = None, content: bytes | None = None,
                      incerto_no_timeout: bool = False) -> Any:
        """Uma tentativa só. Erro vira ErroPainelCrm com o passo, sem corpo de resposta."""
        url = f"{self.cfg['url'].rstrip('/')}/{caminho}"
        try:
            resposta = await self._http.request(metodo, url, headers=headers, params=params, content=content,
                                                timeout=TIMEOUT_S)
        except httpx.TimeoutException:
            raise ErroPainelCrm(passo, "a Helena não respondeu a tempo (15 s)", incerto=incerto_no_timeout) from None
        except httpx.HTTPError as erro:
            raise ErroPainelCrm(passo, f"não foi possível falar com a Helena ({type(erro).__name__})") from None
        if resposta.status_code >= 400:
            raise ErroPainelCrm(passo, f"a Helena respondeu HTTP {resposta.status_code}", status=resposta.status_code)
        try:
            return resposta.json() if resposta.content else None
        except ValueError:
            return None

    def _cab_login(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "application/json", "Origin": self.cfg["origem"]}

    # ------------------------------------------------------------------------------------------ passos
    async def enviar_codigo(self) -> None:
        corpo = {"email": self.cfg["email"], "type": "EMAIL", "partnerId": self.cfg["parceiro"]}
        await self._chamar("codigo", "POST", "auth/v2/login/send-otp", headers=self._cab_login(),
                           content=json.dumps(corpo).encode())
        self.marcar("codigo", "ok", f"código enviado para {mascarar_email(self.cfg['email'])}")

    async def login(self, codigo: str) -> str:
        corpo = {"email": self.cfg["email"], "grantType": "OTP", "internalDeviceId": self.cfg["dispositivo"],
                 "partnerId": self.cfg["parceiro"], "password": codigo}
        try:
            dados = await self._chamar("login", "POST", "auth/v2/login/authenticate", headers=self._cab_login(),
                                       content=json.dumps(corpo).encode())
        except ErroPainelCrm as erro:
            if erro.status in (400, 401, 403, 404, 422):
                raise ErroPainelCrm("login", "código errado ou vencido; peça um novo código") from None
            raise
        acesso = _token(dados)
        if not acesso:
            raise ErroPainelCrm("login", "a Helena não devolveu o acesso; peça um novo código")
        self.marcar("login", "ok", "código aceito")
        return acesso

    async def empresa(self, acesso: str, id_conta: str) -> dict[str, Any]:
        dados = await self._chamar(
            "empresas", "GET", "core/v5/company",
            headers={"Authorization": f"Bearer {acesso}", "Origin": self.cfg["origem"],
                     "Referer": _referer(self.cfg["origem"])},
            params={"refPartnerId": self.cfg["parceiro"], "pageSize": 50, "orderBy": "name",
                    "includeDetails": "PICTUREURL"})
        itens = dados.get("items", []) if isinstance(dados, dict) else []
        achada = next((c for c in itens if isinstance(c, dict) and str(c.get("id") or "").lower() == id_conta.lower()), None)
        if not achada:
            raise ErroPainelCrm("empresas", "a conta deste escritório não está na lista de empresas do parceiro")
        if str(achada["id"]).lower() != id_conta.lower():          # conferência de identidade (trava 4)
            raise ErroPainelCrm("empresas", "o id da empresa achada não bate com o do escritório")
        self.marcar("empresas", "ok", f"empresa {achada.get('name') or achada.get('legalName') or ''} achada")
        return {"id": str(achada["id"]), "nome": achada.get("name") or achada.get("legalName")}

    async def usuario_admin(self, acesso: str, id_conta: str) -> dict[str, Any]:
        dados = await self._chamar("usuarios", "GET", "core/v1/agent",
                                   headers={"Authorization": f"Bearer {acesso}"},
                                   params={"companyId": id_conta, "pageSize": 1000})
        itens = dados.get("items", dados) if isinstance(dados, dict) else (dados or [])
        alvo = self.cfg["admin"].strip().lower()
        achados = [a for a in itens or [] if isinstance(a, dict) and str(a.get("email") or "").strip().lower() == alvo]
        if len(achados) != 1:
            raise ErroPainelCrm("usuarios", "o usuário admin configurado não existe nesta conta" if not achados
                                else "mais de um usuário com o e-mail de admin nesta conta")
        usuario = achados[0]
        id_usuario = usuario.get("userId") or usuario.get("id")
        if not id_usuario:
            raise ErroPainelCrm("usuarios", "o usuário admin veio sem id")
        self.marcar("usuarios", "ok", f"usuário admin {mascarar_email(alvo)} achado")
        return {"id": str(id_usuario), "nome": usuario.get("name"), "email": mascarar_email(alvo)}

    async def impersonate(self, acesso: str, id_usuario: str, id_conta: str) -> str:
        corpo = {"userId": id_usuario, "tenantId": id_conta}
        dados = await self._chamar(
            "impersonate", "POST", "auth/v2/login/authenticate/impersonate",
            headers={"Authorization": f"Bearer {acesso}", "Origin": self.cfg["origem"],
                     "Referer": _referer(self.cfg["origem"]), "Content-Type": "application/json"},
            content=json.dumps(corpo).encode())
        na_conta = _token(dados)
        if not na_conta:
            raise ErroPainelCrm("impersonate", "a Helena não devolveu o acesso à conta do cliente")
        self.marcar("impersonate", "ok", "acesso à conta do cliente")
        return na_conta

    async def criar_painel(self, na_conta: str, id_usuario: str) -> dict[str, Any]:
        """Única chamada feita com o token do impersonate."""
        dados = await self._chamar(
            "painel", "POST", "crm/v1/panel",
            headers={"Authorization": f"Bearer {na_conta}", "Accept": "application/json, text/plain, */*",
                     "Referer": _referer(self.cfg["origem"]), "Content-Type": "application/json"},
            content=painel_crm_padrao.corpo_para(id_usuario), incerto_no_timeout=True)
        return dados if isinstance(dados, dict) else {}


def conferir_retorno(criado: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Mapa por tipo (ordem do array, igual ao n8n) e a lista de divergências do retorno."""
    passos = criado.get("steps") if isinstance(criado.get("steps"), list) else []
    divergencias = []
    if not criado.get("id"):
        divergencias.append("o retorno não tem id do painel")
    if len(passos) != 6:
        divergencias.append(f"o retorno tem {len(passos)} etapas (esperadas 6)")
    titulos = [p.get("title") if isinstance(p, dict) else None for p in passos]
    if len(passos) == 6 and titulos != painel_crm_padrao.TITULOS_DAS_ETAPAS:
        divergencias.append("os títulos das etapas não são os esperados")
    mapa = {tipo: str(p["id"]) for tipo, p in zip(painel_crm_padrao.TIPOS_NA_ORDEM, passos)
            if isinstance(p, dict) and p.get("id")}
    return mapa, divergencias
