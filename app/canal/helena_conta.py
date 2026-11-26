"""Chamadas à API da Helena usadas pelo painel de gestão (ver docs/HELENA_API.md).

Cada função recebe o token já lido do cofre. Erro vira `ErroHelenaApi` com um
motivo curto, para o painel mostrar o que fazer.
"""

from __future__ import annotations

from typing import Any

import httpx

# Etiqueta liga/desliga a IA; MESSAGE_UPDATED traz o status da entrega (FAILED vira 'falhou' + nota na hora);
# PANEL_CARD_STEP_CHANGE: a equipe moveu o card de coluna e o lead passa para o agente daquela etapa (app/troca_etapa.py).
EVENTOS_DO_ATENDIMENTO = ["MESSAGE_RECEIVED", "MESSAGE_SENT", "MESSAGE_UPDATED", "CONTACT_TAG_UPDATE", "PANEL_CARD_STEP_CHANGE"]
NOME_DA_ASSINATURA = "LawChat IA (agentesia)"


class ErroHelenaApi(Exception):
    def __init__(self, motivo: str, detalhe: str = "", status: int | None = None) -> None:
        super().__init__(f"{motivo}: {detalhe}" if detalhe else motivo)
        self.motivo, self.detalhe, self.status = motivo, detalhe, status


