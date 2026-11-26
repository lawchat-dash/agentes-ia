"""Sincronizar a conta da Helena: copia para agentesia_helena_recursos o que existe na conta (canais, painéis, colunas,
etiquetas, equipes e usuários) e marca o que sumiu. Também cria as etiquetas padrão no onboarding.

A cópia serve para conferir as automações e para as telas não chamarem a Helena a cada abertura. Nunca é fonte de ação:
quem age na Helena (mover card, etiquetar, transferir) usa o id da configuração e a própria Helena confere.

Usa os métodos de leitura de `HelenaConta` (app/canal/helena_conta.py). O que falta lá (lista de usuários e criar
etiqueta) é feito aqui pelo mesmo cliente HTTP (`HelenaConta._pedir`), sem mexer no módulo do canal.
Usuário: só id e nome. E-mail e telefone de pessoas não entram na cópia.

Precisa da migração 006 (agentesia_helena_recursos, agentesia_canais.nome_exibicao/tipo_helena/sincronizado_em,
agentesia_escritorios.sincronizado_em).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.canal.helena import normalizar_telefone
from app.canal.helena_conta import ErroHelenaApi, HelenaConta

TIPOS = ("canal", "painel", "coluna", "etiqueta", "equipe", "usuario")

# Etiquetas que as automações e o liga/desliga da IA usam: nomes e cores do fluxo n8n de admin do Weaver
# ("ativar_criarcrm_criaretiqueta_criarwebhook"). Se a Helena recusar a cor, cria sem cor.
ETIQUETAS_PADRAO: list[tuple[str, str]] = [
    ("✅ Contrato Assinado", "GREEN_600"),
    ("✍️ Etapa de Assinatura", "YELLOW_400"),
    ("📄 Contrato em Elaboração", "YELLOW_600"),
    ("🛒 Comercial", "PURPLE_500"),
    ("📞 SDR", "BLUE_500"),
    ("❌ Desqualificado", "RED_300"),
    ("🤖 IA Desativada", "GRAY_600"),
]

# Equipe (departamento) que o n8n cria para a IA: POST core/v1/department {"name", "isDefault": true}.
EQUIPE_IA = "🤖 Comercial IA"

# Painel padrão do Weaver ("🤖 CRM COMERCIAL IA"): 6 etapas por tipo. A API pública NÃO cria painel (o n8n usa a API
# interna api.wts.chat com login de usuário por código no e-mail); aqui só se escolhe um painel existente e se liga
# cada tipo a uma coluna. Ordem da busca: do nome mais específico para o mais geral (para "Contrato Assinado" não
# cair em CONTRATO).
PAINEL_PADRAO = "🤖 CRM COMERCIAL IA"
TIPOS_DE_ETAPA = ["SDR", "COMERCIAL", "CONTRATO", "AGUARDANDO_ASSINATURA", "CONTRATO_ASSINADO", "DESQUALIFICADO"]
_PALAVRAS_DO_TIPO: list[tuple[str, tuple[str, ...]]] = [
    ("CONTRATO_ASSINADO", ("contrato assinado", "assinado")),
    ("AGUARDANDO_ASSINATURA", ("aguardando assinatura", "assinatura", "assinar")),
    ("DESQUALIFICADO", ("desqualif", "perdid", "descart")),
    ("CONTRATO", ("contrato em elabora", "elabora", "contrato", "document")),
    ("COMERCIAL", ("comercial", "closer", "proposta", "negocia")),
    ("SDR", ("sdr", "novo", "entrada", "lead", "triagem")),
]


def _chave_nome(nome: Any) -> str:
    return " ".join(str(nome or "").split()).casefold()


def _sem_acento(texto: Any) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto or "").casefold()) if not unicodedata.combining(c))


def mapear_etapas(painel: dict[str, Any], escolhidas: dict[str, str] | None = None) -> dict[str, str]:
    """{tipo: id da coluna} pelos nomes das colunas do painel; `escolhidas` (da tela) vence o palpite. Cada coluna
    vale para um tipo só. Colunas que não existem no painel são ignoradas."""
    colunas = {e["id"]: _sem_acento(e.get("titulo")) for e in painel.get("etapas") or [] if e.get("id")}
    mapa = {t: c for t, c in (escolhidas or {}).items() if t in TIPOS_DE_ETAPA and c in colunas}
    usadas = set(mapa.values())
    for tipo, palavras in _PALAVRAS_DO_TIPO:
        if tipo in mapa:
            continue
        for palavra in palavras:
            achada = next((i for i, t in colunas.items() if i not in usadas and _sem_acento(palavra) in t), None)
            if achada:
                mapa[tipo] = achada
                usadas.add(achada)
                break
    return {t: mapa[t] for t in TIPOS_DE_ETAPA if t in mapa}


async def criar_equipe_ia(helena: HelenaConta, equipes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Acha (pelo nome) ou cria a equipe da IA, como o n8n (isDefault=true)."""
    equipes = equipes if equipes is not None else await helena.equipes()
    achada = next((e for e in equipes if _chave_nome(e.get("nome")) == _chave_nome(EQUIPE_IA)), None)
    if achada:
        return {**achada, "criada": False}
    dados = await helena._pedir("POST", "core/v1/department", json={"name": EQUIPE_IA, "isDefault": True}) or {}
    return {"id": dados.get("id") if isinstance(dados, dict) else None, "nome": EQUIPE_IA, "criada": True}


