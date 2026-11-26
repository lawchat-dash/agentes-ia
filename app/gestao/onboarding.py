"""Onboarding da conta (primeira criação do escritório), em passos com resultado guardado no escritório.

O Weaver fazia isto em três botões (Sincronizar, Criar Agente, Habilitar Funções) e deixava cliente sem painel e sem
etiqueta. Aqui cada passo volta com situacao ok | feito | aviso | erro | pulado (o mesmo `ativacao.Passo`) e o
resultado fica em agentesia_escritorios.onboarding (migração 006):

Ordem da primeira criação pedida pelo dono (um passo a passo só, retomável: cada passo reaproveita o que já existe):

  token          token da conta no cofre e aceito pela Helena. Sem token e com o token de parceiro, ao avançar cria
                 "IA LawChat" (POST core/v1/company/{id}/tokens), guarda no cofre e só o final no banco
  webhook        a assinatura de webhook existe e aponta para a URL do escritório (cria ou corrige ao avançar)
  equipe         a equipe "🤖 Comercial IA" existe (cria ao avançar com isDefault=true, como o n8n)
  etiquetas      as 7 etiquetas padrão existem na conta (cria as que faltam ao avançar; ids em dados_helena)
  painel         (a) um painel existente está escolhido e as colunas estão ligadas aos 6 tipos (SDR, COMERCIAL,
                 CONTRATO, AGUARDANDO_ASSINATURA, CONTRATO_ASSINADO, DESQUALIFICADO), pelo nome ou pela tela;
                 se a conta tem um painel só, ele é escolhido ao avançar
  painel_padrao  (b) criar o painel "🤖 CRM COMERCIAL IA": a API pública não cria painel (o n8n usa a API interna
                 com login de usuário por código no e-mail). Fica pendente até o dono decidir; opcional
  canais         os números da conta foram lidos (sincroniza ao avançar) e há pelo menos um conectado
  sincronizacao  dados da empresa (CNPJ, razão social, endereço, plano, e-mail de contato) e cópia da conta
                 (agentesia_helena_recursos) feitas ao avançar
  zapsign        token e modelo da ZapSign (opcional: só quem usa contrato)
  produto        há um produto (agente) ativado; a checagem do primeiro agente reaproveita ativacao.preparar

`aplicar=False` só confere (nada muda na Helena). `aplicar=True` faz o que o passo pode fazer sozinho.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import asyncpg
import httpx

from app.canal.helena import normalizar_telefone
from app.canal.helena_conta import EVENTOS_DO_ATENDIMENTO, NOME_DA_ASSINATURA, ErroHelenaApi, HelenaConta
from app.canal.webhook import url_do_escritorio
from app.gestao import ativacao, sincronizar_conta
from app.gestao.ativacao import Passo, Resultado

PASSOS: list[tuple[str, str]] = [
    ("token", "Token da conta na Helena (IA LawChat)"),
    ("webhook", "Recebimento das mensagens (webhook)"),
    ("equipe", "Equipe da IA na Helena (🤖 Comercial IA)"),
    ("etiquetas", "Etiquetas padrão"),
    ("painel", "Painel do CRM e etapas por tipo"),
    ("painel_padrao", "Criar o painel padrão (🤖 CRM COMERCIAL IA)"),
    ("canais", "Números de WhatsApp"),
    ("sincronizacao", "Dados da empresa e cópia da conta"),
    ("zapsign", "Contrato na ZapSign (opcional)"),
    ("produto", "Primeiro produto"),
]
CODIGOS = [c for c, _ in PASSOS]
OBRIGATORIOS = {"token", "webhook", "equipe", "etiquetas", "painel", "canais", "produto"}


NOME_DO_TOKEN = "IA LawChat"


def _erro_helena(erro: ErroHelenaApi) -> str:
    return "a Helena recusou o token" if erro.motivo == "token_recusado" else f"a Helena não respondeu ({erro.motivo})"


async def conferir(
    *,
    repo: Any,
    id_escritorio: str,
    helena_de: Callable[[str], Awaitable[HelenaConta]],
    aplicar: bool,
    passos: list[str] | None = None,
    id_painel: str | None = None,
    titulo_painel: str | None = None,
    etapas_por_tipo: dict[str, str] | None = None,
    http: httpx.AsyncClient | None = None,
    parceiro: HelenaConta | None = None,
    id_conta: str | None = None,
    guardar_token: Callable[[str], Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Confere (e, com aplicar, avança) os passos. `passos` limita o que é APLICADO; todos são conferidos."""
    alvo = set(passos or CODIGOS)
    faz = lambda codigo: aplicar and codigo in alvo  # noqa: E731
    r = Resultado()
    extra: dict[str, Any] = {}

    def passo(codigo: str) -> Passo:
        p = Passo(codigo, dict(PASSOS)[codigo])
        r.passos.append(p)
        return p

    integracoes = await repo.integracoes(id_escritorio)

    # 1. Token
    p_token = passo("token")
    helena: HelenaConta | None = None
    canais: list[dict[str, Any]] = []
    try:
        helena = await helena_de(id_escritorio)
        canais = await helena.canais()
        p_token("ok", f"token aceito; {len(canais)} números na conta")
    except ErroHelenaApi as erro:
        helena = None
        p_token("erro", _erro_helena(erro))
    except Exception as erro:                       # sem token no cofre (HTTPException 409) etc.
        helena = None
        p_token("erro", getattr(erro, "detail", None) or str(erro) or "cadastre o token da Helena")
    sem_token = helena is None and not ((integracoes.get("helena") or {}).get("tem_segredo"))
    if sem_token and faz("token") and parceiro is not None and id_conta and guardar_token is not None:
        # Só cria quando NÃO há token guardado (idempotente: um token recusado não gera outro sozinho).
        try:
            novo = await parceiro.criar_token(id_conta, NOME_DO_TOKEN)        # type: ignore[attr-defined]
            await guardar_token(novo)
            del novo
            helena = await helena_de(id_escritorio)
            canais = await helena.canais()
            p_token("feito", f"token \"{NOME_DO_TOKEN}\" criado e guardado no cofre; {len(canais)} números na conta")
        except ErroHelenaApi as erro:
            helena = None
            p_token("erro", "não deu para criar o token da conta (" + erro.motivo + ")")
        except Exception as erro:
            helena = None
            p_token("erro", getattr(erro, "detail", None) or "não deu para guardar o token da conta")
    elif sem_token and parceiro is None:
        p_token("erro", "cadastre o token da Helena (ou configure AGENTESIA_HELENA_TOKEN_PARCEIRO para criar)")
    if helena is not None:
        final = ((await repo.integracoes(id_escritorio)).get("helena") or {}).get("final_segredo")
        if final:
            await sincronizar_conta.salvar_dados_helena(repo.pool, id_escritorio, ids={"token_final": final})

    # 2. Webhook
    p_webhook = passo("webhook")
    url = url_do_escritorio(id_escritorio)
    id_assinatura = ((integracoes.get("helena") or {}).get("config") or {}).get("id_assinatura")
    if not url:
        p_webhook("pendente", "o servidor ainda não tem endereço público (AGENTESIA_URL_PUBLICA): o webhook é criado quando ele estiver no ar")
    elif _endereco_local(url):
        # A Helena não alcança localhost: não é erro da conta, só ainda não está no ar. Nem tenta (ela recusaria).
        p_webhook("pendente", "o sistema está rodando só neste computador; o webhook é criado sozinho quando ele estiver no ar (Easypanel)")
    elif helena is None:
        p_webhook("pulado", "depende do token")
    else:
        try:
            if faz("webhook"):
                assinatura = await helena.garantir_assinatura(url, id_assinatura)
                await repo.salvar_integracao(id_escritorio, "helena", situacao="ok",
                                             config={"id_assinatura": assinatura["id"], "webhook_conectado": True})
                await sincronizar_conta.salvar_dados_helena(repo.pool, id_escritorio, ids={"id_assinatura": assinatura["id"]})
                p_webhook("ok" if assinatura["acao"] == "ja_estava_certa" else "feito",
                          {"criada": "assinatura criada na Helena", "corrigida": "assinatura corrigida na Helena",
                           "ja_estava_certa": "assinatura já estava certa"}[assinatura["acao"]])
            else:
                atuais = await helena.assinaturas()
                nossa = next((a for a in atuais if a["id"] == id_assinatura), None) or \
                    next((a for a in atuais if a["nome"] == NOME_DA_ASSINATURA), None)
                certa = bool(nossa and nossa["url"] == url and nossa["ativa"]
                             and set(EVENTOS_DO_ATENDIMENTO) <= set(nossa["eventos"]))
                p_webhook("ok" if certa else "pendente", "assinatura certa" if certa else "será criada ou corrigida ao avançar")
        except ErroHelenaApi as erro:
            p_webhook("erro", f"a Helena não aceitou a assinatura ({erro.motivo})")

    # 3. Equipe da IA (como o n8n: "🤖 Comercial IA", isDefault=true)
    p_equipe = passo("equipe")
    if helena is None:
        p_equipe("pulado", "depende do token")
    else:
        try:
            equipes = await helena.equipes()
            achada = next((e for e in equipes if sincronizar_conta._chave_nome(e.get("nome"))
                           == sincronizar_conta._chave_nome(sincronizar_conta.EQUIPE_IA)), None)
            if achada:
                await sincronizar_conta.salvar_dados_helena(repo.pool, id_escritorio, ids={"id_departamento": achada["id"]})
                p_equipe("ok", f"{sincronizar_conta.EQUIPE_IA} existe")
            elif faz("equipe"):
                criada = await sincronizar_conta.criar_equipe_ia(helena, equipes)
                if criada.get("id"):
                    await sincronizar_conta.salvar_dados_helena(repo.pool, id_escritorio, ids={"id_departamento": criada["id"]})
                p_equipe("feito", f"{sincronizar_conta.EQUIPE_IA} criada (equipe padrão da conta)")
            else:
                p_equipe("pendente", f"{sincronizar_conta.EQUIPE_IA} será criada ao avançar e vira a equipe padrão da conta")
        except ErroHelenaApi as erro:
            p_equipe("erro", f"não deu para ler ou criar a equipe ({erro.motivo})")

    # 4. Etiquetas padrão
    p_etiquetas = passo("etiquetas")
    if helena is None:
        p_etiquetas("pulado", "depende do token")
    else:
        try:
            existentes = await helena.etiquetas()
            faltam = sincronizar_conta.etiquetas_padrao_faltando(existentes)
            if faltam and faz("etiquetas"):
                criadas = await sincronizar_conta.garantir_etiquetas_padrao(helena, existentes)
                existentes = existentes + criadas["criadas"]
                if criadas["criadas"]:
                    p_etiquetas("feito", "criadas: " + ", ".join(c["nome"] for c in criadas["criadas"]))
                else:
                    p_etiquetas("ok", "as etiquetas padrão já existem na conta")
            elif faltam:
                p_etiquetas("pendente", "faltam: " + ", ".join(faltam))
            else:
                p_etiquetas("ok", f"as {len(sincronizar_conta.ETIQUETAS_PADRAO)} etiquetas padrão existem")
            ids_etiquetas = sincronizar_conta.ids_das_etiquetas_padrao(existentes)
            if ids_etiquetas:
                await sincronizar_conta.salvar_dados_helena(repo.pool, id_escritorio, ids={"etiquetas": ids_etiquetas})
        except ErroHelenaApi as erro:
            p_etiquetas("erro", f"não deu para ler ou criar as etiquetas ({erro.motivo})")

    # 5. Painel do CRM (só escolher: a API não cria painel)
    p_painel = passo("painel")
    crm = (integracoes.get("crm") or {}).get("config") or {}
    if helena is None:
        p_painel("pulado", "depende do token")
    else:
        try:
            paineis = await helena.paineis()
            extra["paineis"] = [{"id": p["id"], "titulo": p["titulo"], "colunas": len(p["etapas"])} for p in paineis]
            escolhido = id_painel if faz("painel") and id_painel else None
            if escolhido is None and faz("painel") and not crm.get("id_painel") and len(paineis) == 1:
                escolhido = paineis[0]["id"]
            if escolhido is None and faz("painel") and etapas_por_tipo and crm.get("id_painel"):
                escolhido = crm["id_painel"]        # só remapear as etapas do painel já escolhido
            if escolhido:
                painel = next((p for p in paineis if p["id"] == escolhido), None)
                if not painel:
                    p_painel("erro", "o painel escolhido não existe nesta conta da Helena")
                else:
                    mapa = sincronizar_conta.mapear_etapas(painel, etapas_por_tipo)
                    await guardar_painel(repo, id_escritorio, painel, mapa, titulo_painel)
                    extra["etapas_por_tipo"] = mapa
                    faltam = [t for t in sincronizar_conta.TIPOS_DE_ETAPA if t not in mapa]
                    p_painel("aviso" if faltam else "feito",
                             f"painel {painel['titulo']} escolhido; {len(mapa)}/6 tipos ligados"
                             + (f"; sem coluna para: {', '.join(faltam)}" if faltam else ""))
            elif crm.get("id_painel"):
                painel = next((p for p in paineis if p["id"] == crm["id_painel"]), None)
                if painel:
                    colunas = {e["id"] for e in painel["etapas"]}
                    mapa = {t: c for t, c in (crm.get("etapas_por_tipo") or {}).items() if c in colunas}
                    extra["etapas_por_tipo"] = mapa
                    faltam = [t for t in sincronizar_conta.TIPOS_DE_ETAPA if t not in mapa]
                    p_painel("aviso" if faltam else "ok",
                             f"painel {painel['titulo']}; {len(mapa)}/6 tipos ligados"
                             + (f"; sem coluna para: {', '.join(faltam)}" if faltam else ""))
                else:
                    p_painel("erro", f"o painel {crm.get('titulo_painel') or ''} não existe mais na Helena; escolha outro")
            elif not paineis:
                p_painel("erro", "a conta não tem painel de CRM: crie um na Helena (a API não cria painel)")
            else:
                p_painel("pendente", f"escolha um dos {len(paineis)} painéis da conta")
        except ErroHelenaApi as erro:
            p_painel("erro", f"não deu para ler os painéis ({erro.motivo})")

    # 5b. Painel padrão: criado pela tela com código digitado (rotas_painel_crm, com travas). Nada é chamado aqui.
    p_padrao = passo("painel_padrao")
    if p_painel.situacao in ("ok", "feito", "aviso"):
        p_padrao("pulado", "usando um painel que já existe na conta")
    else:
        from app.gestao import painel_crm
        p_padrao("pendente", "a API pública da Helena não cria painel: use \"Enviar código\" (API interna, com simulação "
                             "antes) ou escolha um painel que já existe" if painel_crm.ligado() else
                 "a API pública da Helena não cria painel; a criação pela API interna está desligada no servidor "
                 "(AGENTESIA_PAINEL_CRM_LIGADO): escolha um painel que já existe")

    # 6. Canais (números)
    p_canais = passo("canais")
    if helena is None:
        p_canais("pulado", "depende do token")
    else:
        if faz("canais"):
            await repo.sincronizar_canais(id_escritorio, [
                {**c, "numero_normalizado": normalizar_telefone(c["numero"]) or c["numero"]} for c in canais if c["id"]])
            try:
                await sincronizar_conta.gravar_detalhes_canais(repo.pool, id_escritorio, canais)
            except asyncpg.UndefinedColumnError:
                pass                                # banco sem a 006: só não guarda nome e tipo
        conectados = [c for c in canais if c.get("ativo")]
        if not conectados:
            # Sem número não trava nada: o agente pode ser criado e configurado; o número entra depois.
            p_canais("pendente", "nenhum WhatsApp conectado ainda; dá para criar e configurar o agente. Depois de conectar o número, clique em Sincronizar conta")
        else:
            nomes = ", ".join((c.get("nome") or c.get("numero_formatado") or c.get("numero") or "?") for c in conectados[:3])
            p_canais("feito" if faz("canais") else "ok",
                     f"{len(conectados)} conectado(s): {nomes}" + ("…" if len(conectados) > 3 else ""))

    # 7. ZapSign (opcional)
    p_zapsign = passo("zapsign")
    zapsign = integracoes.get("zapsign") or {}
    modelos = [m for m in (zapsign.get("config") or {}).get("modelos") or [] if m.get("id_modelo")]
    if zapsign.get("situacao") == "ok" and modelos:
        p_zapsign("ok", f"token testado e {len(modelos)} modelo(s)")
    elif zapsign.get("situacao") == "ok":
        p_zapsign("aviso", "token testado; falta escolher o modelo de contrato")
    elif zapsign.get("situacao") == "erro":
        p_zapsign("erro", "o token da ZapSign deu erro no teste")
    else:
        p_zapsign("pulado", "só para quem gera contrato pela IA (Integrações > ZapSign)")

    # 8. Primeiro produto (reaproveita a checagem da ativação do agente)
    p_produto = passo("produto")
    agentes = await repo.agentes(id_escritorio)
    if not agentes:
        p_produto("pendente", "ative o primeiro produto (Produtos) para a IA ter um número e etapas")
    else:
        ligado = next((a for a in agentes if a.get("situacao") == "ativo"), None)
        if ligado:
            p_produto("ok", f"{ligado['nome']} ligado ({'teste' if ligado.get('modo') == 'teste' else 'para todos'})")
        else:
            agente = await repo.agente(id_escritorio, str(agentes[0]["id"]))
            if helena is None or agente is None:
                p_produto("aviso", f"{agentes[0]['nome']} criado e pausado; falta conferir a ativação")
            else:
                async def _mesma(_id: str) -> HelenaConta:
                    return helena                   # type: ignore[return-value]
                checagem = await ativacao.preparar(repo=repo, id_escritorio=id_escritorio, agente=agente,
                                                   modo=agente.get("modo") or "teste", aplicar=False,
                                                   helena_de=_mesma, http=http)
                extra["ativacao"] = checagem.como_dict()
                if checagem.pronto:
                    p_produto("aviso", f"{agente['nome']} pronto para ligar (Produtos > Ativar)")
                else:
                    p_produto("aviso", f"{agente['nome']}: " + "; ".join(checagem.pendencias))

    # 6b. Dados da empresa e cópia da conta
    p_sinc = passo("sincronizacao")
    if helena is None:
        p_sinc("pulado", "depende do token")
    elif faz("sincronizacao"):
        try:
            feita = await sincronizar_conta.sincronizar(repo=repo, id_escritorio=id_escritorio, helena=helena,
                                                        parceiro=parceiro, id_conta=id_conta)
            extra["sincronizacao"] = feita
            resumo = ", ".join(f"{v['total']} {t}" for t, v in feita["tipos"].items())
            if feita["erros"]:
                p_sinc("aviso", f"{resumo}; falhou: " + ", ".join(f"{t} ({m})" for t, m in feita["erros"].items()))
            else:
                p_sinc("feito", resumo)
        except asyncpg.UndefinedTableError:
            p_sinc("erro", "o banco ainda não tem a migração 006")
    else:
        quando = await _sincronizado_em(repo.pool, id_escritorio)
        p_sinc("ok" if quando else "pendente",
               f"última em {quando:%d/%m/%Y %H:%M}" if quando else "ainda não sincronizada")

    ordem = {c: i for i, c in enumerate(CODIGOS)}
    r.passos.sort(key=lambda p: ordem[p.codigo])
    agora = datetime.now(timezone.utc).isoformat()
    anterior = await ler(repo.pool, id_escritorio)
    completo = all(p.situacao in ("ok", "feito") for p in r.passos if p.codigo in OBRIGATORIOS)
    onboarding = {
        "passos": [{"codigo": p.codigo, "titulo": p.titulo, "situacao": p.situacao, "detalhe": p.detalhe, "em": agora}
                   for p in r.passos],
        "concluido_em": (anterior.get("concluido_em") or agora) if completo else None,
        "atualizado_em": agora,
        "aplicado": aplicar,
    }
    await salvar(repo.pool, id_escritorio, onboarding)
    return {**onboarding, "pronto": r.pronto, "completo": completo, "pendencias": r.pendencias,
            "dados_helena": await sincronizar_conta.ler_dados_helena(repo.pool, id_escritorio), **extra}


