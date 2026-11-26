"""Cliente da API da ZapSign (contrato a partir de modelo, leitura, cancelamento, signatário e plano).

Mesmo padrão de helena_conta.py: erro vira ErroZapSign com um motivo curto.
Criar documento não repete sozinho (repetir criaria dois contratos): quem decide é o Executor.
Campos e endpoints conferidos na documentação pública (docs.zapsign.com.br): detalhar documento, cancelar
(POST /api/v1/refuse/), atualizar signatário (POST /api/v1/signers/{token}/) e plano (GET /api/v1/info-plan/).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

URL_PRODUCAO = "https://api.zapsign.com.br"
URL_SANDBOX = "https://sandbox.api.zapsign.com.br"
USER_AGENT = "LawChat-IA/1.0"            # o cancelamento (refuse) exige User-Agent, senão a ZapSign trata como spam
LIMITE_PDF = 10 * 1024 * 1024            # a ZapSign limita os arquivos a 10 MB


class ErroZapSign(Exception):
    """motivo: chave | pagamento | limite | modelo | nao_encontrado | fora_do_ar"""

    def __init__(self, motivo: str, detalhe: str = "", status: int | None = None) -> None:
        super().__init__(f"{motivo}: {detalhe}" if detalhe else motivo)
        self.motivo, self.detalhe, self.status = motivo, detalhe, status

    @property
    def do_escritorio(self) -> bool:
        """Problema que só o escritório resolve (conta, plano, chave, modelo): repetir não adianta."""
        return self.motivo in ("chave", "pagamento", "limite", "modelo")


@dataclass(frozen=True)
class Assinante:
    token: str
    nome: str
    status: str                          # new | link-opened | signed (refused/rejected quando recusa)
    telefone: str | None
    link: str | None
    assinou_em: datetime | None
    vezes_visto: int = 0                 # times_viewed
    ultimo_acesso: datetime | None = None  # last_view_at
    id_externo: str | None = None        # external_id do signatário (quando a conta usa)
    email: str | None = None


@dataclass(frozen=True)
class DocumentoZapSign:
    token: str
    status: str                          # pending | signed | refused (cancelado ou recusado)
    arquivo_assinado: str | None         # signed_file: link temporário (vence em 60 min)
    assinantes: list[Assinante]
    excluido: bool = False               # deleted
    id_externo: str | None = None        # external_id do documento (= id do nosso contrato)
    motivo_recusa: str | None = None     # rejected_reason
    prazo: datetime | None = None        # date_limit_to_sign

    @property
    def link(self) -> str | None:
        return self.assinantes[0].link if self.assinantes else None

    def link_de(self, token_assinante: str | None) -> str | None:
        """Link do assinante certo (o lead), não do primeiro da lista."""
        achado = next((a for a in self.assinantes if token_assinante and a.token == token_assinante), None)
        return achado.link if achado else self.link


def _data(valor: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")) if valor else None
    except ValueError:
        return None


def _inteiro(valor: Any) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _documento(dados: dict[str, Any]) -> DocumentoZapSign:
    assinantes = [Assinante(
        token=str(s.get("token") or ""), nome=str(s.get("name") or ""),
        status=str(s.get("status") or s.get("status_code") or "").lower(),
        telefone=str(s.get("phone_number") or "") or None,
        link=s.get("sign_url") or s.get("signing_link"), assinou_em=_data(s.get("signed_at")),
        vezes_visto=_inteiro(s.get("times_viewed")), ultimo_acesso=_data(s.get("last_view_at")),
        id_externo=str(s.get("external_id") or "") or None, email=str(s.get("email") or "") or None,
    ) for s in dados.get("signers") or [] if isinstance(s, dict)]
    return DocumentoZapSign(token=str(dados.get("token") or ""), status=str(dados.get("status") or "").lower(),
                            arquivo_assinado=dados.get("signed_file"), assinantes=assinantes,
                            excluido=bool(dados.get("deleted")), id_externo=str(dados.get("external_id") or "") or None,
                            motivo_recusa=str(dados.get("rejected_reason") or "") or None,
                            prazo=_data(dados.get("date_limit_to_sign")))


def _motivo(status: int, texto: str) -> str:
    texto = texto.lower()
    if status == 402 or "payment required" in texto:
        return "pagamento"
    if status == 429 or any(p in texto for p in ("limit", "quota", "too many")):
        return "limite"
    if status == 403 and any(p in texto for p in ("already_signed", "already_refused", "refuse_not_allowed")):
        return "nao_encontrado"            # cancelar o que já foi assinado/cancelado: nada a repetir
    if status in (401, 403) or "unauthorized" in texto or "forbidden" in texto:
        return "chave"
    if status == 404:
        return "nao_encontrado"
    if status in (400, 422) or "template" in texto:
        return "modelo"
    return "fora_do_ar"


class ZapSign:
    def __init__(self, token: str, url_base: str = URL_PRODUCAO, http: httpx.AsyncClient | None = None) -> None:
        self._token = token.strip()
        self._url = url_base.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=45)

    @property
    def chave_cache(self) -> str:
        """Identifica a conta (para o cache do plano) sem guardar o token: só um resumo dele."""
        import hashlib
        return hashlib.sha256(f"{self._url}|{self._token}".encode()).hexdigest()[:24]

    async def _pedir(self, metodo: str, caminho: str, *, tentativas: int = 1, **kwargs: Any) -> Any:
        ultimo: ErroZapSign | None = None
        for _ in range(max(1, tentativas)):
            try:
                resposta = await self._http.request(
                    metodo, f"{self._url}/{caminho.lstrip('/')}",
                    headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json",
                             "User-Agent": USER_AGENT}, **kwargs)
            except httpx.HTTPError as erro:
                ultimo = ErroZapSign("fora_do_ar", type(erro).__name__)
                continue
            if resposta.status_code < 300:
                try:
                    return resposta.json()
                except ValueError:
                    return {}
            texto = resposta.text[:500]
            ultimo = ErroZapSign(_motivo(resposta.status_code, texto), texto, resposta.status_code)
            if ultimo.motivo != "fora_do_ar":
                break
        assert ultimo is not None
        raise ultimo

    async def criar_de_modelo(self, *, id_modelo: str, id_externo: str, nome: str, telefone: str | None,
                              email: str | None, variaveis: list[tuple[str, str]], pais: str = "55") -> DocumentoZapSign:
        """POST /api/v1/models/create-doc/. Uma tentativa só."""
        corpo: dict[str, Any] = {
            "template_id": id_modelo, "external_id": id_externo, "signer_name": nome,
            "signer_phone_country": pais, "signer_phone_number": telefone or "",
            "data": [{"de": de, "para": para} for de, para in variaveis],
        }
        if email:
            corpo["signer_email"] = email
        dados = await self._pedir("POST", "api/v1/models/create-doc/", json=corpo)
        documento = _documento(dados or {})
        if not documento.token or not any((a.link or "").startswith("http") for a in documento.assinantes):
            raise ErroZapSign("modelo", "a ZapSign não devolveu documento nem link")
        return documento

    async def documento(self, token_documento: str) -> DocumentoZapSign:
        return _documento(await self._pedir("GET", f"api/v1/docs/{token_documento}/", tentativas=3) or {})

    async def modelos(self) -> list[dict[str, Any]]:
        """Modelos da conta (também serve para testar o token)."""
        dados = await self._pedir("GET", "api/v1/templates/", tentativas=2)
        itens = dados.get("results", dados) if isinstance(dados, dict) else dados
        return [{"id": m.get("token"), "nome": m.get("name") or m.get("token")} for m in itens or [] if isinstance(m, dict)]

    async def variaveis_do_modelo(self, id_modelo: str) -> list[str]:
        dados = await self._pedir("GET", f"api/v1/templates/{id_modelo}/", tentativas=2) or {}
        campos = dados.get("inputs") or dados.get("variables") or []
        nomes = [str(c.get("variable") or c.get("label") or "").strip("{} ") for c in campos if isinstance(c, dict)]
        return [n for n in nomes if n]

    async def cancelar(self, token_documento: str, motivo: str) -> None:
        """POST /api/v1/refuse/: o documento vira recusado (marca d'água) e não pode mais ser assinado.
        Sem aviso ao signatário (notify_signer=false). 403 document_already_* vira 'nao_encontrado'."""
        await self._pedir("POST", "api/v1/refuse/", json={
            "doc_token": token_documento, "rejected_reason": motivo[:300], "notify_signer": False})

    async def atualizar_signatario(self, token_assinante: str, *, telefone: str | None = None,
                                   email: str | None = None, pais: str = "55") -> bool:
        """POST /api/v1/signers/{token}/: troca telefone e e-mail de quem ainda não assinou, sem novo documento
        (sem gastar crédito). Só manda os campos informados. Falso se não havia nada para mandar."""
        corpo: dict[str, Any] = {}
        if telefone:
            corpo.update(phone_country=pais, phone_number=telefone)
        if email:
            corpo["email"] = email
        if not corpo:
            return False
        await self._pedir("POST", f"api/v1/signers/{token_assinante}/", json=corpo)
        return True

    async def criar_webhook(self, url: str, cabecalhos: dict[str, str]) -> str | None:
        """POST /api/v1/user/company/webhook/: aviso da conta para todos os eventos de documento (type "").
        A senha vai como cabeçalho (não aparece na URL nem em log). Devolve o id do webhook."""
        dados = await self._pedir("POST", "api/v1/user/company/webhook/", json={
            "url": url, "type": "", "headers": [{"name": k, "value": v} for k, v in cabecalhos.items()]})
        ident = (dados or {}).get("id") if isinstance(dados, dict) else None
        return str(ident) if ident is not None else None

    async def plano(self) -> dict[str, Any]:
        """GET /api/v1/info-plan/: {name, number_of_credits, status, period, current_period_end}."""
        dados = await self._pedir("GET", "api/v1/info-plan/")
        return dados if isinstance(dados, dict) else {}

    async def baixar(self, url: str) -> bytes:
        """Baixa o PDF assinado pelo link temporário (signed_file, URL assinada do armazenamento da ZapSign), sem o
        cabeçalho Authorization (a URL assinada não precisa dele e o token não deve sair para outro host)."""
        try:
            resposta = await self._http.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        except httpx.HTTPError as erro:
            raise ErroZapSign("fora_do_ar", type(erro).__name__) from erro
        if resposta.status_code >= 300:
            raise ErroZapSign("fora_do_ar" if resposta.status_code >= 500 or resposta.status_code == 403 else "nao_encontrado",
                              f"download do PDF: HTTP {resposta.status_code}", resposta.status_code)
        if len(resposta.content) > LIMITE_PDF:
            raise ErroZapSign("nao_encontrado", "PDF maior que 10 MB")
        return resposta.content


# Situação do plano que impede gerar (o status da documentação de exemplo é "paid"; os outros são suposição).
PLANO_PENDENTE = ("unpaid", "overdue", "pending", "pending_payment", "past_due", "canceled", "cancelled", "expired",
                  "inactive", "suspended", "blocked")


def problema_do_plano(plano: dict[str, Any]) -> str | None:
    """sem_credito | plano_pendente | None. Só com resposta clara: campo ausente ou estranho não trava a geração."""
    status = str(plano.get("status") or "").strip().lower()
    if status in PLANO_PENDENTE:
        return "plano_pendente"
    creditos = plano.get("number_of_credits")
    try:
        if creditos is not None and str(creditos).strip() != "" and float(str(creditos).replace(",", ".")) <= 0:
            return "sem_credito"
    except ValueError:
        return None
    return None
