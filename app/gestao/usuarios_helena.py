"""Usuários da conta na LawChat → agentesia_usuarios (login pelo painel), mantendo os dois iguais.

Lê `GET core/v1/agent` com o token da conta (todas as páginas, timeout curto) e, para o escritório:
  - cria quem existe na LawChat e não existe aqui (ligado por id_usuario_helena = userId da LawChat);
  - casa por e-mail quem foi criado no painel sem id_usuario_helena (passa a ser ligado);
  - atualiza nome, e-mail e papel; reativa quem voltou;
  - desativa (nunca apaga) quem saiu da LawChat.
Nunca mexe na equipe LawChat (papéis dono_lawchat/admin_lawchat): se o e-mail é de alguém da equipe, a pessoa fica
de fora (ela entra na conta pelo login integrado como equipe). Quem foi criado só no painel, sem id_usuario_helena,
também não é desativado.

Senha: quem nasce aqui entra pelo login integrado da LawChat (/entrar/helena); `senha_hash` recebe uma marca que
nenhuma senha confere (seguranca.conferir_senha devolve False), e trocar_senha = false.

Papel (a API devolve `profile` e `isOwner`; o painel "Buscar da helena" usa os mesmos campos):
  isOwner = true ou profile ADMIN/OWNER/ADMINISTRATOR → gestor  (o "dono" do nosso sistema é só da equipe LawChat)
  profile AGENT/USER/ATTENDANT/SUPERVISOR             → atendente
  sem profile reconhecido                             → quem já existe fica com o papel que tem; quem nasce recebe
                                                        config.papel_entrada_helena do escritório (padrão gestor),
                                                        o mesmo do login integrado
O histórico (agentesia_alteracoes) leva nome e papel; e-mail e telefone não entram.
"""

from __future__ import annotations

import json
from typing import Any

from app.canal.helena_conta import ErroHelenaApi, HelenaConta

PAPEIS_LAWCHAT = ("dono_lawchat", "admin_lawchat")
PAPEIS_CLIENTE = ("gestor", "atendente")
NOME_PAPEL = {"gestor": "gestor", "atendente": "atendente"}
SEM_SENHA = "sem_senha$login_pela_lawchat"       # não é scrypt: conferir_senha sempre recusa
TIMEOUT_S = 10.0
POR_PAGINA = 100
LIMITE_PAGINAS = 20

_PERFIS_GESTOR = {"ADMIN", "ADMINISTRATOR", "ADMINISTRADOR", "OWNER", "DONO"}
_PERFIS_ATENDENTE = {"AGENT", "USER", "ATTENDANT", "ATENDENTE", "SUPERVISOR", "OPERATOR"}


def papel_da_lawchat(atendente: dict[str, Any]) -> str | None:
    """gestor | atendente | None (perfil desconhecido: quem chama decide)."""
    if atendente.get("isOwner") is True:
        return "gestor"
    perfil = str(atendente.get("profile") or atendente.get("role") or "").strip().upper()
    if perfil in _PERFIS_GESTOR:
        return "gestor"
    if perfil in _PERFIS_ATENDENTE:
        return "atendente"
    return None


def _ativo_na_lawchat(a: dict[str, Any]) -> bool:
    for campo in ("active", "isActive", "enabled"):
        if a.get(campo) is False:
            return False
    return str(a.get("status") or "").upper() not in ("DELETED", "INACTIVE", "DISABLED", "REMOVED")


def _normalizar(a: dict[str, Any]) -> dict[str, Any] | None:
    id_usuario = a.get("userId") or a.get("id")
    if not id_usuario:
        return None
    email = str(a.get("email") or "").strip().lower() or None
    nome = str(a.get("name") or a.get("shortName") or "").strip() or (email.split("@")[0] if email else "Usuário da LawChat")
    disponibilidade = a.get("availability") or a.get("status")
    return {"id_usuario": str(id_usuario), "id_atendente": a.get("id"), "nome": nome[:200], "email": email,
            "papel": papel_da_lawchat(a), "ativo": _ativo_na_lawchat(a),
            "disponibilidade": disponibilidade if isinstance(disponibilidade, str) else None}