class HelenaConta:
    def __init__(self, token: str, url_base: str = "https://api.helena.run",
                 http: httpx.AsyncClient | None = None) -> None:
        self._token = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        self._url = url_base.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=20)

    async def _pedir(self, metodo: str, caminho: str, **kwargs: Any) -> Any:
        try:
            resposta = await self._http.request(
                metodo, f"{self._url}/{caminho.lstrip('/')}",
                headers={"Authorization": self._token, "Accept": "application/json"}, **kwargs)
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as erro:
            if metodo.upper() == "POST":
                # O pedido pode já ter entrado na Helena (mensagem ao lead na fila): repetir mandaria duas vezes.
                raise ErroHelenaApi("talvez_enviado", type(erro).__name__) from erro
            raise ErroHelenaApi("sem_conexao", type(erro).__name__) from erro
        except httpx.HTTPError as erro:
            raise ErroHelenaApi("sem_conexao", type(erro).__name__) from erro
        if resposta.status_code in (401, 403):
            raise ErroHelenaApi("token_recusado", "a Helena recusou o token", resposta.status_code)
        if resposta.status_code == 404:
            raise ErroHelenaApi("nao_encontrado", caminho, 404)
        if resposta.status_code == 429:
            raise ErroHelenaApi("limite_de_uso", "muitas chamadas; tente em alguns minutos", 429)
        if resposta.status_code >= 400:
            raise ErroHelenaApi("erro_helena", f"HTTP {resposta.status_code}: {resposta.text[:200]}", resposta.status_code)
        if not resposta.content:
            return None
        try:
            return resposta.json()
        except ValueError:
            return None

    # ---------------------------------------------------------------- canais
    async def canais(self) -> list[dict[str, Any]]:
        dados = await self._pedir("GET", "chat/v1/channel", params={"ChannelType": "All"}) or []
        return [{
            "id": c.get("id"),
            "ativo": bool(c.get("active", True)),
            "tipo": "oficial" if str(c.get("type", "")).lower().startswith("cloudapi") else "nao_oficial",
            "tipo_helena": c.get("type"),
            "numero": c.get("number") or "",
            "numero_formatado": c.get("numberFormatted") or c.get("number") or "",
            "nome": (c.get("identity") or {}).get("displayName") or "",
            "foto": (c.get("identity") or {}).get("pictureUrl"),
            "provedor": (c.get("identity") or {}).get("provider"),
        } for c in dados if isinstance(c, dict)]

    # ---------------------------------------------------------------- webhook
    async def assinaturas(self) -> list[dict[str, Any]]:
        dados = await self._pedir("GET", "core/v1/webhook/subscription") or []
        saida = []
        for item in dados:
            eventos = [e.get("event") if isinstance(e, dict) else e for e in item.get("events") or []]
            saida.append({"id": item.get("id"), "nome": item.get("name"), "url": item.get("url"),
                          "ativa": bool(item.get("enabled")), "eventos": eventos})
        return saida

    async def garantir_assinatura(self, url: str, id_existente: str | None = None) -> dict[str, Any]:
        """Cria ou corrige a assinatura de webhook que traz as mensagens para o nosso servidor."""
        atuais = await self.assinaturas()
        nossa = next((a for a in atuais if a["id"] == id_existente), None) or \
            next((a for a in atuais if a["nome"] == NOME_DA_ASSINATURA), None)
        if nossa:
            certa = nossa["url"] == url and nossa["ativa"] and set(EVENTOS_DO_ATENDIMENTO) <= set(nossa["eventos"])
            if certa:
                return {**nossa, "acao": "ja_estava_certa"}
            await self._pedir("PUT", f"core/v1/webhook/subscription/{nossa['id']}", json={
                "fields": ["Url", "Events", "Enabled"], "url": url,
                "events": EVENTOS_DO_ATENDIMENTO, "enabled": True,
            })
            return {**nossa, "url": url, "ativa": True, "eventos": EVENTOS_DO_ATENDIMENTO, "acao": "corrigida"}
        criada = await self._pedir("POST", "core/v1/webhook/subscription", json={
            "name": NOME_DA_ASSINATURA, "url": url, "events": EVENTOS_DO_ATENDIMENTO, "enabled": True,
        }) or {}
        return {"id": criada.get("id"), "nome": NOME_DA_ASSINATURA, "url": url, "ativa": True,
                "eventos": EVENTOS_DO_ATENDIMENTO, "acao": "criada"}

    async def remover_assinatura(self, id_assinatura: str) -> None:
        await self._pedir("DELETE", f"core/v1/webhook/subscription/{id_assinatura}")

    # ---------------------------------------------------------------- CRM
    async def paineis(self) -> list[dict[str, Any]]:
        dados = await self._pedir("GET", "crm/v2/panel", params={"IncludeDetails": "Steps", "PageSize": 100}) or {}
        saida = []
        for painel in dados.get("items", []) if isinstance(dados, dict) else []:
            etapas = sorted(painel.get("steps") or [], key=lambda e: e.get("position") or 0)
            saida.append({
                "id": painel.get("id"), "titulo": painel.get("title"), "tipo": painel.get("type"),
                "etapas": [{"id": e.get("id"), "titulo": e.get("title"), "inicial": bool(e.get("isInitial")),
                            "final": bool(e.get("isFinal"))} for e in etapas if not e.get("archived")],
            })
        return saida

    async def etiquetas(self) -> list[dict[str, Any]]:
        dados = await self._pedir("GET", "core/v1/tag") or []
        return [{"id": t.get("id"), "nome": t.get("name"), "cor": t.get("color")} for t in dados]

    async def atendente(self, id_usuario: str) -> dict[str, Any] | None:
        """Confere se o usuário existe NESTA conta da Helena. Aceita o id do atendente ou do usuário."""
        try:
            dados = await self._pedir("GET", f"core/v1/agent/{id_usuario}")
        except ErroHelenaApi as erro:
            if erro.motivo != "nao_encontrado":
                raise
            dados = None
        if not dados:
            try:
                lista = await self._pedir("GET", "core/v1/agent", params={"PageSize": 100}) or []
            except ErroHelenaApi as erro:
                if erro.motivo != "nao_encontrado":
                    raise
                lista = []
            itens = lista.get("items", []) if isinstance(lista, dict) else lista
            dados = next((a for a in itens if id_usuario in (a.get("id"), a.get("userId"))), None)
        if not dados:
            return None
        return {"id": dados.get("id"), "id_usuario": dados.get("userId") or dados.get("id"),
                "nome": dados.get("name") or dados.get("shortName") or "Usuário da Helena",
                "email": (dados.get("email") or "").strip().lower() or None}

    # ---------------------------------------------------------------- ações do atendimento
    async def contato_da_sessao(self, id_sessao: str) -> str | None:
        dados = await self._pedir("GET", f"chat/v2/session/{id_sessao}") or {}
        return dados.get("contactId")

    async def card_do_contato(self, id_painel: str, id_contato: str) -> str | None:
        dados = await self._pedir("GET", "crm/v2/panel/card", params={
            "PanelId": id_painel, "ContactId": id_contato, "PageSize": 5,
            "OrderBy": "createdAt", "OrderDirection": "DESCENDING"}) or {}
        itens = dados.get("items", []) if isinstance(dados, dict) else []
        abertos = [c for c in itens if c.get("status", "OPEN") == "OPEN"] or itens
        return abertos[0].get("id") if abertos else None

    async def criar_card(self, *, id_etapa: str, titulo: str, id_contato: str | None,
                         id_sessao: str | None, descricao: str | None = None) -> str:
        corpo: dict[str, Any] = {"stepId": id_etapa, "title": titulo[:500]}
        if descricao:
            corpo["description"] = descricao[:4000]
        if id_contato:
            corpo["contactIds"] = [id_contato]
        if id_sessao:
            corpo["sessionId"] = id_sessao
        dados = await self._pedir("POST", "crm/v2/panel/card", json=corpo) or {}
        if not dados.get("id"):
            raise ErroHelenaApi("erro_helena", "a Helena não devolveu o card criado")
        return dados["id"]

    async def mover_card(self, id_card: str, id_etapa: str) -> None:
        await self._pedir("PUT", f"crm/v3/panel/card/{id_card}", json={"fields": ["StepId"], "stepId": id_etapa})

    async def descrever_card(self, id_card: str, descricao: str) -> None:
        """Troca a descrição do card (o resumo do contrato assinado vai nela). Mesmo PUT v3 do mover_card, com o campo
        Description (suposição: o v3 aceita "fields": ["Description"] como aceita ["StepId"])."""
        await self._pedir("PUT", f"crm/v3/panel/card/{id_card}", json={"fields": ["Description"], "description": descricao[:4000]})

    async def etiquetar(self, id_contato: str, nomes: list[str], *, remover: bool = False) -> None:
        if nomes:
            await self._pedir("POST", f"core/v1/contact/{id_contato}/tags", json={
                "tagNames": nomes, "operation": "DeleteIfExists" if remover else "InsertIfNotExists"})

    async def nota(self, id_sessao: str, texto: str) -> None:
        await self._pedir("POST", f"chat/v1/session/{id_sessao}/note", json={"text": texto[:4000]})

    async def transferir(self, id_sessao: str, id_equipe: str) -> None:
        await self._pedir("PUT", f"chat/v1/session/{id_sessao}/transfer", json={
            "type": "DEPARTMENT", "newDepartmentId": id_equipe, "options": {"stopBotInExecution": True}})

    async def enviar_no_atendimento(self, id_sessao: str, *, texto: str | None = None, url_arquivo: str | None = None,
                                    id_canal: str | None = None) -> str | None:
        """Mensagem no atendimento do lead (link do contrato, confirmação de assinatura, lembrete)."""
        corpo: dict[str, Any] = {"text": texto} if texto is not None else {"fileUrl": url_arquivo}
        if id_canal:
            corpo["channelId"] = id_canal
        dados = await self._pedir("POST", f"chat/v1/session/{id_sessao}/message", json=corpo) or {}
        return dados.get("id") if isinstance(dados, dict) else None

    async def status_da_mensagem(self, id_mensagem: str) -> dict[str, Any]:
        """Entrega de uma mensagem enviada (o envio é assíncrono): status (QUEUED, SENT, DELIVERED, READ, FAILED)
        e failureReason."""
        dados = await self._pedir("GET", f"chat/v1/message/{id_mensagem}/status")
        return dados if isinstance(dados, dict) else {}

    async def enviar_modelo_no_atendimento(self, id_sessao: str, id_modelo: str, parametros: dict[str, str] | None = None) -> str | None:
        """Modelo aprovado no atendimento: único jeito de falar no número oficial depois de 24 h sem resposta."""
        dados = await self._pedir("POST", f"chat/v1/session/{id_sessao}/message",
                                  json={"templateId": id_modelo, "parameters": parametros or {}}) or {}
        return dados.get("id") if isinstance(dados, dict) else None

    async def modelos_aprovados(self) -> list[dict[str, Any]]:
        dados = await self._pedir("GET", "chat/v1/template", params={"ApprovedOnly": "true", "PageSize": 100}) or {}
        itens = dados.get("items", dados) if isinstance(dados, dict) else dados
        return [{"id": t.get("id"), "nome": t.get("name"), "texto": t.get("text"), "canal": t.get("channelId"),
                 "parametros": [p.get("name") for p in t.get("params") or [] if isinstance(p, dict)]}
                for t in itens or [] if isinstance(t, dict)]

    async def enviar_sem_atendimento(self, *, de: str, para: str, texto: str, ref_id: str | None = None) -> str | None:
        """Mensagem para um número fora de atendimento aberto (aviso à equipe), sem abrir atendimento visível."""
        dados = await self._pedir("POST", "chat/v1/message/send", json={
            "from": de, "to": para, "body": {"text": texto, **({"refId": ref_id} if ref_id else {})},
            "options": {"enableBot": False, "hiddenSession": True, "forceStartSession": True}}) or {}
        return dados.get("id") if isinstance(dados, dict) else None

    async def login_integrado(self, *, email: str, id_conta: str, destino: str | None = None) -> dict[str, Any]:
        """POST auth/v1/login/authenticate (Login integrado): devolve o link de uso único que abre a Helena já
        logada na conta id_conta (tenantId) como o usuário do e-mail. Só no servidor: o token não vai ao navegador.
        O link (urlRedirect) carrega um código de acesso: nunca registrar em log."""
        corpo: dict[str, Any] = {"email": email, "tenantId": id_conta}
        if destino:
            corpo["redirectUrl"] = destino
        dados = await self._pedir("POST", "auth/v1/login/authenticate", json=corpo)
        return dados if isinstance(dados, dict) else {}

    async def equipes(self) -> list[dict[str, Any]]:
        dados = await self._pedir("GET", "core/v2/department", params={"PageSize": 100}) or {}
        itens = dados.get("items", dados) if isinstance(dados, dict) else dados
        return [{"id": d.get("id"), "nome": d.get("name"), "padrao": bool(d.get("isDefault"))} for d in itens or []]


