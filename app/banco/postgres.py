"""Repositório no Postgres (Supabase), nas tabelas agentesia_*.

Só lê e grava tabelas que começam com agentesia_. Toda consulta usa parâmetros;
nenhum valor é colado no texto do SQL.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.banco.tipos import Agente, Canal, Escritorio, Etapa, Lead, Mensagem
from app.modelo import Chamada

_CAMPOS_DO_LEAD = {
    "id_agente", "id_etapa", "estado", "motivo_estado", "pausado_ate", "id_sessao_helena",
    "ultima_mensagem_lead_em", "ultima_resposta_ia_em",
}


def _json(valor: Any) -> dict[str, Any]:
    if valor is None:
        return {}
    return json.loads(valor) if isinstance(valor, str) else dict(valor)


def _texto(valor: Any) -> str | None:
    return None if valor is None else str(valor)


def contrato_pela_etapa(etapa: str | None) -> str:
    """Situação do contrato quando não há contrato gerado no sistema: a etapa do lead decide (regra do n8n)."""
    if etapa in ("contratoassinado", "contrato_assinado"):
        return "consta como JÁ ASSINADO."
    if etapa == "assinatura":
        return "já foi gerado e enviado ao lead. Ainda não consta a assinatura."
    return "ainda não foi gerado."


# Mensagens fora da janela do histórico (mesmo filtro e ordem de historico()) depois da marca da ficha.
# $1 lead, $2 janela, $3 limite, $4 corte de cada texto, $5 autores que entram. O corte ($3) vem nas duas consultas
# abaixo: do começo (resumo, a ficha anda em ordem) ou do fim (prompt, as antigas mais perto da janela).
_ANTIGAS_SEM_RESUMO_BASE = """
    with marca as (
      select m.enviada_em, m.registrada_em, m.id
      from agentesia_lead_resumo r join agentesia_mensagens m on m.id = r.ate_id_mensagem
      where r.id_lead = $1::uuid
    ), conversa as (
      select m.id, m.autor, coalesce(nullif(btrim(m.texto_extraido), ''), btrim(m.texto)) as texto,
             m.enviada_em, m.registrada_em,
             row_number() over (order by m.enviada_em desc, m.registrada_em desc, m.id desc) as de_tras
      from agentesia_mensagens m
      where m.id_lead = $1::uuid and not (m.autor = 'lead' and m.id_turno is null)
    )
    select c.id, c.autor, left(c.texto, $4) as texto, c.enviada_em, c.registrada_em, count(*) over () as pendentes
    from conversa c
    where c.de_tras > $2 and c.autor = any($5::text[]) and coalesce(c.texto, '') <> ''
      and (not exists (select 1 from marca)
           or (c.enviada_em, c.registrada_em, c.id) > (select enviada_em, registrada_em, id from marca))"""
_ANTIGAS_SEM_RESUMO = _ANTIGAS_SEM_RESUMO_BASE + """
    order by c.enviada_em, c.registrada_em, c.id
    limit $3"""
# Para o prompt: as últimas N antigas (as mais perto da janela), devolvidas da mais antiga para a mais nova.
_ANTIGAS_RECENTES_SEM_RESUMO = "select * from (" + _ANTIGAS_SEM_RESUMO_BASE + """
    order by c.enviada_em desc, c.registrada_em desc, c.id desc
    limit $3) t
    order by t.enviada_em, t.registrada_em, t.id"""


async def token_helena(conexao: Any, id_escritorio: Any) -> str | None:
    """Token da Helena do escritório: a integração cadastrada no painel e, como reserva, a coluna antiga.

    Fonte única para o envio do turno, o Executor da fila e o follow-up (nunca um token global do .env)."""
    try:
        return await conexao.fetchval(
            """select s.decrypted_secret
               from agentesia_escritorios e
               left join agentesia_integracoes i on i.id_escritorio = e.id and i.tipo = 'helena'
               join vault.decrypted_secrets s on s.id = coalesce(i.id_segredo_vault, e.id_segredo_helena)
               where e.id = $1::uuid
               limit 1""", str(id_escritorio))
    except (asyncpg.DataError, ValueError):
        return None


# A resposta da IA ganha do eco do próprio envio: se o MESSAGE_SENT (origem API) chegou antes e gravou o mesmo id
# como 'automacao', a linha passa a ser da IA, com o turno (sem isso, a boas-vindas sairia de novo no turno seguinte).
_GRAVAR_MENSAGEM_DA_IA = """insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, id_externo, autor, tipo, texto,
                                                 texto_extraido, url_midia, enviada_em, situacao_envio, erro)
               values ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               on conflict (id_escritorio, id_externo) where id_externo is not null do update
                 set autor = 'ia', id_turno = excluded.id_turno, situacao_envio = excluded.situacao_envio,
                     erro = excluded.erro, texto = coalesce(excluded.texto, agentesia_mensagens.texto),
                     texto_extraido = coalesce(excluded.texto_extraido, agentesia_mensagens.texto_extraido)
                 where agentesia_mensagens.autor = 'automacao'
               returning id"""


# Colunas e tabelas sem as quais o atendimento não funciona (migrações 001 e 002). Faltou: o servidor não sobe.
ESQUEMA_ESSENCIAL = {
    "agentesia_leads": ("responder_apos", "processando_ate"),
    "agentesia_acoes": ("chave_unica", "proxima_em"),
    "agentesia_followups": ("agendado_para",),
    "agentesia_eventos_recebidos": ("id_externo",),
    "agentesia_turnos": ("concluido_em",),
}


def chave_telefone(telefone: str | None) -> str | None:
    """Mesma conta da coluna gerada agentesia_contatos.telefone_chave (migração 006): 55 + DDD + 8 últimos dígitos."""
    import re
    if not telefone or not re.fullmatch(r"55\d{10,11}", telefone):
        return None
    return telefone[:4] + telefone[-8:]


def _segundos_do_env(nome: str, padrao: float) -> float:
    import os
    try:
        return max(1.0, float(os.environ.get(nome, padrao)))
    except ValueError:
        return padrao


class RepositorioPostgres:
    def __init__(self, pool: asyncpg.Pool, midia_pendente: bool = False, telefone_chave: bool = False) -> None:
        self._pool = pool
        self._midia_pendente = midia_pendente        # a coluna da migração 005 existe?
        self._telefone_chave = telefone_chave        # a coluna da migração 006 existe?

    @classmethod
    async def conectar(cls, url: str, max_conexoes: int = 10, conferir: bool = False) -> "RepositorioPostgres":
        """statement_cache_size=0: necessário com o pooler do Supabase (modo transação). `timeout` limita a espera por
        conexão e `command_timeout` uma consulta pendurada (pooler que não fecha o TCP): sem eles um turno ou webhook
        ficava preso para sempre. AGENTESIA_BANCO_TIMEOUT_S (padrão 10) e AGENTESIA_BANCO_COMANDO_S (padrão 15).
        conferir=True confere as migrações essenciais e falha na hora se faltar alguma."""
        pool = await asyncpg.create_pool(url, min_size=1, max_size=max_conexoes, statement_cache_size=0,
                                         timeout=_segundos_do_env("AGENTESIA_BANCO_TIMEOUT_S", 10),
                                         command_timeout=_segundos_do_env("AGENTESIA_BANCO_COMANDO_S", 15))
        repo = cls(pool)
        try:
            repo._midia_pendente = await repo._tem_coluna("agentesia_mensagens", "midia_pendente_desde")
            repo._telefone_chave = await repo._tem_coluna("agentesia_contatos", "telefone_chave")
            if conferir:
                await repo.conferir_esquema()
        except BaseException:
            await repo.fechar()
            raise
        return repo

    async def _tem_coluna(self, tabela: str, coluna: str) -> bool:
        return bool(await self._pool.fetchval(
            """select exists(select 1 from information_schema.columns
                             where table_schema = 'public' and table_name = $1 and column_name = $2)""", tabela, coluna))

    async def conferir_esquema(self) -> None:
        """Falha rápida na subida: sem as migrações 001/002 o webhook gravava a mensagem e dava 500 em seguida."""
        faltando: list[str] = []
        for tabela, colunas in ESQUEMA_ESSENCIAL.items():
            achadas = {r["column_name"] for r in await self._pool.fetch(
                """select column_name from information_schema.columns
                   where table_schema = 'public' and table_name = $1""", tabela)}
            if not achadas:
                faltando.append(tabela)
                continue
            faltando += [f"{tabela}.{c}" for c in colunas if c not in achadas]
        if faltando:
            raise RuntimeError("banco sem as migrações do atendimento (falta: " + ", ".join(faltando)
                               + "). Rode db/migracoes/001 e 002 (e as seguintes) antes de subir o servidor.")

    async def fechar(self) -> None:
        try:
            await asyncio.wait_for(self._pool.close(), 5)
        except asyncio.TimeoutError:                 # alguma conexão não fechou a tempo
            self._pool.terminate()

    # ---- recepção ----
    async def registrar_recebido(self, *, origem, id_externo, tipo, payload, id_escritorio) -> bool:
        linha = await self._pool.fetchrow(
            """insert into agentesia_eventos_recebidos (id_escritorio, origem, id_externo, tipo, payload, situacao, processado_em)
               values ($1::uuid, $2, $3, $4, $5::jsonb, 'processado', now())
               on conflict (origem, id_externo) do nothing returning id""",
            id_escritorio, origem, id_externo, tipo, json.dumps(payload, ensure_ascii=False),
        )
        return linha is not None

    # ---- configuração ----
    @staticmethod
    def _escritorio(linha: asyncpg.Record | None) -> Escritorio | None:
        if not linha:
            return None
        return Escritorio(id=str(linha["id"]), nome=linha["nome"], ia_desligada=linha["ia_desligada"],
                          situacao=linha.get("situacao") or "ativo",
                          id_segredo_helena=_texto(linha["id_segredo_helena"]), config=_json(linha["config"]))

    async def escritorio_por_conta(self, id_conta):
        try:
            linha = await self._pool.fetchrow(
                "select * from agentesia_escritorios where id_conta_helena = $1::uuid", id_conta)
        except (asyncpg.DataError, ValueError):
            return None                              # id de conta que não é uuid
        return self._escritorio(linha)

    async def escritorio(self, id_escritorio):
        # O token da Helena vem da integração cadastrada no painel; a coluna antiga fica como reserva.
        return self._escritorio(await self._pool.fetchrow(
            """select e.id, e.nome, (e.ia_desligada or e.situacao <> 'ativo') as ia_desligada, e.situacao, e.config,
                      coalesce(i.id_segredo_vault, e.id_segredo_helena) as id_segredo_helena
               from agentesia_escritorios e
               left join agentesia_integracoes i on i.id_escritorio = e.id and i.tipo = 'helena'
               where e.id = $1::uuid""", id_escritorio))

    @staticmethod
    def _canal(linha: asyncpg.Record | None) -> Canal | None:
        if not linha:
            return None
        return Canal(id=str(linha["id"]), id_escritorio=str(linha["id_escritorio"]),
                     numero_normalizado=linha["numero_normalizado"], id_canal_helena=linha["id_canal_helena"],
                     ativo=linha["ativo"], tipo=linha.get("tipo") or "nao_oficial")

    async def canal_por_numero(self, id_escritorio, numero):
        return self._canal(await self._pool.fetchrow(
            "select * from agentesia_canais where id_escritorio = $1::uuid and numero_normalizado = $2 and ativo",
            id_escritorio, numero))

    async def canal(self, id_canal):
        return self._canal(await self._pool.fetchrow("select * from agentesia_canais where id = $1::uuid", id_canal))

    async def agente_do_canal(self, id_canal):
        linha = await self._pool.fetchrow("select * from agentesia_agentes where id_canal = $1::uuid", id_canal)
        if not linha:
            return None
        etapas = await self._pool.fetch(
            "select * from agentesia_agente_etapas where id_agente = $1 order by ordem", linha["id"])
        return Agente(
            id=str(linha["id"]), id_escritorio=str(linha["id_escritorio"]), id_canal=str(linha["id_canal"]),
            nome=linha["nome"], produto=linha["produto"], situacao=linha["situacao"], modo=linha["modo"],
            minutos_pausa_humano=linha["minutos_pausa_humano"], config=_json(linha["config"]),
            numeros_teste=list(linha["numeros_teste"] or []),
            etapas=[Etapa(id=str(e["id"]), codigo=e["codigo"], principal=e["principal"],
                          instrucao=e["instrucao"], modelo=e["modelo"]) for e in etapas],
        )

    # ---- lead ----
    _LEAD = """select l.id, l.id_escritorio, l.id_canal, l.id_agente, l.id_etapa, l.estado, l.motivo_estado,
                      l.pausado_ate, l.id_sessao_helena, c.telefone_normalizado as telefone
               from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato"""

    @staticmethod
    def _lead(linha: asyncpg.Record | None, novo: bool = False) -> Lead | None:
        if not linha:
            return None
        return Lead(
            id=str(linha["id"]), id_escritorio=str(linha["id_escritorio"]), id_canal=str(linha["id_canal"]),
            id_agente=_texto(linha["id_agente"]), id_etapa=_texto(linha["id_etapa"]), telefone=linha["telefone"],
            estado=linha["estado"], motivo_estado=linha["motivo_estado"], pausado_ate=linha["pausado_ate"],
            id_sessao_helena=linha["id_sessao_helena"], novo=novo,
        )

    async def _contato_sem_nono_digito(self, conexao, id_escritorio, telefone, nome) -> Any:
        """Contato já gravado com o mesmo número a menos do nono dígito (a Helena às vezes manda sem o 9).
        Prefere o número exato (o insert normal acha); só usa a chave se houver UM contato com ela. Sem a 006, nada."""
        chave = chave_telefone(telefone)
        if not self._telefone_chave or not chave:
            return None
        if await conexao.fetchval(
                "select 1 from agentesia_contatos where id_escritorio = $1::uuid and telefone_normalizado = $2",
                id_escritorio, telefone):
            return None
        achados = await conexao.fetch(
            "select id from agentesia_contatos where id_escritorio = $1::uuid and telefone_chave = $2 limit 2",
            id_escritorio, chave)
        if len(achados) != 1:
            return None
        await conexao.execute(
            "update agentesia_contatos set atualizado_em = now(), nome = coalesce(nome, $2) where id = $1",
            achados[0]["id"], nome)
        return achados[0]["id"]

    async def achar_ou_criar_lead(self, *, escritorio, canal, agente, telefone, id_sessao, nome=None) -> Lead:
        principal = agente.principal() if agente else None
        async with self._pool.acquire() as conexao, conexao.transaction():
            id_contato = await self._contato_sem_nono_digito(conexao, escritorio.id, telefone, nome)
            if id_contato is None:
                id_contato = await conexao.fetchval(
                    """insert into agentesia_contatos (id_escritorio, telefone_normalizado, nome)
                       values ($1::uuid, $2, $3)
                       on conflict (id_escritorio, telefone_normalizado) where telefone_normalizado is not null
                       do update set atualizado_em = now(), nome = coalesce(agentesia_contatos.nome, excluded.nome)
                       returning id""",
                    escritorio.id, telefone, nome)
            criado = await conexao.fetchrow(
                """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena)
                   values ($1::uuid, $2, $3::uuid, $4::uuid, $5::uuid, $6)
                   on conflict (id_canal, id_contato) do update
                     set id_sessao_helena = coalesce(excluded.id_sessao_helena, agentesia_leads.id_sessao_helena)
                   returning id, (xmax = 0) as novo""",
                escritorio.id, id_contato, canal.id, agente.id if agente else None,
                principal.id if principal else None, id_sessao)
            linha = await conexao.fetchrow(self._LEAD + " where l.id = $1", criado["id"])
        lead = self._lead(linha, novo=criado["novo"])
        assert lead is not None
        return lead

    async def lead(self, id_lead):
        return self._lead(await self._pool.fetchrow(self._LEAD + " where l.id = $1::uuid", id_lead))

    async def lead_por_sessao(self, id_escritorio, id_sessao):
        """Lead do atendimento da Helena (para a fala do atendente que chega sem o número do contato)."""
        return self._lead(await self._pool.fetchrow(
            self._LEAD + " where l.id_escritorio = $1::uuid and l.id_sessao_helena = $2 order by l.criado_em desc limit 1",
            id_escritorio, id_sessao))

    async def lead_do_contato(self, id_escritorio, id_canal, *, id_contato_helena=None, telefone=None):
        """Lead do canal pelo contato da Helena (contactId) ou, de reserva, pelo telefone gravado (dados antigos com os
        dígitos do '@lid'). Para o webhook que chega sem número numa sessão nova."""
        if not id_contato_helena and not telefone:
            return None
        return self._lead(await self._pool.fetchrow(
            self._LEAD + """ where l.id_escritorio = $1::uuid and l.id_canal = $2::uuid
                              and (($3::text is not null and c.id_contato_helena = $3)
                                   or ($4::text is not null and c.telefone_normalizado = $4))
                            order by (c.id_contato_helena is not distinct from $3) desc, l.criado_em desc limit 1""",
            id_escritorio, id_canal, id_contato_helena, telefone))

    async def atualizar_lead(self, id_lead, **campos) -> None:
        desconhecidos = set(campos) - _CAMPOS_DO_LEAD
        if desconhecidos:
            raise ValueError(f"campo de lead não permitido: {sorted(desconhecidos)}")
        if not campos:
            return
        nomes = list(campos)                         # nomes vêm da lista fixa acima, nunca de fora
        atribuicoes = ", ".join(
            f"{nome} = ${i + 2}" + ("::uuid" if nome in ("id_etapa", "id_agente") else "") for i, nome in enumerate(nomes))
        await self._pool.execute(
            f"update agentesia_leads set {atribuicoes} where id = $1::uuid", id_lead, *[campos[n] for n in nomes])

    # ---- mensagens ----
    _GRAVAR_MENSAGEM = """insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, id_externo, autor, tipo, texto,
                                                 texto_extraido, url_midia, enviada_em, situacao_envio, erro)
               values ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               on conflict (id_escritorio, id_externo) where id_externo is not null do nothing
               returning id"""

    async def gravar_mensagem(self, *, lead, autor, tipo, texto, texto_extraido, url_midia, enviada_em,
                              id_externo, id_turno=None, situacao_envio="recebida", erro=None):
        id_mensagem = await self._pool.fetchval(
            _GRAVAR_MENSAGEM_DA_IA if autor == "ia" else self._GRAVAR_MENSAGEM,
            lead.id_escritorio, lead.id, id_turno, id_externo, autor, tipo, texto, texto_extraido, url_midia,
            enviada_em, situacao_envio, erro)
        return _texto(id_mensagem)

    async def lead_ja_escreveu(self, id_lead, *, antes_de=None) -> bool:
        """O lead já tinha mandado alguma mensagem ANTES da `antes_de` (a que acabou de chegar)?

        Só as anteriores contam (ordem: horário do WhatsApp, chegada, id): com duas mensagens quase juntas, cada webhook
        enxergava a outra e nenhum criava o card. Assim exatamente a primeira cria (a fila deduplica por {id_lead}:lead_novo)."""
        if antes_de is None:
            return bool(await self._pool.fetchval(
                "select exists(select 1 from agentesia_mensagens where id_lead = $1::uuid and autor = 'lead')", id_lead))
        return bool(await self._pool.fetchval(
            """select exists(select 1 from agentesia_mensagens m, agentesia_mensagens atual
                              where atual.id = $2::uuid and m.id_lead = $1::uuid and m.autor = 'lead' and m.id <> atual.id
                                and (m.enviada_em, m.registrada_em, m.id) < (atual.enviada_em, atual.registrada_em, atual.id))""",
            id_lead, antes_de))

    async def ultima_mensagem_do_lead(self, id_lead):
        """Quando o lead escreveu pela última vez (janela de 24 h do número oficial)."""
        return await self._pool.fetchval(
            "select max(enviada_em) from agentesia_mensagens where id_lead = $1::uuid and autor = 'lead'", id_lead)

    async def token_helena(self, id_escritorio):
        return await token_helena(self._pool, id_escritorio)

    async def marcar_envio_falhou(self, *, id_escritorio, id_externo, erro) -> dict | None:
        """A Helena avisou (status FAILED) que a mensagem da IA não foi entregue. Devolve a mensagem se mudou agora."""
        linha = await self._pool.fetchrow(
            """update agentesia_mensagens set situacao_envio = 'falhou', erro = $3
               where id_escritorio = $1::uuid and id_externo = $2 and autor = 'ia' and situacao_envio <> 'falhou'
               returning id, id_lead, id_turno, texto, url_midia""", id_escritorio, id_externo, (erro or "")[:500])
        return dict(linha) if linha else None

    async def registrar_fala_do_atendente(self, *, lead, tipo, texto, texto_extraido, url_midia, enviada_em,
                                          id_externo, pausa, motivo_followup):
        """Atendente falou: grava a fala, cancela o follow-up e pausa a IA numa transação só (tudo ou nada)."""
        from app.followup import servico

        async with self._pool.acquire() as conexao, conexao.transaction():
            id_mensagem = await conexao.fetchval(
                self._GRAVAR_MENSAGEM, lead.id_escritorio, lead.id, None, id_externo, "humano", tipo, texto,
                texto_extraido, url_midia, enviada_em, "recebida", None)
            await servico.cancelar(conexao, lead.id, motivo_followup)
            if pausa:
                await conexao.execute(
                    """update agentesia_leads set estado = $2, motivo_estado = $3, pausado_ate = $4
                       where id = $1::uuid""", lead.id, pausa["estado"], pausa["motivo_estado"], pausa["pausado_ate"])
        return _texto(id_mensagem)

    async def esquecer_recebido(self, *, origem, id_externo, tipo) -> None:
        """Desfaz a marca de recebido: o reenvio do mesmo webhook volta a ser processado."""
        if id_externo is not None:
            await self._pool.execute(
                "delete from agentesia_eventos_recebidos where origem = $1 and id_externo = $2", origem, id_externo)

    async def mensagem_por_id_externo(self, id_escritorio, id_externo):
        linha = await self._pool.fetchrow(
            "select * from agentesia_mensagens where id_escritorio = $1::uuid and id_externo = $2", id_escritorio, id_externo)
        return self._mensagem(linha) if linha else None

    async def ligar_eco_a_ia(self, id_escritorio, id_lead, *, id_externo, texto, url_midia, minutos=15) -> bool:
        """Eco (MESSAGE_SENT de origem API) de uma parte da IA que a Helena não confirmou (situação 'pendente', sem id):
        a linha da IA ganha o id e vira 'enviada', em vez de o eco ser gravado como 'automacao'."""
        if texto is None and url_midia is None:
            return False
        return bool(await self._pool.fetchval(
            """update agentesia_mensagens set id_externo = $3, situacao_envio = 'enviada', erro = null
               where id = (select id from agentesia_mensagens
                            where id_escritorio = $1::uuid and id_lead = $2::uuid and autor = 'ia' and id_externo is null
                              and situacao_envio = 'pendente' and enviada_em >= now() - make_interval(mins => $6)
                              and (($4::text is not null and btrim(texto) = btrim($4))
                                   or ($5::text is not null and url_midia = $5))
                            order by enviada_em limit 1)
               returning id""", id_escritorio, id_lead, id_externo, texto, url_midia, int(minutos)))

    async def eco_sem_dono(self, id_lead, *, texto, url_midia, minutos=15) -> str | None:
        """O eco chegou ANTES de a parte não confirmada ser gravada e virou 'automacao': devolve o id dele, para a parte
        da IA ser gravada com esse id (o upsert de _GRAVAR_MENSAGEM_DA_IA transforma a linha em 'ia')."""
        if texto is None and url_midia is None:
            return None
        return await self._pool.fetchval(
            """select id_externo from agentesia_mensagens
               where id_lead = $1::uuid and autor = 'automacao' and id_externo is not null
                 and enviada_em >= now() - make_interval(mins => $4)
                 and (($2::text is not null and btrim(texto) = btrim($2)) or ($3::text is not null and url_midia = $3))
               order by enviada_em desc limit 1""", id_lead, texto, url_midia, int(minutos))

    async def mensagem_e_da_ia(self, id_escritorio, id_externo) -> bool:
        return bool(await self._pool.fetchval(
            "select exists(select 1 from agentesia_mensagens where id_escritorio = $1::uuid and id_externo = $2 and autor = 'ia')",
            id_escritorio, id_externo))

    @staticmethod
    def _mensagem(linha: asyncpg.Record) -> Mensagem:
        return Mensagem(id=str(linha["id"]), autor=linha["autor"], tipo=linha["tipo"], texto=linha["texto"],
                        texto_extraido=linha["texto_extraido"], enviada_em=linha["enviada_em"],
                        id_turno=_texto(linha["id_turno"]), id_externo=linha["id_externo"],
                        url_midia=linha.get("url_midia"), midia_pendente_desde=linha.get("midia_pendente_desde"))

    async def mensagens_pendentes(self, id_lead):
        linhas = await self._pool.fetch(
            """select * from agentesia_mensagens
               where id_lead = $1::uuid and autor = 'lead' and id_turno is null
               order by enviada_em, registrada_em""", id_lead)
        return [self._mensagem(l) for l in linhas]

    async def historico(self, id_lead, limite=40):
        linhas = await self._pool.fetch(
            """select * from (
                 select * from agentesia_mensagens
                 where id_lead = $1::uuid and not (autor = 'lead' and id_turno is null)
                 order by enviada_em desc, registrada_em desc limit $2
               ) recentes order by enviada_em, registrada_em""", id_lead, limite)
        return [self._mensagem(l) for l in linhas]

    # ---- memória longa (ficha da conversa antiga) ----
    async def _antigas_sem_resumo(self, id_lead, janela, limite, corte, recentes=False) -> list[asyncpg.Record]:
        from app.memoria import AUTORES
        consulta = _ANTIGAS_RECENTES_SEM_RESUMO if recentes else _ANTIGAS_SEM_RESUMO
        return await self._pool.fetch(consulta, id_lead, janela, limite, corte, list(AUTORES))

    async def comeco_da_conversa(self, id_lead, *, janela=40, limite=60, corte=600) -> dict:
        """Ficha guardada e as antigas fora da janela que ainda não entraram nela (para o prompt): as `limite` mais
        recentes, logo antes da janela, mais antiga primeiro. `pendentes` conta todas, não só as do corte."""
        ficha = await self._pool.fetchrow(
            "select resumo, ate_id_mensagem from agentesia_lead_resumo where id_lead = $1::uuid", id_lead)
        linhas = await self._antigas_sem_resumo(id_lead, janela, limite, corte, recentes=True)
        return {"resumo": ficha["resumo"] if ficha else "", "ate_id_mensagem": _texto(ficha["ate_id_mensagem"]) if ficha else None,
                "antigas": [{"autor": l["autor"], "texto": l["texto"]} for l in linhas],
                "pendentes": int(linhas[0]["pendentes"]) if linhas else 0}

    async def trecho_para_resumir(self, id_lead, *, janela=40, limite=150, corte=1500) -> dict:
        """Ficha anterior e o trecho antigo ainda sem resumo (até 150 mensagens, mais antiga primeiro)."""
        resumo = await self._pool.fetchval("select resumo from agentesia_lead_resumo where id_lead = $1::uuid", id_lead)
        linhas = await self._antigas_sem_resumo(id_lead, janela, limite, corte)
        return {"resumo": resumo or "",
                "mensagens": [{"id": str(l["id"]), "autor": l["autor"], "texto": l["texto"]} for l in linhas]}

    async def gravar_resumo(self, *, id_lead, resumo, ate_id_mensagem, quantidade, modelo, tokens) -> None:
        """Uma ficha por lead. A marca só anda para a frente (o GREATEST do n8n, pela ordem das mensagens)."""
        await self._pool.execute(
            """insert into agentesia_lead_resumo (id_lead, id_escritorio, resumo, ate_id_mensagem, mensagens_resumidas, modelo, tokens)
               select l.id, l.id_escritorio, $2, $3::uuid, $4, $5, $6 from agentesia_leads l where l.id = $1::uuid
               on conflict (id_lead) do update set
                 resumo = excluded.resumo,
                 ate_id_mensagem = case
                   when (select row(m.enviada_em, m.registrada_em, m.id) from agentesia_mensagens m
                          where m.id = agentesia_lead_resumo.ate_id_mensagem)
                      > (select row(n.enviada_em, n.registrada_em, n.id) from agentesia_mensagens n
                          where n.id = excluded.ate_id_mensagem)
                   then agentesia_lead_resumo.ate_id_mensagem else excluded.ate_id_mensagem end,
                 mensagens_resumidas = agentesia_lead_resumo.mensagens_resumidas + excluded.mensagens_resumidas,
                 modelo = excluded.modelo, tokens = excluded.tokens""",
            id_lead, resumo, ate_id_mensagem, quantidade, modelo, tokens)

    async def marcar_no_turno(self, ids_mensagens, id_turno) -> None:
        await self._pool.execute(
            "update agentesia_mensagens set id_turno = $2::uuid where id = any($1::uuid[])", ids_mensagens, id_turno)

    # ---- fatos ----
    async def fatos_vigentes(self, id_lead):
        linhas = await self._pool.fetch(
            "select chave, valor from agentesia_lead_fatos where id_lead = $1::uuid and substituido_em is null", id_lead)
        return {l["chave"]: json.loads(l["valor"]) if isinstance(l["valor"], str) else l["valor"] for l in linhas}

    async def gravar_fatos(self, *, lead, id_turno, fatos) -> None:
        async with self._pool.acquire() as conexao, conexao.transaction():
            for fato in fatos:
                await conexao.execute(
                    """update agentesia_lead_fatos set substituido_em = now()
                       where id_lead = $1::uuid and chave = $2 and substituido_em is null""", lead.id, fato["chave"])
                await conexao.execute(
                    """insert into agentesia_lead_fatos (id_escritorio, id_lead, chave, valor, trecho, fonte, id_turno)
                       values ($1::uuid, $2::uuid, $3, $4::jsonb, $5, $6, $7::uuid)""",
                    lead.id_escritorio, lead.id, fato["chave"], json.dumps(fato["valor"], ensure_ascii=False),
                    fato.get("trecho"), fato.get("fonte") or "extrator", id_turno)

    # ---- turno, chamadas, eventos ----
    async def abrir_turno(self, *, lead, modo, etapa_antes) -> str:
        return str(await self._pool.fetchval(
            """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes)
               values ($1::uuid, $2::uuid, $3, $4) returning id""", lead.id_escritorio, lead.id, modo, etapa_antes))

    async def fechar_turno(self, id_turno, *, situacao, motivo, etapa_depois, contexto, resposta) -> None:
        await self._pool.execute(
            """update agentesia_turnos set situacao = $2, motivo = $3, etapa_depois = $4,
                      contexto = $5::jsonb, resposta = $6::jsonb, concluido_em = now()
               where id = $1::uuid""",
            id_turno, situacao, motivo, etapa_depois,
            json.dumps(contexto, ensure_ascii=False, default=str) if contexto is not None else None,
            json.dumps(resposta, ensure_ascii=False, default=str) if resposta is not None else None)

    async def fatos_do_sistema(self, id_lead) -> dict:
        linha = await self._pool.fetchrow(
            """select nullif(btrim(coalesce(ct.nome, ''), ' ''"'), '') as nome, ct.telefone_normalizado, l.criado_em, l.origem,
                      et.codigo as etapa,
                      (select row(k.situacao, k.versao, k.link, k.gerado_em, coalesce(k.lead_assinou_em, k.assinado_em))
                        from agentesia_contratos k where k.id_lead = l.id
                        and k.situacao in ('gerado', 'assinado') order by (k.situacao = 'assinado') desc, k.versao desc limit 1) as contrato
               from agentesia_leads l join agentesia_contatos ct on ct.id = l.id_contato
               left join agentesia_agente_etapas et on et.id = l.id_etapa
               where l.id = $1::uuid""", id_lead)
        if not linha:
            return {}
        from app.cerebro.contexto import texto_do_contrato
        from app.notificacoes import formatar_telefone, fuso
        contrato = linha["contrato"]
        # Como no n8n: assinado diz quando; gerado e não assinado leva o link vigente; sem contrato, vale a etapa.
        situacao = texto_do_contrato(contrato[0], versao=contrato[1], link=contrato[2], gerado_em=contrato[3],
                                     assinado_em=contrato[4]) if contrato is not None else contrato_pela_etapa(linha["etapa"])
        fatos = {"nome no WhatsApp": f"{linha['nome']} (pode não ser o nome completo)" if linha["nome"] else None,
                 "telefone": formatar_telefone(linha["telefone_normalizado"]),
                 "primeiro contato": linha["criado_em"].astimezone(fuso()).strftime("%d/%m/%Y %H:%M"), "contrato": situacao}
        if contrato is None or contrato[0] != "assinado":
            # Última releitura do documento na ZapSign (já assinei, lembrete, consulta, aviso): abriu? travou? cancelado?
            # A linha vem pronta de app/contrato/assinatura.linha_para_ia, para a IA responder sem inventar.
            linha_ia = await self._pool.fetchval(
                """select a.resultado->>'linha_ia' from agentesia_acoes a
                   where a.id_lead = $1::uuid and a.situacao = 'feita' and a.resultado ? 'linha_ia'
                     and a.tipo in ('verificar_assinatura', 'lembrar_assinatura', 'reenviar_link')
                   order by a.atualizado_em desc limit 1""", id_lead)
            if linha_ia:
                fatos["assinatura do contrato (sistema)"] = linha_ia.removeprefix("ASSINATURA DO CONTRATO (sistema) ")
        origem = linha["origem"] if isinstance(linha["origem"], dict) else json.loads(linha["origem"] or "{}")
        if origem.get("origem") == "anuncio":
            from app.origem import PRODUTOS
            fatos["veio de anúncio"] = " · ".join(x for x in (origem.get("titulo") or origem.get("campanha"),
                                                              PRODUTOS.get(origem.get("produto", "")) if origem.get("produto") not in (None, "nao_sei") else None) if x)
        return fatos

    async def marcar_resposta(self, id_lead, quando) -> None:
        await self._pool.execute("update agentesia_leads set responder_apos = $2 where id = $1::uuid", id_lead, quando)

    async def reservar_lead(self, id_lead, segundos) -> bool:
        linha = await self._pool.fetchrow(
            """update agentesia_leads set processando_ate = now() + make_interval(secs => $2)
               where id = $1::uuid and (processando_ate is null or processando_ate < now()) returning id""", id_lead, float(segundos))
        return linha is not None

    async def renovar_reserva(self, id_lead, segundos) -> None:
        """Estende a reserva de quem já reservou (o envio com pausas de digitação não deixa ela vencer no meio)."""
        await self._pool.execute(
            "update agentesia_leads set processando_ate = now() + make_interval(secs => $2) where id = $1::uuid",
            id_lead, float(segundos))

    async def responder_apos(self, id_lead):
        return await self._pool.fetchval("select responder_apos from agentesia_leads where id = $1::uuid", id_lead)

    async def fechar_turnos_interrompidos(self, minutos=10) -> list[dict]:
        """Turnos 'processando' há mais de `minutos` (o processo caiu no meio): viram 'erro'. O returning garante que
        só um servidor fecha (e avisa) cada turno."""
        linhas = await self._pool.fetch(
            """update agentesia_turnos set situacao = 'erro', motivo = 'turno_interrompido', concluido_em = now()
               where situacao = 'processando' and concluido_em is null
                 and iniciado_em < now() - make_interval(mins => $1)
               returning id, id_escritorio, id_lead""", int(minutos))
        return [{"id_turno": str(l["id"]), "id_escritorio": str(l["id_escritorio"]), "id_lead": _texto(l["id_lead"])}
                for l in linhas]

    async def liberar_lead(self, id_lead) -> None:
        await self._pool.execute("update agentesia_leads set processando_ate = null where id = $1::uuid", id_lead)

    async def leads_aguardando(self, limite=200):
        linhas = await self._pool.fetch(
            """select id, responder_apos from agentesia_leads
               where responder_apos is not null and (processando_ate is null or processando_ate < now())
               order by responder_apos limit $1""", limite)
        return [(str(r["id"]), r["responder_apos"]) for r in linhas]

    async def religar_pausas_vencidas(self, id_lead=None) -> list[str]:
        """Desativação da IA com prazo (30 min, 2 h, 24 h) que acabou: religa, tira a etiqueta e deixa nota."""
        from app import ia_controle
        return await ia_controle.religar_vencidas(self._pool, id_lead)

    async def agendar_followup(self, id_lead, base) -> None:
        from app.followup import servico
        await servico.agendar(self._pool, id_lead, base)

    async def cancelar_followups(self, id_lead, motivo) -> None:
        from app.followup import servico
        await servico.cancelar(self._pool, id_lead, motivo)

    async def eventos_com_aviso(self, id_escritorio) -> set[str]:
        linhas = await self._pool.fetch(
            "select tipo_evento from agentesia_notificacoes where id_escritorio = $1::uuid and habilitada", id_escritorio)
        return {r["tipo_evento"] for r in linhas}

    async def atualizar_texto_extraido(self, id_mensagem, texto) -> None:
        if self._midia_pendente:                     # leitura terminou: tira a marca de mídia pendente junto
            await self._pool.execute(
                "update agentesia_mensagens set texto_extraido = $2, midia_pendente_desde = null where id = $1::uuid",
                id_mensagem, texto)
            return
        await self._pool.execute("update agentesia_mensagens set texto_extraido = $2 where id = $1::uuid", id_mensagem, texto)

    async def marcar_midia_pendente(self, id_mensagem) -> None:
        if self._midia_pendente:
            await self._pool.execute(
                "update agentesia_mensagens set midia_pendente_desde = now() where id = $1::uuid", id_mensagem)

    async def limpar_midia_pendente(self, id_mensagem) -> None:
        if self._midia_pendente:
            await self._pool.execute(
                "update agentesia_mensagens set midia_pendente_desde = null where id = $1::uuid", id_mensagem)

    async def nota_de_problema(self, *, id_escritorio, id_lead, tipo, texto) -> bool:
        """Nota no chat do lead sobre um problema: no máximo 1 a cada 6 h por conversa e tipo (o evento grava sempre)."""
        from app.notificacoes import fuso

        prefixo = f"{id_lead}:problema:{tipo}:"
        async with self._pool.acquire() as conexao, conexao.transaction():
            await conexao.execute("select pg_advisory_xact_lock(hashtext($1))", prefixo)    # duas mensagens juntas = uma nota
            linha = await conexao.fetchrow(
                """select min(criado_em) as primeira, max(criado_em) as ultima, count(*) as notas from agentesia_acoes
                   where id_lead = $1::uuid and tipo = 'nota' and left(chave_unica, length($2)) = $2""", id_lead, prefixo)
            if linha["ultima"] and linha["ultima"] > datetime.now(timezone.utc) - timedelta(hours=6):
                return False
            if linha["primeira"]:
                ocorrencias = await conexao.fetchval(
                    "select count(*) from agentesia_eventos where id_lead = $1::uuid and tipo = $2 and criado_em >= $3",
                    id_lead, tipo, linha["primeira"])
                texto += (f"\n\nPrimeiro aviso deste problema: {linha['primeira'].astimezone(fuso()):%d/%m %H:%M}. "
                          f"Ocorrências desde então: {ocorrencias}")
            await conexao.execute(
                """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
                   values ($1::uuid, $2::uuid, 'nota', $3, $4::jsonb) on conflict (chave_unica) do nothing""",
                id_escritorio, id_lead, prefixo + str(linha["notas"] + 1), json.dumps({"texto": texto}, ensure_ascii=False))
        return True

    async def documentos_do_agente(self, id_agente) -> list[tuple[str, str]]:
        """Só os ainda sem índice (processando/erro): entram pela busca por palavras até o vetor ficar pronto."""
        linhas = await self._pool.fetch(
            """select d.nome, d.texto from agentesia_documentos d
               join agentesia_agentes a on a.id = d.id_agente and a.id_escritorio = d.id_escritorio   -- nunca de outro escritório
               where d.id_agente = $1::uuid and d.ativo and d.situacao <> 'pronto'
                 and d.tipo in ('arquivo', 'texto')             -- FAQ/objeções (virtuais) vêm da config do agente
               order by d.criado_em""", id_agente)
        return [(l["nome"], l["texto"]) for l in linhas]

    async def trechos_do_agente(self, id_agente) -> list[dict]:
        from app.conhecimento_indice import trechos_do_agente
        return await trechos_do_agente(self._pool, id_agente)

    async def registrar_lacuna(self, *, id_escritorio, id_agente, papel, pergunta, id_lead=None, id_turno=None) -> dict | None:
        from app.conhecimento_indice import registrar_lacuna
        return await registrar_lacuna(self._pool, id_escritorio=id_escritorio, id_agente=id_agente, papel=papel,
                                      pergunta=pergunta, id_lead=id_lead, id_turno=id_turno)

    async def reindexar_base(self, id_agente, modelo, dimensoes) -> int:
        from app.conhecimento_indice import marcar_para_reindexar
        return await marcar_para_reindexar(self._pool, id_agente, modelo, dimensoes)

    async def gravar_origem(self, id_lead, origem) -> bool:
        """Só o primeiro toque: não troca a origem de quem já tem."""
        return await self._pool.fetchval(
            """update agentesia_leads set origem = $2::jsonb where id = $1::uuid and origem = '{}'::jsonb returning true""",
            id_lead, json.dumps(origem, ensure_ascii=False)) is True

    async def gasto_desde(self, id_escritorio, desde) -> float:
        return float(await self._pool.fetchval(
            "select coalesce(sum(custo_usd), 0) from agentesia_chamadas_ia where id_escritorio = $1::uuid and criado_em >= $2",
            id_escritorio, desde) or 0)

    async def gravar_chamadas(self, *, id_escritorio, id_turno, chamadas: list[Chamada], id_lead=None) -> None:
        """Ponto único (app.cobranca.gravar_chamadas): tokens, US$ e, pela 007, o R$ com cotação e markup."""
        from app import cobranca
        await cobranca.gravar_chamadas(self._pool, id_escritorio=id_escritorio, chamadas=chamadas, id_turno=id_turno,
                                       id_lead=id_lead)

    async def bloqueado_por_saldo(self, id_escritorio) -> bool:
        """'Pode gastar?' do escritório (pré-pago sem saldo = bloqueado). Sem a 007, nunca bloqueia."""
        from app import cobranca
        return await cobranca.bloqueado(self._pool, id_escritorio)

    async def gravar_eventos(self, *, id_escritorio, id_lead, id_turno, eventos) -> None:
        if not eventos:
            return
        await self._pool.executemany(
            """insert into agentesia_eventos (id_escritorio, id_lead, id_turno, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8::jsonb)""",
            [(id_escritorio, id_lead, id_turno, e["tipo"], e.get("gravidade", "aviso"), e.get("responsavel"),
              e.get("descricao"), json.dumps(e.get("detalhe") or {}, ensure_ascii=False, default=str)) for e in eventos])

    async def config_crm(self, id_escritorio):
        valor = await self._pool.fetchval(
            """select config from agentesia_integracoes
               where id_escritorio = $1::uuid and tipo = 'crm' and situacao = 'ok'""", id_escritorio)
        return _json(valor) if valor is not None else None

    async def config_zapsign(self, id_escritorio):
        """Config da integração ZapSign (modelos de contrato com os campos obrigatórios); sem o token."""
        valor = await self._pool.fetchval(
            "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign'", id_escritorio)
        return _json(valor) if valor is not None else {}

    async def enfileirar_acoes(self, *, id_escritorio, id_lead, id_turno, acoes) -> None:
        if not acoes:
            return
        await self._pool.executemany(
            """insert into agentesia_acoes (id_escritorio, id_lead, id_turno, tipo, chave_unica, dados, proxima_em)
               values ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6::jsonb, now() + make_interval(secs => $7))
               on conflict (chave_unica) do nothing""",
            [(id_escritorio, id_lead, id_turno, a["tipo"], a["chave_unica"],
              json.dumps(a["dados"], ensure_ascii=False), float(a.get("atraso_s") or 0)) for a in acoes])

    async def segredo(self, id_segredo):
        if not id_segredo:
            return None
        return await self._pool.fetchval(
            "select decrypted_secret from vault.decrypted_secrets where id = $1::uuid", id_segredo)