async def listar(helena: HelenaConta, *, timeout: float = TIMEOUT_S, por_pagina: int = POR_PAGINA,
                 limite_paginas: int = LIMITE_PAGINAS) -> list[dict[str, Any]]:
    """Todos os usuários da conta, página a página. Para quando a página vem curta, quando a resposta diz que não há
    mais (hasMorePages/totalPages) ou quando a página não traz ninguém novo (a LawChat ignorou a paginação)."""
    vistos: dict[str, dict[str, Any]] = {}
    for pagina in range(1, limite_paginas + 1):
        dados = await helena._pedir("GET", "core/v1/agent", params={"PageSize": por_pagina, "PageNumber": pagina},
                                    timeout=timeout) or []
        mais: Any = None
        total_paginas: Any = None
        if isinstance(dados, dict):
            itens = dados.get("items") or dados.get("data") or []
            mais = dados.get("hasMorePages", dados.get("hasNextPage"))
            total_paginas = dados.get("totalPages") or dados.get("pageCount")
        else:
            itens = dados
        novos = 0
        for bruto in itens or []:
            if not isinstance(bruto, dict):
                continue
            item = _normalizar(bruto)
            if item and item["id_usuario"] not in vistos:
                vistos[item["id_usuario"]] = item
                novos += 1
        if not novos or mais is False:
            break
        if mais is None and (int(total_paginas) <= pagina if isinstance(total_paginas, int) and total_paginas else
                             len(itens or []) < por_pagina):
            break
    return list(vistos.values())


def _email_reserva(id_usuario: str, id_escritorio: str) -> str:
    """O mesmo formato do login integrado, para quando o e-mail da LawChat falta ou já é de outra pessoa aqui."""
    return f"helena-{id_usuario}@{id_escritorio[:8]}.helena.local".lower()


def texto_do_resultado(r: dict[str, Any]) -> str:
    partes = [f"{r['criados']} criados", f"{r['atualizados']} atualizados", f"{r['desativados']} desativados"]
    if r.get("ignorados"):
        partes.append(f"{r['ignorados']} da equipe LawChat sem mudança")
    return ", ".join(partes)