class HelenaParceiro(HelenaConta):
    """Token de Parceiro: gestão de contas (só a equipe LawChat usa)."""

    async def empresas(self, busca: str = "", pagina: int = 1, por_pagina: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"PageSize": por_pagina, "PageNumber": pagina}
        if busca:
            params["SearchableText"] = busca
        dados = await self._pedir("GET", "core/v1/company", params=params) or {}
        return [{"id": c.get("id"), "nome": c.get("name") or c.get("legalName"), "ativa": bool(c.get("active")),
                 "email": c.get("email"), "telefone": c.get("phoneNumberFormatted") or c.get("phoneNumber")}
                for c in (dados.get("items", []) if isinstance(dados, dict) else [])]

    async def todas_as_empresas_completas(self, limite_paginas: int = 20) -> list[dict[str, Any]]:
        """Todas as contas do parceiro como a Helena devolve (documentId, legalName, address...), página a página
        (100 por página, até limite_paginas). Sem repetir id."""
        vistas: dict[str, dict[str, Any]] = {}
        for pagina in range(1, limite_paginas + 1):
            dados = await self._pedir("GET", "core/v1/company", params={"PageSize": 100, "PageNumber": pagina}) or {}
            lote = [c for c in (dados.get("items", []) if isinstance(dados, dict) else dados or []) if isinstance(c, dict)]
            novas = [c for c in lote if c.get("id") and str(c["id"]) not in vistas]
            for c in novas:
                vistas[str(c["id"])] = c
            if len(lote) < 100 or not novas:        # última página (ou a Helena ignorou a paginação)
                break
        return list(vistas.values())

    async def todas_as_empresas(self, limite_paginas: int = 20) -> list[dict[str, Any]]:
        """Todas as contas do parceiro, resumidas (id, nome, ativa, e-mail, telefone)."""
        return [{"id": c.get("id"), "nome": c.get("name") or c.get("legalName"), "ativa": bool(c.get("active")),
                 "email": c.get("email"), "telefone": c.get("phoneNumberFormatted") or c.get("phoneNumber")}
                for c in await self.todas_as_empresas_completas(limite_paginas)]

    async def criar_token(self, id_empresa: str, nome: str = "LawChat IA") -> str:
        dados = await self._pedir("POST", f"core/v1/company/{id_empresa}/tokens", json={"name": nome}) or {}
        token = dados.get("token")
        if not token:
            raise ErroHelenaApi("erro_helena", "a Helena não devolveu o token")
        return token