# ---------------------------------------------------------------------------------------------- dados da empresa
def formatar_documento(documento: Any) -> str | None:
    """CNPJ 00.000.000/0000-00 ou CPF 000.000.000-00 (como o "Arruma formato Lovable" do n8n do Weaver)."""
    if not documento:
        return None
    d = "".join(c for c in str(documento) if c.isdigit())
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return str(documento)


def _formatar_cep(cep: Any) -> str | None:
    if not cep:
        return None
    d = "".join(c for c in str(cep) if c.isdigit())
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else str(cep)


def _formatar_telefone(telefone: Any) -> str | None:
    if not telefone:
        return None
    return "".join(c for c in str(telefone).replace("|", "") if c.isdigit() or c == "+") or None


def _foto_https(url: Any) -> str | None:
    """pictureUrl da empresa: só https (a tela mostra como <img>); vazio ou outro esquema vira None."""
    from urllib.parse import urlparse
    texto = str(url or "").strip()
    if not texto or len(texto) > 2000:
        return None
    partes = urlparse(texto)
    return texto if partes.scheme == "https" and partes.netloc else None


def limpar_empresa(c: dict[str, Any]) -> dict[str, Any]:
    """Dados cadastrais DA EMPRESA (GET core/v1/company, token de parceiro): nome fantasia, razão social, CNPJ/CPF
    (cru e formatado), tipo PF/PJ, administrador (a razão social, como no Weaver), e-mail e telefone de contato da
    empresa (pedido do dono para a tela Contas), endereço, plano e recursos. Dados de pessoas (usuários) não entram."""
    endereco = c.get("address") if isinstance(c.get("address"), dict) else {}
    config = c.get("config") if isinstance(c.get("config"), dict) else {}
    recursos = config.get("resources") if isinstance(config.get("resources"), dict) else {}
    endereco = {k: endereco.get(k) for k in ("zipcode", "address1", "number", "address2", "neighborhood", "city", "state")
                if endereco.get(k) is not None}
    if endereco.get("zipcode"):
        endereco["zipcode"] = _formatar_cep(endereco["zipcode"])
    if endereco.get("state"):
        endereco["state"] = str(endereco["state"]).upper()
    return {
        "nome": c.get("name"), "razao_social": c.get("legalName"), "email_contato": c.get("email"),
        "documento": c.get("documentId"), "documento_formatado": formatar_documento(c.get("documentId")),
        "tipo_documento": c.get("documentType"),
        "tipo_pessoa": "PJ" if str(c.get("documentType") or "").upper() == "CNPJ" else ("PF" if c.get("documentType") else None),
        "administrador": c.get("legalName"),
        "telefone": _formatar_telefone(c.get("phoneNumber")),
        "ativa": bool(c.get("active", True)),
        "foto": _foto_https(c.get("pictureUrl")),
        "endereco": endereco,
        "criada_em": c.get("createdAt"),
        # Nome do campo de plano não confirmado na documentação: guarda o que vier.
        "plano": c.get("plan") or config.get("plan"),
        "recursos": {k: recursos.get(k) for k in ("includedAgents", "includedSessions") if k in recursos},
    }