async def sincronizar(*, repo: Any, id_escritorio: str, helena: HelenaConta | None = None,
                      lista: list[dict[str, Any]] | None = None, simular: bool = False,
                      id_usuario: str | None = None, escritorio: dict[str, Any] | None = None) -> dict[str, Any]:
    """Alinha agentesia_usuarios do escritório com a LawChat. `lista` (de `listar`) evita ler de novo; `simular`
    só conta o que faria; `escritorio` (a linha já lida) evita mais uma ida ao banco.
    Devolve {criados, atualizados, desativados, ignorados, total, aviso, mudancas}.
    Idas ao banco: 2 leituras (os usuários do escritório e os donos dos e-mails, juntas) e, se algo mudou, 2 escritas
    (todas as mudanças numa só e o histórico numa só), qualquer que seja o número de usuários."""
    if lista is None:
        if helena is None:
            raise ValueError("sem a LawChat e sem a lista de usuários")
        lista = await listar(helena)
    pool = repo.pool
    if escritorio is None:
        escritorio = await repo.escritorio(id_escritorio) or {}
    papel_novo = ((escritorio.get("config") or {}).get("papel_entrada_helena") or "gestor")
    papel_novo = papel_novo if papel_novo in PAPEIS_CLIENTE else "gestor"

    ativos = [u for u in lista if u["ativo"]]
    ids_ativos = {u["id_usuario"] for u in ativos}
    emails = sorted({u["email"] for u in ativos if u["email"]})
    # Uma ida só: os usuários do escritório e quem já tem cada e-mail (em qualquer escritório).
    linhas = await pool.fetch(
        """select 'local' as de, id::text as id, email, nome, papel, ativo, id_usuario_helena,
                  id_escritorio::text as id_escritorio
           from agentesia_usuarios where id_escritorio = $1::uuid
           union all
           select 'email', id::text, email, nome, papel, ativo, id_usuario_helena, id_escritorio::text
           from agentesia_usuarios where email = any($2::text[])""", id_escritorio, emails)
    locais = [{k: l[k] for k in ("id", "email", "nome", "papel", "ativo", "id_usuario_helena")}
              for l in linhas if l["de"] == "local"]
    donos = {l["email"]: {k: l[k] for k in ("id", "papel", "id_escritorio", "id_usuario_helena")}
             for l in linhas if l["de"] == "email"}
    por_helena = {l["id_usuario_helena"]: l for l in locais if l["id_usuario_helena"]}

    async def dono_do_email(email: str) -> dict[str, Any] | None:
        return donos.get(email)

    r: dict[str, Any] = {"criados": 0, "atualizados": 0, "desativados": 0, "ignorados": 0, "total": len(ativos),
                         "simulacao": simular, "aviso": None}
    mudancas: list[dict[str, Any]] = []              # para o histórico (nome e papel; nada de e-mail)
    usados: set[str] = set()                          # e-mails já tomados nesta rodada
    ligados: set[str] = set()                         # usuários daqui já casados com alguém da LawChat

    for h in ativos:
        local = por_helena.get(h["id_usuario"])
        email_livre: str | None = None
        if h["email"]:
            dono = await dono_do_email(h["email"])
            if dono and dono["papel"] in PAPEIS_LAWCHAT and local is None:
                r["ignorados"] += 1                   # equipe LawChat: nunca vira usuário do escritório
                continue
            if local is None and dono and dono["id_escritorio"] == id_escritorio and not dono["id_usuario_helena"] \
                    and dono["id"] not in ligados:
                local = next((l for l in locais if l["id"] == dono["id"]), None)       # casou pelo e-mail
            if (dono is None or (local is not None and dono["id"] == local["id"])) and h["email"] not in usados:
                email_livre = h["email"]
        if local is None:
            email = email_livre or _email_reserva(h["id_usuario"], id_escritorio)
            papel = h["papel"] or papel_novo
            usados.add(email)
            r["criados"] += 1
            mudancas.append({"acao": "criou", "nome": h["nome"], "papel": papel, "id": None, "h": h, "email": email})
            continue
        ligados.add(local["id"])
        novo: dict[str, Any] = {}
        if local["id_usuario_helena"] != h["id_usuario"]:
            novo["id_usuario_helena"] = h["id_usuario"]
        if h["nome"] and local["nome"] != h["nome"]:
            novo["nome"] = h["nome"]
        if email_livre and local["email"] != email_livre:
            novo["email"] = email_livre
            usados.add(email_livre)
        if h["papel"] and local["papel"] != h["papel"]:
            novo["papel"] = h["papel"]
        if not local["ativo"]:
            novo["ativo"] = True
        por_helena[h["id_usuario"]] = local
        if novo:
            r["atualizados"] += 1
            mudancas.append({"acao": "alterou", "id": local["id"], "nome": novo.get("nome", local["nome"]),
                             "antes": {k: local.get(k) for k in novo if k not in ("email", "id_usuario_helena")},
                             "novo": novo})

    # Quem saiu da LawChat. Lista vazia é suspeita (toda conta tem ao menos o dono): não desativa ninguém.
    if ativos:
        for l in locais:
            if l["id_usuario_helena"] and l["ativo"] and l["id_usuario_helena"] not in ids_ativos \
                    and l["papel"] in PAPEIS_CLIENTE:
                r["desativados"] += 1
                mudancas.append({"acao": "desativou", "id": l["id"], "nome": l["nome"]})
    elif any(l["id_usuario_helena"] for l in locais):
        r["aviso"] = "a LawChat devolveu a lista de usuários vazia: ninguém foi desativado"

    if not simular and mudancas:
        await _gravar(pool, id_escritorio, mudancas)
        for m in mudancas:
            if m.get("id"):
                repo.esquecer_usuario(m["id"])
        await _registrar(repo, pool, id_usuario, id_escritorio, mudancas)
    r["mudancas"] = [{"acao": m["acao"], "nome": m["nome"]} for m in mudancas]
    r["texto"] = texto_do_resultado(r)
    return r