async def guardar_painel(repo: Any, id_escritorio: str, painel: dict[str, Any], mapa: dict[str, str],
                         titulo: str | None = None) -> dict[str, Any]:
    """Painel escolhido: na integração crm (que o motor lê: id_painel) e em dados_helena.ids (painel e etapas por tipo)."""
    config = {"id_painel": painel["id"], "titulo_painel": titulo or painel["titulo"], "etapas_por_tipo": mapa}
    await repo.salvar_integracao(id_escritorio, "crm", situacao="ok", config=config)
    await sincronizar_conta.salvar_dados_helena(repo.pool, id_escritorio,
                                                ids={"id_painel": painel["id"], "etapas_por_tipo": mapa})
    return config


async def _sincronizado_em(pool: Any, id_escritorio: str) -> datetime | None:
    valor = await pool.fetchval(
        "select to_jsonb(e) ->> 'sincronizado_em' from agentesia_escritorios e where e.id = $1::uuid", id_escritorio)
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


async def ler(pool: Any, id_escritorio: str) -> dict[str, Any]:
    """Onboarding guardado (vazio se ainda não houve ou se o banco não tem a 006)."""
    valor = await pool.fetchval(
        "select to_jsonb(e) -> 'onboarding' from agentesia_escritorios e where e.id = $1::uuid", id_escritorio)
    if isinstance(valor, str):
        valor = json.loads(valor or "{}")
    return valor or {}


async def salvar(pool: Any, id_escritorio: str, onboarding: dict[str, Any]) -> bool:
    try:
        await pool.execute("update agentesia_escritorios set onboarding = $2::jsonb where id = $1::uuid",
                           id_escritorio, json.dumps(onboarding, ensure_ascii=False, default=str))
        return True
    except asyncpg.UndefinedColumnError:
        return False                                # banco sem a 006: o resultado só volta para a tela


def _endereco_local(url: str) -> bool:
    """URL que só existe neste computador (localhost, 127.x, 0.0.0.0, ::1, *.local): a Helena não consegue chamar."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "0.0.0.0", "::1") or host.startswith("127.") or host.endswith(".local") or host.endswith(".localhost")