async def empresa_bruta(parceiro: HelenaConta, id_conta: str) -> dict[str, Any] | None:
    """Como o sync_one do Weaver: lista as contas do parceiro (todas as páginas) e filtra pelo id."""
    todas = getattr(parceiro, "todas_as_empresas_completas", None)
    if todas is not None:
        itens = await todas()
    else:
        dados = await parceiro._pedir("GET", "core/v1/company", params={"PageSize": 100}) or {}
        itens = dados.get("items", []) if isinstance(dados, dict) else dados
    return next((c for c in itens or [] if isinstance(c, dict) and str(c.get("id")).lower() == str(id_conta).lower()), None)


async def dados_da_empresa(parceiro: HelenaConta, id_conta: str) -> dict[str, Any] | None:
    achada = await empresa_bruta(parceiro, id_conta)
    return limpar_empresa(achada) if achada else None


# ---------------------------------------------------------------------------------------------- contas (tela Contas)
def _uuid_ou_none(valor: Any) -> str | None:
    import uuid as _uuid
    try:
        return str(_uuid.UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        return None


async def gravar_empresa(pool: Any, empresa: dict[str, Any], *, conta_lawchat: str | None = None) -> tuple[str, str]:
    """Upsert de uma empresa da Helena como conta (linha de agentesia_escritorios), casada por id_conta_helena.
    Atualiza nome (fantasia), dados_helena.conta e sincronizado_em; cria a que falta. Devolve (id, 'criada'|'atualizada').
    Não mexe em situação, token, agentes nem configurações de quem já existe. A conta da própria LawChat entra marcada
    (dados_helena.conta_lawchat = true) e nunca é tratada como cliente comum pela tela."""
    id_conta = _uuid_ou_none(empresa.get("id"))
    if not id_conta:
        raise ValueError("empresa sem id válido")
    conta = limpar_empresa(empresa)
    nome = (conta.get("nome") or conta.get("razao_social") or "").strip() or f"Conta {id_conta[:8]}"
    eh_lawchat = bool(conta_lawchat) and id_conta.lower() == str(conta_lawchat).strip().lower()
    extra = {"conta": conta, "conta_lawchat": eh_lawchat,
             "sync": {"situacao": "ok", "erro": None, "em": datetime.now(timezone.utc).isoformat()}}
    async with pool.acquire() as conexao, conexao.transaction():
        linha = await conexao.fetchrow(
            """insert into agentesia_escritorios (nome, id_conta_helena, situacao)
               values ($1, $2::uuid, $3)
               on conflict (id_conta_helena) do update set nome = excluded.nome, atualizado_em = now()
               returning id, (xmax = 0) as criada""",
            nome, id_conta, "ativo" if conta.get("ativa", True) else "suspenso")
        await conexao.execute(
            """update agentesia_escritorios set dados_helena = coalesce(dados_helena, '{}'::jsonb) || $2::jsonb,
                      sincronizado_em = now() where id = $1""",
            linha["id"], json.dumps(extra, ensure_ascii=False, default=str))
    return str(linha["id"]), ("criada" if linha["criada"] else "atualizada")


async def marcar_erro_sync(pool: Any, id_conta_helena: str, erro: str) -> None:
    """Webhook = 'error' na tela: a última sincronização desta conta falhou."""
    id_conta = _uuid_ou_none(id_conta_helena)
    if not id_conta:
        return
    await pool.execute(
        """update agentesia_escritorios set dados_helena = coalesce(dados_helena, '{}'::jsonb)
             || jsonb_build_object('sync', jsonb_build_object('situacao', 'erro', 'erro', $2::text, 'em', now()))
           where id_conta_helena = $1::uuid""", id_conta, erro[:300])


async def sincronizar_contas(pool: Any, empresas: list[dict[str, Any]], *, conta_lawchat: str | None = None) -> dict[str, Any]:
    """"Sincronizar com LawChat": upsert de cada empresa do token de parceiro. Uma que falha não para as outras."""
    criadas = atualizadas = 0
    erros: list[dict[str, Any]] = []
    for indice, empresa in enumerate(empresas):
        try:
            _, como = await gravar_empresa(pool, empresa, conta_lawchat=conta_lawchat)
            if como == "criada":
                criadas += 1
            else:
                atualizadas += 1
        except Exception as erro:                   # noqa: BLE001 — conta a falha e segue
            erros.append({"indice": indice, "id_conta_helena": empresa.get("id"), "nome": empresa.get("name"),
                          "erro": f"{type(erro).__name__}: {erro}"[:300]})
            try:
                await marcar_erro_sync(pool, str(empresa.get("id") or ""), str(erro))
            except Exception:                       # noqa: BLE001
                pass
    return {"total": len(empresas), "criadas": criadas, "atualizadas": atualizadas, "com_erro": len(erros),
            "erros": erros[:20]}


async def salvar_dados_helena(pool: Any, id_escritorio: str, *, conta: dict[str, Any] | None = None,
                              ids: dict[str, Any] | None = None) -> bool:
    """Grava em agentesia_escritorios.dados_helena: `conta` substitui; `ids` mistura com os que já estavam."""
    import asyncpg
    try:
        if conta is not None:
            await pool.execute(
                """update agentesia_escritorios set dados_helena = coalesce(dados_helena, '{}'::jsonb)
                     || jsonb_build_object('conta', $2::jsonb) where id = $1::uuid""",
                id_escritorio, json.dumps(conta, ensure_ascii=False, default=str))
        if ids:
            await pool.execute(
                """update agentesia_escritorios set dados_helena = coalesce(dados_helena, '{}'::jsonb)
                     || jsonb_build_object('ids', coalesce(dados_helena -> 'ids', '{}'::jsonb) || $2::jsonb)
                   where id = $1::uuid""",
                id_escritorio, json.dumps(ids, ensure_ascii=False, default=str))
        return True
    except asyncpg.UndefinedColumnError:
        return False                                # banco sem a 006


async def ler_dados_helena(pool: Any, id_escritorio: str) -> dict[str, Any]:
    valor = await pool.fetchval(
        "select to_jsonb(e) -> 'dados_helena' from agentesia_escritorios e where e.id = $1::uuid", id_escritorio)
    if isinstance(valor, str):
        valor = json.loads(valor or "{}")
    return valor or {}


def ids_das_etiquetas_padrao(etiquetas: list[dict[str, Any]]) -> dict[str, str]:
    padrao = {_chave_nome(n): n for n, _ in ETIQUETAS_PADRAO}
    return {padrao[_chave_nome(e.get("nome"))]: e["id"] for e in etiquetas
            if e.get("id") and _chave_nome(e.get("nome")) in padrao}


# ---------------------------------------------------------------------------------------------- leituras que faltam
async def usuarios(helena: HelenaConta) -> list[dict[str, Any]]:
    """Usuários (atendentes) da conta para a cópia: só id e nome (e-mail fica de fora da cópia). A lista completa,
    página a página e com timeout curto, vem de usuarios_helena.listar e segue em "_usuario" para alimentar
    agentesia_usuarios (usuarios_helena.sincronizar)."""
    from app.gestao import usuarios_helena
    return [{"id": u["id_usuario"], "nome": u["nome"],
             "dados": {"id_atendente": u.get("id_atendente"),
                       **({"disponibilidade": u["disponibilidade"]} if u.get("disponibilidade") else {}),
                       **({} if u["ativo"] else {"inativo": True})},
             "_usuario": u}
            for u in await usuarios_helena.listar(helena)]


async def criar_etiqueta(helena: HelenaConta, nome: str, cor: str | None) -> dict[str, Any]:
    """`POST core/v1/tag` com name e color. Se a cor for recusada (400), tenta sem cor."""
    try:
        dados = await helena._pedir("POST", "core/v1/tag", json={"name": nome, **({"color": cor} if cor else {})})
    except ErroHelenaApi as erro:
        if erro.status in (409, 500):
            # A Helena responde 500 ao criar uma etiqueta que já existe (e às vezes ela não volta na listagem).
            return {"id": None, "nome": nome, "cor": cor, "ja_existia": True}
        if not cor or erro.status != 400:
            raise
        dados = await helena._pedir("POST", "core/v1/tag", json={"name": nome})
    dados = dados if isinstance(dados, dict) else {}
    return {"id": dados.get("id"), "nome": dados.get("name") or nome, "cor": dados.get("color") or cor}


async def garantir_etiquetas_padrao(helena: HelenaConta, existentes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Cria só as etiquetas padrão que ainda não existem (pelo nome, sem diferença de maiúscula/espaço)."""
    existentes = existentes if existentes is not None else await helena.etiquetas()
    nomes = {_chave_nome(e.get("nome")) for e in existentes}
    criadas, ja_existiam = [], []
    for nome, cor in ETIQUETAS_PADRAO:
        if _chave_nome(nome) in nomes:
            ja_existiam.append(nome)
            continue
        feita = await criar_etiqueta(helena, nome, cor)
        (ja_existiam if feita.get("ja_existia") else criadas).append(nome if feita.get("ja_existia") else feita)
        nomes.add(_chave_nome(nome))
    return {"criadas": criadas, "ja_existiam": ja_existiam}


def etiquetas_padrao_faltando(existentes: list[dict[str, Any]]) -> list[str]:
    nomes = {_chave_nome(e.get("nome")) for e in existentes}
    return [nome for nome, _ in ETIQUETAS_PADRAO if _chave_nome(nome) not in nomes]


# ---------------------------------------------------------------------------------------------- leitura da conta
async def ler_conta(helena: HelenaConta) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Lê cada tipo separado: se um falhar, os outros ainda entram (e o que falhou não marca nada como sumido)."""
    recursos: dict[str, list[dict[str, Any]]] = {}
    erros: dict[str, str] = {}

    try:
        recursos["canal"] = [{
            "id": c["id"], "nome": c.get("nome") or c.get("numero_formatado") or c.get("numero"),
            "dados": {"numero": c.get("numero"), "tipo": c.get("tipo"), "tipo_helena": c.get("tipo_helena"),
                      "ativo": c.get("ativo"), "provedor": c.get("provedor")},
            "_canal": c,
        } for c in await helena.canais() if c.get("id")]
    except ErroHelenaApi as erro:
        erros["canal"] = erro.motivo

    try:
        paineis = await helena.paineis()
        recursos["painel"] = [{"id": p["id"], "nome": p.get("titulo"), "dados": {"tipo": p.get("tipo"),
                                                                                 "colunas": len(p.get("etapas") or [])}}
                              for p in paineis if p.get("id")]
        recursos["coluna"] = [{"id": e["id"], "id_pai": p["id"], "nome": e.get("titulo"), "posicao": i,
                               "dados": {"inicial": e.get("inicial"), "final": e.get("final"), "painel": p.get("titulo")}}
                              for p in paineis if p.get("id")
                              for i, e in enumerate(p.get("etapas") or [], start=1) if e.get("id")]
    except ErroHelenaApi as erro:
        erros["painel"] = erros["coluna"] = erro.motivo

    try:
        recursos["etiqueta"] = [{"id": t["id"], "nome": t.get("nome"), "dados": {"cor": t.get("cor")}}
                                for t in await helena.etiquetas() if t.get("id")]
    except ErroHelenaApi as erro:
        erros["etiqueta"] = erro.motivo

    try:
        recursos["equipe"] = [{"id": d["id"], "nome": d.get("nome"), "dados": {"padrao": d.get("padrao")}}
                              for d in await helena.equipes() if d.get("id")]
    except ErroHelenaApi as erro:
        erros["equipe"] = erro.motivo

    try:
        recursos["usuario"] = await usuarios(helena)
    except ErroHelenaApi as erro:
        erros["usuario"] = erro.motivo
    return recursos, erros


# ---------------------------------------------------------------------------------------------- gravação
async def gravar_detalhes_canais(pool: Any, id_escritorio: str, canais: list[dict[str, Any]]) -> None:
    """Nome de exibição e tipo cru da Helena nos canais (colunas da 006)."""
    for c in canais:
        if not c.get("id"):
            continue
        await pool.execute(
            """update agentesia_canais set nome_exibicao = $3, tipo_helena = $4, sincronizado_em = now()
               where id_escritorio = $1::uuid and id_canal_helena = $2""",
            id_escritorio, c["id"], c.get("nome") or None, c.get("tipo_helena"))


async def sincronizar(*, repo: Any, id_escritorio: str, helena: HelenaConta,
                      parceiro: HelenaConta | None = None, id_conta: str | None = None,
                      com_usuarios: bool = True, id_usuario: str | None = None) -> dict[str, Any]:
    """Lê a conta e atualiza a cópia. Devolve, por tipo, quantos existem, quantos são novos e quantos sumiram.
    Com o token de parceiro, também guarda os dados cadastrais da empresa (sem e-mail/telefone).
    Com `com_usuarios`, alinha também os logins do painel (agentesia_usuarios) com os usuários da conta, usando a
    mesma lista lida (resultado em "usuarios"; se a lista não veio, o erro já está em erros["usuario"])."""
    recursos, erros = await ler_conta(helena)
    pool = repo.pool
    conta = None
    if parceiro is not None and id_conta:
        try:
            conta = await dados_da_empresa(parceiro, id_conta)
        except ErroHelenaApi as erro:
            erros["empresa"] = erro.motivo
    ids: dict[str, Any] = {}
    if "etiqueta" in recursos:
        ids["etiquetas"] = ids_das_etiquetas_padrao(recursos["etiqueta"])
    if "equipe" in recursos:
        equipe_ia = next((e for e in recursos["equipe"] if _chave_nome(e.get("nome")) == _chave_nome(EQUIPE_IA)), None)
        if equipe_ia:
            ids["id_departamento"] = equipe_ia["id"]
    if conta is not None or ids:
        await salvar_dados_helena(pool, id_escritorio, conta=conta, ids=ids)
    if "canal" in recursos:
        canais = [r["_canal"] for r in recursos["canal"]]
        # Mesmo caminho do botão "Atualizar números": upsert por id do canal e desliga os que sumiram.
        await repo.sincronizar_canais(id_escritorio, [
            {**c, "numero_normalizado": normalizar_telefone(c["numero"]) or c["numero"]} for c in canais])
        await gravar_detalhes_canais(pool, id_escritorio, canais)

    agora = datetime.now(timezone.utc)
    tipos: dict[str, dict[str, int]] = {}
    async with pool.acquire() as conexao, conexao.transaction():
        for tipo in TIPOS:
            if tipo not in recursos:
                continue
            novos = 0
            vistos = []
            for item in recursos[tipo]:
                id_externo = str(item["id"])
                vistos.append(id_externo)
                novo = await conexao.fetchval(
                    """insert into agentesia_helena_recursos
                         (id_escritorio, tipo, id_externo, id_pai_externo, nome, posicao, dados, visto_em, sumiu_em)
                       values ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, $8, null)
                       on conflict (id_escritorio, tipo, id_externo) do update set
                         id_pai_externo = excluded.id_pai_externo, nome = excluded.nome, posicao = excluded.posicao,
                         dados = excluded.dados, visto_em = excluded.visto_em, sumiu_em = null
                       returning (xmax = 0)""",
                    id_escritorio, tipo, id_externo, item.get("id_pai"), item.get("nome"), item.get("posicao"),
                    json.dumps(item.get("dados") or {}, ensure_ascii=False, default=str), agora)
                novos += 1 if novo else 0
            sumiram = await conexao.fetchval(
                """with marcados as (
                     update agentesia_helena_recursos set sumiu_em = $4
                     where id_escritorio = $1::uuid and tipo = $2 and sumiu_em is null and not (id_externo = any($3::text[]))
                     returning 1)
                   select count(*)::int from marcados""", id_escritorio, tipo, vistos, agora)
            tipos[tipo] = {"total": len(vistos), "novos": novos, "sumiram": sumiram}
        if recursos:
            await conexao.execute("update agentesia_escritorios set sincronizado_em = $2 where id = $1::uuid",
                                  id_escritorio, agora)
    alinhados: dict[str, Any] | None = None
    if com_usuarios and "usuario" in recursos:
        from app.gestao import usuarios_helena
        try:
            alinhados = await usuarios_helena.sincronizar(
                repo=repo, id_escritorio=id_escritorio, lista=[r["_usuario"] for r in recursos["usuario"]],
                id_usuario=id_usuario)
        except Exception as erro:                   # noqa: BLE001 — opcional: não derruba a cópia
            erros["usuarios_painel"] = usuarios_helena.erro_legivel(erro)
    return {"sincronizado_em": agora.isoformat() if recursos else None, "tipos": tipos, "erros": erros,
            "completa": not erros, "empresa": conta, "usuarios": alinhados}


async def listar(pool: Any, id_escritorio: str, *, tipo: str | None = None, incluir_sumidos: bool = False) -> list[dict[str, Any]]:
    linhas = await pool.fetch(
        """select id, tipo, id_externo, id_pai_externo, nome, posicao, dados, visto_em, sumiu_em
           from agentesia_helena_recursos
           where id_escritorio = $1::uuid and ($2::text is null or tipo = $2) and ($3 or sumiu_em is null)
           order by tipo, id_pai_externo nulls first, posicao nulls last, nome""",
        id_escritorio, tipo, incluir_sumidos)
    saida = []
    for linha in linhas:
        item = dict(linha)
        item["id"] = str(item["id"])
        if isinstance(item.get("dados"), str):
            item["dados"] = json.loads(item["dados"] or "{}")
        saida.append(item)
    return saida