async def _gravar(pool: Any, id_escritorio: str, mudancas: list[dict[str, Any]]) -> None:
    """Todas as mudanças numa ida ao banco (um comando só: tudo ou nada, como a transação de antes)."""
    criar = [{"email": m["email"], "nome": m["h"]["nome"], "papel": m["papel"], "id_usuario_helena": m["h"]["id_usuario"]}
             for m in mudancas if m["acao"] == "criou"]
    alterar = [{"id": m["id"], **{k: m["novo"].get(k) for k in ("id_usuario_helena", "nome", "email", "papel", "ativo")}}
               for m in mudancas if m["acao"] == "alterou"]
    desativar = [m["id"] for m in mudancas if m["acao"] == "desativou"]
    novos = await pool.fetch(
        """with novos as (
             insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, id_usuario_helena, trocar_senha)
             select x.email, x.nome, $2, x.papel, $1::uuid, x.id_usuario_helena, false
             from jsonb_to_recordset($3::jsonb) as x(email text, nome text, papel text, id_usuario_helena text)
             returning id::text as id, id_usuario_helena
           ), alterados as (
             update agentesia_usuarios u set
               id_usuario_helena = coalesce(x.id_usuario_helena, u.id_usuario_helena), nome = coalesce(x.nome, u.nome),
               email = coalesce(x.email, u.email), papel = coalesce(x.papel, u.papel), ativo = coalesce(x.ativo, u.ativo),
               atualizado_em = now()
             from jsonb_to_recordset($4::jsonb)
               as x(id uuid, id_usuario_helena text, nome text, email text, papel text, ativo boolean)
             where u.id = x.id and u.id_escritorio = $1::uuid
             returning u.id
           ), desativados as (
             update agentesia_usuarios u set ativo = false, atualizado_em = now()
             where u.id = any($5::uuid[]) and u.id_escritorio = $1::uuid
             returning u.id
           )
           select id, id_usuario_helena from novos""",
        id_escritorio, SEM_SENHA, json.dumps(criar, ensure_ascii=False), json.dumps(alterar, ensure_ascii=False),
        desativar)
    por_helena = {l["id_usuario_helena"]: l["id"] for l in novos}
    for m in mudancas:
        if m["acao"] == "criou":
            m["id"] = por_helena.get(m["h"]["id_usuario"])


async def _registrar(repo: Any, pool: Any, id_usuario: str | None, id_escritorio: str,
                     mudancas: list[dict[str, Any]]) -> None:
    """Histórico (agentesia_alteracoes) de todas as mudanças numa ida ao banco; o mesmo conteúdo de
    repo.registrar_alteracao (nome e papel; nada de e-mail)."""
    linhas = [{
        "id_registro": m["id"], "acao": m["acao"], "resumo": _resumo(m), "antes": m.get("antes"),
        "depois": ({"papel": m["papel"]} if m["acao"] == "criou" else
                   {k: v for k, v in (m.get("novo") or {}).items() if k not in ("email", "id_usuario_helena")}
                   if m["acao"] == "alterou" else {"ativo": False}),
    } for m in mudancas]
    await pool.execute(
        """insert into agentesia_alteracoes (id_usuario, id_escritorio, tabela, id_registro, acao, resumo, antes, depois)
           select $1::uuid, $2::uuid, 'agentesia_usuarios', x.id_registro, x.acao, x.resumo, x.antes, x.depois
           from jsonb_to_recordset($3::jsonb) as x(id_registro uuid, acao text, resumo text, antes jsonb, depois jsonb)""",
        id_usuario, id_escritorio, json.dumps(linhas, ensure_ascii=False, default=str))


def _resumo(m: dict[str, Any]) -> str:
    if m["acao"] == "criou":
        return f"{m['nome']} veio da LawChat como {NOME_PAPEL.get(m['papel'], m['papel'])} (entra pelo login da LawChat)"
    if m["acao"] == "desativou":
        return f"{m['nome']} saiu da LawChat: acesso desativado"
    n = m["novo"]
    partes = []
    if "nome" in n:
        partes.append("nome")
    if "email" in n:
        partes.append("e-mail")
    if "papel" in n:
        partes.append(f"papel: {NOME_PAPEL.get(m['antes'].get('papel'), m['antes'].get('papel'))} → {NOME_PAPEL[n['papel']]}")
    if n.get("ativo"):
        partes.append("reativado (voltou para a LawChat)")
    if "id_usuario_helena" in n and len(partes) == 0:
        partes.append("ligado ao usuário da LawChat")
    return f"{m['nome']} atualizado pela LawChat: " + ", ".join(partes)


def erro_legivel(erro: BaseException) -> str:
    """Texto para a tela, no padrão do onboarding."""
    if isinstance(erro, ErroHelenaApi):
        return {"token_recusado": "a LawChat recusou o token",
                "sem_conexao": "a LawChat não respondeu a tempo",
                "limite_de_uso": "a LawChat pediu para esperar (muitas chamadas); tente em alguns minutos",
                "nao_encontrado": "a LawChat não tem a lista de usuários para este token"}.get(
            erro.motivo, f"a LawChat não respondeu ({erro.motivo})")
    from app.gestao.onboarding import _inesperado
    return _inesperado(erro)
