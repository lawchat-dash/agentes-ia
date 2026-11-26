"""Consultas do painel de gestão, nas tabelas agentesia_*. Sempre com parâmetros."""

from __future__ import annotations

import json
import re
from typing import Any

import asyncpg



def _linha(registro: asyncpg.Record | None) -> dict[str, Any] | None:
    if registro is None:
        return None
    saida = {}
    for chave, valor in dict(registro).items():
        if isinstance(valor, str) and chave in ("config", "detalhe", "antes", "depois", "valor", "contexto",
                                                "resposta", "origem", "payload", "limite_consumo", "onboarding",
                                                "conta_helena", "sync_helena", "criar_agente"):
            try:
                valor = json.loads(valor)
            except json.JSONDecodeError:
                pass
        saida[chave] = str(valor) if valor.__class__.__name__ == "UUID" else valor
    return saida


def _linhas(registros: list[asyncpg.Record]) -> list[dict[str, Any]]:
    return [_linha(r) for r in registros]  # type: ignore[misc]


def _j(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


# Quem fez o pedido é lido a cada requisição do painel (rotas.contexto). Uma tela abre 5 a 10 pedidos de uma vez:
# guardar o usuário por alguns segundos poupa uma ida ao banco por pedido. Toda alteração de usuário feita por este
# repositório apaga a cópia na hora; o que mudar por fora (SQL manual) vale em até USUARIO_TTL_S.
USUARIO_TTL_S = 30.0


class RepositorioGestao:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool
        self._usuarios: dict[str, tuple[float, dict[str, Any] | None]] = {}

    def esquecer_usuario(self, id_usuario: str | None = None) -> None:
        """Apaga a cópia do usuário (ou de todos) guardada por usuario()."""
        if id_usuario is None:
            self._usuarios.clear()
        else:
            self._usuarios.pop(str(id_usuario), None)

    # ------------------------------------------------------------------ cofre
    async def guardar_segredo(self, nome: str, valor: str, id_existente: str | None) -> str:
        if id_existente:
            await self.pool.execute("select vault.update_secret($1::uuid, $2)", id_existente, valor)
            return id_existente
        return str(await self.pool.fetchval("select vault.create_secret($1, $2)", valor, nome))

    async def ler_segredo(self, id_segredo: str | None) -> str | None:
        if not id_segredo:
            return None
        return await self.pool.fetchval(
            "select decrypted_secret from vault.decrypted_secrets where id = $1::uuid", id_segredo)

    # ------------------------------------------------------------------ usuários
    async def usuario_por_email(self, email: str) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow("select * from agentesia_usuarios where email = $1", email.lower()))

    async def usuario(self, id_usuario: str) -> dict[str, Any] | None:
        import time
        agora = time.monotonic()
        guardado = self._usuarios.get(str(id_usuario))
        if guardado and agora - guardado[0] < USUARIO_TTL_S:
            return dict(guardado[1]) if guardado[1] else None
        linha = _linha(await self.pool.fetchrow(
            """select u.*, e.nome as nome_escritorio from agentesia_usuarios u
               left join agentesia_escritorios e on e.id = u.id_escritorio where u.id = $1::uuid""", id_usuario))
        if len(self._usuarios) > 2000:
            self._usuarios.clear()
        self._usuarios[str(id_usuario)] = (agora, linha)
        return dict(linha) if linha else None

    async def criar_usuario(self, *, email: str, nome: str, senha_hash: str, papel: str,
                            id_escritorio: str | None) -> dict[str, Any]:
        return _linha(await self.pool.fetchrow(
            """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio)
               values ($1, $2, $3, $4, $5::uuid) returning id, email, nome, papel, id_escritorio, ativo""",
            email.lower(), nome, senha_hash, papel, id_escritorio))  # type: ignore[return-value]

    async def escritorio_por_conta_helena(self, id_conta: str) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow(
            "select * from agentesia_escritorios where id_conta_helena = $1::uuid", id_conta))

    async def usuario_da_helena(self, id_escritorio: str, id_usuario_helena: str) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow(
            "select * from agentesia_usuarios where id_escritorio = $1::uuid and id_usuario_helena = $2",
            id_escritorio, id_usuario_helena))

    async def criar_usuario_da_helena(self, *, id_escritorio: str, id_usuario_helena: str, email: str,
                                      nome: str, papel: str, senha_hash: str) -> dict[str, Any]:
        return _linha(await self.pool.fetchrow(
            """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, id_usuario_helena, trocar_senha)
               values ($1, $2, $3, $4, $5::uuid, $6, false) returning *""",
            email.lower(), nome, senha_hash, papel, id_escritorio, id_usuario_helena))  # type: ignore[return-value]

    async def vincular_usuario_helena(self, id_usuario: str, id_usuario_helena: str, nome: str) -> None:
        self.esquecer_usuario(id_usuario)
        await self.pool.execute(
            "update agentesia_usuarios set id_usuario_helena = $2, nome = $3 where id = $1::uuid",
            id_usuario, id_usuario_helena, nome)

    async def usuarios_do_escritorio(self, id_escritorio: str) -> list[dict[str, Any]]:
        return _linhas(await self.pool.fetch(
            """select id, email, nome, papel, ativo, ultimo_acesso_em, criado_em from agentesia_usuarios
               where id_escritorio = $1::uuid order by nome""", id_escritorio))

    async def registrar_acesso(self, id_usuario: str) -> None:
        await self.pool.execute("update agentesia_usuarios set ultimo_acesso_em = now() where id = $1::uuid", id_usuario)

    async def trocar_senha(self, id_usuario: str, senha_hash: str) -> None:
        self.esquecer_usuario(id_usuario)
        await self.pool.execute(
            "update agentesia_usuarios set senha_hash = $2, trocar_senha = false where id = $1::uuid",
            id_usuario, senha_hash)

    async def alterar_usuario(self, id_usuario: str, id_escritorio: str, *, ativo: bool | None = None,
                              papel: str | None = None) -> None:
        self.esquecer_usuario(id_usuario)
        await self.pool.execute(
            """update agentesia_usuarios set ativo = coalesce($3, ativo), papel = coalesce($4, papel)
               where id = $1::uuid and id_escritorio = $2::uuid""", id_usuario, id_escritorio, ativo, papel)

    # ------------------------------------------------------------------ equipe LawChat
    async def equipe_lawchat(self) -> list[dict[str, Any]]:
        return _linhas(await self.pool.fetch(
            """select u.id, u.email, u.nome, u.papel, u.ativo, u.trocar_senha, u.ultimo_acesso_em, u.criado_em,
                      (select count(*) from agentesia_escritorios e where e.id_responsavel = u.id) as escritorios
               from agentesia_usuarios u where u.id_escritorio is null
               order by u.ativo desc, (u.papel = 'dono_lawchat') desc, u.nome"""))

    async def membro_lawchat(self, id_usuario: str) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow(
            "select * from agentesia_usuarios where id = $1::uuid and id_escritorio is null", id_usuario))

    async def donos_ativos(self) -> int:
        return await self.pool.fetchval(
            "select count(*) from agentesia_usuarios where papel = 'dono_lawchat' and ativo")

    async def alterar_membro_lawchat(self, id_usuario: str, *, nome: str | None = None, papel: str | None = None,
                                     ativo: bool | None = None) -> dict[str, Any] | None:
        self.esquecer_usuario(id_usuario)
        return _linha(await self.pool.fetchrow(
            """update agentesia_usuarios set nome = coalesce($2, nome), papel = coalesce($3, papel),
                      ativo = coalesce($4, ativo), atualizado_em = now()
               where id = $1::uuid and id_escritorio is null
               returning id, email, nome, papel, ativo""", id_usuario, nome, papel, ativo))

    async def redefinir_senha(self, id_usuario: str, senha_hash: str) -> None:
        self.esquecer_usuario(id_usuario)
        await self.pool.execute(
            "update agentesia_usuarios set senha_hash = $2, trocar_senha = true where id = $1::uuid",
            id_usuario, senha_hash)

    async def definir_responsavel(self, id_escritorio: str, id_usuario: str | None) -> None:
        await self.pool.execute(
            "update agentesia_escritorios set id_responsavel = $2::uuid where id = $1::uuid", id_escritorio, id_usuario)

    # ------------------------------------------------------------------ escritórios
    async def escritorios(self) -> list[dict[str, Any]]:
        return _linhas(await self.pool.fetch(
            """select e.id, e.nome, e.situacao, e.ia_desligada, e.id_conta_helena, e.criado_em, e.id_responsavel,
                      (select r.nome from agentesia_usuarios r where r.id = e.id_responsavel) as responsavel,
                      (select count(*) from agentesia_agentes a where a.id_escritorio = e.id) as agentes,
                      (select count(*) from agentesia_agentes a where a.id_escritorio = e.id and a.situacao = 'ativo') as agentes_ativos,
                      (select count(*) from agentesia_eventos v where v.id_escritorio = e.id and v.resolvido_em is null
                         and v.gravidade in ('erro', 'critico') and v.criado_em > now() - interval '7 days') as erros_abertos,
                      (select situacao from agentesia_integracoes i where i.id_escritorio = e.id and i.tipo = 'helena') as helena,
                      (select coalesce(sum(c.custo_usd), 0)::float8 from agentesia_chamadas_ia c where c.id_escritorio = e.id
                         and c.criado_em >= date_trunc('month', now() at time zone 'America/Sao_Paulo') at time zone 'America/Sao_Paulo') as gasto_mes_usd,
                      e.config -> 'limite_consumo' as limite_consumo,
                      to_jsonb(e) -> 'onboarding' as onboarding, to_jsonb(e) ->> 'sincronizado_em' as sincronizado_em,
                      to_jsonb(e) -> 'dados_helena' -> 'conta' as conta_helena,
                      to_jsonb(e) -> 'dados_helena' -> 'sync' as sync_helena,
                      e.config -> 'criar_agente' as criar_agente
               from agentesia_escritorios e order by e.nome"""))

    async def documentos(self, id_agente: str) -> list[dict[str, Any]]:
        return _linhas(await self.pool.fetch(
            """select id, nome, tipo, formato, tamanho_bytes, caracteres, ativo, situacao, erro, tokens, origem, travado,
                      criado_em, criado_em as created_at, left(texto, 300) as previa
               from agentesia_documentos where id_agente = $1::uuid and ativo order by travado desc, ordem, criado_em desc""", id_agente))

    async def criar_documento(self, *, id_escritorio: str, id_agente: str, nome: str, formato: str, tamanho_bytes: int,
                              texto: str, criado_por: str | None, tipo: str = "arquivo") -> dict[str, Any]:
        return _linha(await self.pool.fetchrow(
            """insert into agentesia_documentos (id_escritorio, id_agente, tipo, nome, formato, tamanho_bytes, texto, caracteres, criado_por)
               values ($1::uuid, $2::uuid, $8, $3, $4, $5, $6, length($6), $7::uuid)
               returning id, nome, tipo, formato, tamanho_bytes, caracteres, ativo, situacao, tokens, origem, travado,
                         criado_em, criado_em as created_at""",
            id_escritorio, id_agente, nome, formato, tamanho_bytes, texto, criado_por, tipo))  # type: ignore[return-value]

    async def apagar_documento(self, id_agente: str, id_documento: str) -> str | None:
        return await self.pool.fetchval(
            "delete from agentesia_documentos where id = $1::uuid and id_agente = $2::uuid and not travado returning nome",
            id_documento, id_agente)

    async def consumo_do_mes(self, id_escritorio: str, desde: Any) -> dict[str, Any]:
        import asyncio
        # As duas leituras são independentes: em paralelo (uma ida ao banco de espera em vez de duas).
        dia, papel = await asyncio.gather(self.pool.fetch(
            """select to_char(criado_em at time zone 'America/Sao_Paulo', 'YYYY-MM-DD') as dia, sum(custo_usd)::float8 as custo_usd,
                      count(*) as chamadas
               from agentesia_chamadas_ia where id_escritorio = $1::uuid and criado_em >= $2 group by 1 order by 1""",
            id_escritorio, desde), self.pool.fetch(
            """select papel, sum(custo_usd)::float8 as custo_usd, count(*) as chamadas,
                      sum(tokens_entrada)::bigint as tokens_entrada, sum(tokens_saida)::bigint as tokens_saida
               from agentesia_chamadas_ia where id_escritorio = $1::uuid and criado_em >= $2 group by 1 order by 2 desc""",
            id_escritorio, desde))
        por_dia, por_papel = _linhas(dia), _linhas(papel)
        return {"por_dia": por_dia, "por_papel": por_papel, "gasto_usd": sum(d["custo_usd"] or 0 for d in por_dia)}

    async def salvar_limite_consumo(self, id_escritorio: str, limite: dict[str, Any]) -> None:
        await self.pool.execute(
            "update agentesia_escritorios set config = jsonb_set(coalesce(config, '{}'::jsonb), '{limite_consumo}', $2::jsonb) where id = $1::uuid",
            id_escritorio, json.dumps(limite))

    async def escritorio(self, id_escritorio: str) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow("select * from agentesia_escritorios where id = $1::uuid", id_escritorio))

    async def criar_escritorio(self, nome: str, id_conta_helena: str | None) -> dict[str, Any]:
        return _linha(await self.pool.fetchrow(
            "insert into agentesia_escritorios (nome, id_conta_helena) values ($1, $2::uuid) returning *",
            nome, id_conta_helena))  # type: ignore[return-value]

    async def alterar_escritorio(self, id_escritorio: str, campos: dict[str, Any]) -> dict[str, Any] | None:
        permitidos = {"nome", "situacao", "ia_desligada", "config", "id_conta_helena"}
        campos = {k: v for k, v in campos.items() if k in permitidos}
        if not campos:
            return await self.escritorio(id_escritorio)
        nomes = list(campos)
        tipos = {"config": "::jsonb", "id_conta_helena": "::uuid"}
        sql = ", ".join(f"{n} = ${i + 2}{tipos.get(n, '')}" for i, n in enumerate(nomes))
        valores = [_j(campos[n]) if n == "config" else campos[n] for n in nomes]
        return _linha(await self.pool.fetchrow(
            f"update agentesia_escritorios set {sql} where id = $1::uuid returning *", id_escritorio, *valores))

    # ------------------------------------------------------------------ integrações
    async def integracoes(self, id_escritorio: str) -> dict[str, dict[str, Any]]:
        linhas = await self.pool.fetch(
            """select tipo, situacao, final_segredo, config, erro, testado_em, atualizado_em,
                      id_segredo_vault is not null as tem_segredo
               from agentesia_integracoes where id_escritorio = $1::uuid""", id_escritorio)
        return {l["tipo"]: _linha(l) for l in linhas}  # type: ignore[misc]

    async def integracao(self, id_escritorio: str, tipo: str) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow(
            "select * from agentesia_integracoes where id_escritorio = $1::uuid and tipo = $2", id_escritorio, tipo))

    async def salvar_integracao(self, id_escritorio: str, tipo: str, **campos: Any) -> dict[str, Any]:
        atual = await self.integracao(id_escritorio, tipo)
        # No update, a mistura é feita no banco (config atual || o que mudou): um salvamento de token
        # não apaga a lista de modelos que outro pedido gravou no meio tempo.
        mudou = campos.pop("config", {})
        config = {**(atual or {}).get("config", {}), **mudou}
        dados = {
            "id_segredo_vault": campos.get("id_segredo_vault", (atual or {}).get("id_segredo_vault")),
            "final_segredo": campos.get("final_segredo", (atual or {}).get("final_segredo")),
            "situacao": campos.get("situacao", (atual or {}).get("situacao", "pendente")),
            "erro": campos.get("erro"),
        }
        return _linha(await self.pool.fetchrow(
            """insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, final_segredo, config, situacao, erro, testado_em)
               values ($1::uuid, $2, $3::uuid, $4, $5::jsonb, $6, $7, case when $6 in ('ok', 'erro') then now() end)
               on conflict (id_escritorio, tipo) do update set
                 id_segredo_vault = excluded.id_segredo_vault, final_segredo = excluded.final_segredo,
                 config = coalesce(agentesia_integracoes.config, '{}'::jsonb) || $8::jsonb, situacao = excluded.situacao, erro = excluded.erro,
                 testado_em = coalesce(excluded.testado_em, agentesia_integracoes.testado_em)
               returning *""",
            id_escritorio, tipo, dados["id_segredo_vault"], dados["final_segredo"], _j(config),
            dados["situacao"], dados["erro"], _j(mudou)))  # type: ignore[return-value]

    # ------------------------------------------------------------------ canais
    async def sincronizar_canais(self, id_escritorio: str, canais: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Um registro por número (unique id_escritorio + numero_normalizado). A Helena lista também canais sem número
        # (Instagram, Messenger...) e o mesmo número duas vezes (reconectado): sem este filtro o insert estourava
        # UniqueViolation e o "Avançar"/"Sincronizar conta" virava erro 500.
        por_numero: dict[str, dict[str, Any]] = {}
        for canal in canais:
            numero = str(canal.get("numero_normalizado") or "").strip()
            if not canal.get("id") or not numero:
                continue
            atual = por_numero.get(numero)
            if atual is None or (canal.get("ativo") and not atual.get("ativo")):
                por_numero[numero] = {**canal, "numero_normalizado": numero}
        canais = list(por_numero.values())
        async with self.pool.acquire() as conexao, conexao.transaction():
            for canal in canais:
                try:
                    async with conexao.transaction():          # savepoint: um canal ruim não derruba os outros
                        # Mesmo número com outro id de canal (reconectado na Helena): o registro passa para o id novo.
                        await conexao.execute(
                            """update agentesia_canais set id_canal_helena = $3
                               where id_escritorio = $1::uuid and numero_normalizado = $2
                                 and id_canal_helena is distinct from $3
                                 and not exists (select 1 from agentesia_canais o where o.id_canal_helena = $3)""",
                            id_escritorio, canal["numero_normalizado"], canal["id"])
                        await conexao.execute(
                            """insert into agentesia_canais (id_escritorio, id_canal_helena, numero_normalizado, tipo, ativo)
                               values ($1::uuid, $2, $3, $4, $5)
                               on conflict (id_canal_helena) do update set
                                 numero_normalizado = excluded.numero_normalizado, tipo = excluded.tipo, ativo = excluded.ativo
                               where agentesia_canais.id_escritorio = excluded.id_escritorio""",
                            id_escritorio, canal["id"], canal["numero_normalizado"], canal["tipo"], canal["ativo"])
                except asyncpg.UniqueViolationError:
                    continue
            ids = [c["id"] for c in canais]
            await conexao.execute(
                """update agentesia_canais set ativo = false
                   where id_escritorio = $1::uuid and not (id_canal_helena = any($2::text[]))""", id_escritorio, ids)
        return await self.canais(id_escritorio)

    async def canais(self, id_escritorio: str) -> list[dict[str, Any]]:
        return _linhas(await self.pool.fetch(
            """select c.id, c.id_canal_helena, c.numero_normalizado, c.tipo, c.ativo,
                      to_jsonb(c) ->> 'nome_exibicao' as nome_exibicao, to_jsonb(c) ->> 'tipo_helena' as tipo_helena,
                      a.id as id_agente, a.nome as nome_agente
               from agentesia_canais c left join agentesia_agentes a on a.id_canal = c.id
               where c.id_escritorio = $1::uuid order by c.ativo desc, c.numero_normalizado""", id_escritorio))

    # ------------------------------------------------------------------ agentes
    _AGENTE = """select a.*, c.numero_normalizado as numero_canal, c.id_canal_helena, c.tipo as tipo_canal,
                        (select count(*)::int from agentesia_documentos d where d.id_agente = a.id and d.ativo) as documentos
                 from agentesia_agentes a join agentesia_canais c on c.id = a.id_canal"""

    async def agentes(self, id_escritorio: str) -> list[dict[str, Any]]:
        return _linhas(await self.pool.fetch(
            self._AGENTE + """ where a.id_escritorio = $1::uuid order by a.criado_em""", id_escritorio))

    async def agente(self, id_escritorio: str, id_agente: str) -> dict[str, Any] | None:
        import asyncio
        # O agente e as etapas em paralelo (uma espera pelo banco em vez de duas); as etapas só valem se o agente for
        # deste escritório.
        linha, etapas = await asyncio.gather(
            self.pool.fetchrow(self._AGENTE + " where a.id = $1::uuid and a.id_escritorio = $2::uuid", id_agente, id_escritorio),
            self.pool.fetch(
                """select id, codigo, ordem, tipo, principal, instrucao, instrucao_travada, modelo, temperatura
                   from agentesia_agente_etapas where id_agente = $1::uuid order by ordem""", id_agente))
        agente = _linha(linha)
        if agente:
            agente["etapas"] = _linhas(etapas)
        return agente

    async def criar_agente(self, *, id_escritorio: str, id_canal: str, nome: str, produto: str,
                           config: dict[str, Any], etapas: list[tuple[str, str]]) -> dict[str, Any]:
        """etapas: [(codigo, tipo)] na ordem; a primeira é onde o lead novo entra."""
        async with self.pool.acquire() as conexao, conexao.transaction():
            id_agente = await conexao.fetchval(
                """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config)
                   values ($1::uuid, $2::uuid, $3, $4, $5::jsonb) returning id""",
                id_escritorio, id_canal, nome, produto, _j(config))
            for ordem, (codigo, tipo) in enumerate(etapas, start=1):
                await conexao.execute(
                    """insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal)
                       values ($1, $2, $3, $4, $5)""", id_agente, codigo, ordem, tipo, ordem == 1)
        return await self.agente(id_escritorio, str(id_agente))  # type: ignore[return-value]

    async def sincronizar_etapas(self, id_agente: str, etapas: list[tuple[str, str]]) -> list[str]:
        """Deixa as etapas do agente iguais à definição. Não apaga etapa com lead: devolve as que impediram."""
        codigos = [c for c, _ in etapas]
        async with self.pool.acquire() as conexao, conexao.transaction():
            em_uso = [r["codigo"] for r in await conexao.fetch(
                """select distinct e.codigo from agentesia_agente_etapas e
                   join agentesia_leads l on l.id_etapa = e.id
                   where e.id_agente = $1::uuid and not (e.codigo = any($2::text[]))""", id_agente, codigos)]
            if em_uso:
                return em_uso
            await conexao.execute(
                "delete from agentesia_agente_etapas where id_agente = $1::uuid and not (codigo = any($2::text[]))",
                id_agente, codigos)
            await conexao.execute("update agentesia_agente_etapas set principal = false where id_agente = $1::uuid", id_agente)
            for ordem, (codigo, tipo) in enumerate(etapas, start=1):
                await conexao.execute(
                    """insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal)
                       values ($1::uuid, $2, $3, $4, $5)
                       on conflict (id_agente, codigo) do update set ordem = excluded.ordem, tipo = excluded.tipo,
                         principal = excluded.principal""", id_agente, codigo, ordem, tipo, ordem == 1)
        return []

    async def alterar_agente(self, id_escritorio: str, id_agente: str, campos: dict[str, Any]) -> None:
        permitidos = {"nome", "situacao", "modo", "minutos_pausa_humano", "config", "numeros_teste", "id_canal"}
        campos = {k: v for k, v in campos.items() if k in permitidos}
        if not campos:
            return
        nomes = list(campos)
        tipos = {"config": "::jsonb", "numeros_teste": "::text[]", "id_canal": "::uuid"}
        sql = ", ".join(f"{n} = ${i + 3}{tipos.get(n, '')}" for i, n in enumerate(nomes))
        valores = [_j(campos[n]) if n == "config" else campos[n] for n in nomes]
        await self.pool.execute(
            f"update agentesia_agentes set {sql} where id = $1::uuid and id_escritorio = $2::uuid",
            id_agente, id_escritorio, *valores)

    async def alterar_etapa(self, id_agente: str, codigo: str, *, instrucao: str | None,
                            travada: bool | None) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow(
            """update agentesia_agente_etapas
               set instrucao = $3, instrucao_travada = coalesce($4, instrucao_travada)
               where id_agente = $1::uuid and codigo = $2
               returning id, codigo, instrucao, instrucao_travada""", id_agente, codigo, instrucao, travada))

    async def aplicar_instrucoes(self, id_agente: str, instrucoes: dict[str, str]) -> None:
        """Instruções personalizadas por etapa, vindas de um modelo da biblioteca."""
        for codigo, texto in instrucoes.items():
            if texto and texto.strip():
                await self.pool.execute(
                    "update agentesia_agente_etapas set instrucao = $3 where id_agente = $1::uuid and codigo = $2",
                    id_agente, codigo, texto.strip())

    async def marcar_modelo(self, id_agente: str, id_modelo: str) -> None:
        await self.pool.execute("update agentesia_agentes set id_modelo = $2::uuid where id = $1::uuid", id_agente, id_modelo)

    # ------------------------------------------------------------------ biblioteca de modelos
    async def modelos(self, *, so_publicados: bool) -> list[dict[str, Any]]:
        return _linhas(await self.pool.fetch(
            """select m.*, (select count(*) from agentesia_agentes a where a.id_modelo = m.id) as agentes
               from agentesia_modelos_agente m
               where (not $1 or m.situacao = 'publicado')
               order by m.situacao = 'publicado' desc, m.nome""", so_publicados))

    async def modelo(self, id_modelo: str) -> dict[str, Any] | None:
        return _linha(await self.pool.fetchrow("select * from agentesia_modelos_agente where id = $1::uuid", id_modelo))

    async def salvar_modelo(self, id_modelo: str | None, *, nome: str, descricao: str, produto: str,
                            config: dict[str, Any], situacao: str, id_usuario: str) -> dict[str, Any]:
        if id_modelo:
            return _linha(await self.pool.fetchrow(
                """update agentesia_modelos_agente set nome = $2, descricao = $3, produto = $4, config = $5::jsonb, situacao = $6
                   where id = $1::uuid returning *""", id_modelo, nome, descricao, produto, _j(config), situacao))  # type: ignore[return-value]
        return _linha(await self.pool.fetchrow(
            """insert into agentesia_modelos_agente (nome, descricao, produto, config, situacao, criado_por)
               values ($1, $2, $3, $4::jsonb, $5, $6::uuid) returning *""",
            nome, descricao, produto, _j(config), situacao, id_usuario))  # type: ignore[return-value]

    # ------------------------------------------------------------------ acompanhamento
    async def resumo(self, id_escritorio: str) -> dict[str, Any]:
        import asyncio
        # Os totais e a contagem por etapa são independentes: em paralelo (uma espera pelo banco em vez de duas).
        linha, por_etapa = await asyncio.gather(self.pool.fetchrow(
            """select
                 (select count(*) from agentesia_leads where id_escritorio = $1::uuid) as leads,
                 (select count(*) from agentesia_leads where id_escritorio = $1::uuid
                    and criado_em >= date_trunc('day', now() at time zone 'America/Sao_Paulo') at time zone 'America/Sao_Paulo') as leads_hoje,
                 (select count(*) from agentesia_mensagens where id_escritorio = $1::uuid and autor = 'ia'
                    and registrada_em > now() - interval '24 hours') as respostas_24h,
                 (select count(*) from agentesia_turnos where id_escritorio = $1::uuid and situacao = 'erro'
                    and iniciado_em > now() - interval '24 hours') as turnos_com_erro_24h,
                 (select count(*) from agentesia_eventos where id_escritorio = $1::uuid and resolvido_em is null
                    and gravidade in ('erro', 'critico')) as erros_abertos,
                 (select coalesce(sum(custo_usd), 0) from agentesia_chamadas_ia where id_escritorio = $1::uuid
                    and criado_em > now() - interval '24 hours') as custo_24h_usd,
                 (select max(recebido_em) from agentesia_eventos_recebidos where id_escritorio = $1::uuid) as ultimo_webhook""",
            id_escritorio), self.pool.fetch(
            """select coalesce(e.codigo, '-') as etapa, l.estado, count(*) as leads
               from agentesia_leads l left join agentesia_agente_etapas e on e.id = l.id_etapa
               where l.id_escritorio = $1::uuid group by 1, 2 order by 1""", id_escritorio))
        resumo = _linha(linha) or {}
        resumo["custo_24h_usd"] = float(resumo.get("custo_24h_usd") or 0)
        resumo["por_etapa"] = _linhas(por_etapa)
        return resumo

    DESVIOS = ("desqualificado", "analise_manual")      # etapas fora do caminho principal do funil

    async def funil(self, id_agente: str, dias: int) -> dict[str, Any]:
        """Leads que chegaram ao agente no período e até onde cada um já foi (a etapa mais adiante que alcançou)."""
        from datetime import timedelta
        desde = timedelta(days=int(dias))
        import asyncio
        # As três leituras (etapas, totais e origens) são independentes: em paralelo.
        etapas, totais, origens = await asyncio.gather(self.pool.fetch(
            """with et as (select id, codigo, ordem from agentesia_agente_etapas where id_agente = $1::uuid and not (codigo = any($3::text[]))),
                    ld as (select id, id_etapa from agentesia_leads where id_agente = $1::uuid and criado_em >= now() - $2::interval),
                    alcance as (
                      select ld.id, greatest(
                        coalesce((select et.ordem from et where et.id = ld.id_etapa), -1),
                        coalesce((select max(et.ordem) from agentesia_turnos t join et on et.codigo = t.etapa_depois
                                   where t.id_lead = ld.id), -1)) as maxima
                      from ld)
               select et.codigo, et.ordem, (select count(*)::int from alcance a where a.maxima >= et.ordem) as leads
               from et order by et.ordem""", id_agente, desde, list(self.DESVIOS)), self.pool.fetchrow(
            """select count(*)::int as leads,
                      count(*) filter (where e.codigo = 'desqualificado')::int as desqualificados,
                      count(*) filter (where e.codigo = 'analise_manual')::int as analise_manual,
                      count(*) filter (where l.estado = 'pausado')::int as pausados,
                      count(*) filter (where exists (select 1 from agentesia_contratos k where k.id_lead = l.id and k.situacao = 'assinado'))::int as assinados
               from agentesia_leads l left join agentesia_agente_etapas e on e.id = l.id_etapa
               where l.id_agente = $1::uuid and l.criado_em >= now() - $2::interval""", id_agente, desde), self.pool.fetch(
            """select coalesce(nullif(l.origem->>'campanha', ''),
                               case when l.origem->>'origem' = 'anuncio' then 'Anúncio (sem campanha)'
                                    when l.origem->>'origem' = 'utm' then 'UTM (sem campanha)' else 'Direto' end) as origem,
                      count(*)::int as leads,
                      count(*) filter (where exists (select 1 from agentesia_contratos k where k.id_lead = l.id and k.situacao = 'assinado'))::int as assinados
               from agentesia_leads l where l.id_agente = $1::uuid and l.criado_em >= now() - $2::interval
               group by 1 order by 2 desc limit 12""", id_agente, desde))
        return {"etapas": _linhas(etapas), "totais": _linha(totais) or {}, "origens": _linhas(origens)}

    async def eventos(self, id_escritorio: str | None, *, abertos: bool, limite: int = 200) -> list[dict[str, Any]]:
        # O mesmo erro do mesmo lead (ex.: o turno tentou de novo e falhou outra vez) aparece UMA vez, com "repeticoes";
        # sem isso, resolver um deixava o gêmeo na lista e parecia que "voltou".
        return _linhas(await self.pool.fetch(
            """select * from (
                 select v.id, v.id_escritorio, e.nome as escritorio, v.id_lead, v.id_turno, v.tipo, v.gravidade,
                        v.responsavel, v.descricao, v.detalhe, v.criado_em, v.resolvido_em,
                        count(*) over g as repeticoes,
                        row_number() over (g order by v.criado_em desc) as n
                 from agentesia_eventos v left join agentesia_escritorios e on e.id = v.id_escritorio
                 where ($1::uuid is null or v.id_escritorio = $1::uuid)
                   and (not $2 or v.resolvido_em is null)
                   and v.gravidade <> 'info'          -- "Etapa do lead: sdr → closer" é registro, não erro
                 window g as (partition by v.id_escritorio, coalesce(v.id_lead::text, v.id::text), v.tipo,
                                           (v.resolvido_em is null))
               ) x where n = 1
               order by criado_em desc limit $3""", id_escritorio, abertos, limite))

    async def resolver_evento(self, id_evento: str, id_escritorio: str | None, id_usuario: str) -> bool:
        """Resolve o erro e as repetições abertas dele (mesmo escritório, lead e tipo)."""
        resultado = await self.pool.execute(
            """update agentesia_eventos v set resolvido_em = now(), resolvido_por = $3::uuid
               from agentesia_eventos alvo
               where alvo.id = $1::uuid and ($2::uuid is null or alvo.id_escritorio = $2::uuid)
                 and v.resolvido_em is null and v.tipo = alvo.tipo
                 and v.id_escritorio is not distinct from alvo.id_escritorio
                 and (v.id = alvo.id or (alvo.id_lead is not null and v.id_lead = alvo.id_lead))""",
            id_evento, id_escritorio, id_usuario)
        return not resultado.endswith(" 0")

    async def conversas(self, id_escritorio: str, busca: str = "", limite: int = 100,
                        id_agente: str | None = None) -> list[dict[str, Any]]:
        # Telefone é guardado só com dígitos: "(11) 98765-4321" e "+55 11 98765..." procuram pelos dígitos.
        # Com letra na busca, é nome: os números dela não viram busca de telefone.
        digitos = "" if re.search(r"[^\W\d_]", busca) else re.sub(r"\D", "", busca)
        # A prévia da lista é a última mensagem: o texto, ou o que foi lido da mídia (transcrição do áudio,
        # descrição da imagem), e o tipo, para a tela mostrar "Áudio" quando não há texto nenhum.
        return _linhas(await self.pool.fetch(
            """select l.id, c.nome, c.telefone_normalizado as telefone, l.estado, l.motivo_estado, l.pausado_ate,
                      e.codigo as etapa, l.id_agente, a.nome as agente, l.ultima_mensagem_lead_em, l.ultima_resposta_ia_em, l.criado_em,
                      coalesce(nullif(btrim(u.texto), ''), nullif(btrim(u.texto_extraido), '')) as ultima_mensagem,
                      u.tipo as ultima_mensagem_tipo,
                      a.situacao as situacao_agente, (es.ia_desligada or es.situacao <> 'ativo') as ia_desligada_escritorio
               from agentesia_leads l
               join agentesia_contatos c on c.id = l.id_contato
               join agentesia_escritorios es on es.id = l.id_escritorio
               left join agentesia_agente_etapas e on e.id = l.id_etapa
               left join agentesia_agentes a on a.id = l.id_agente
               left join lateral (select m.texto, m.texto_extraido, m.tipo from agentesia_mensagens m where m.id_lead = l.id
                                  order by m.enviada_em desc limit 1) u on true
               where l.id_escritorio = $1::uuid
                 and ($2 = '' or ($4 <> '' and c.telefone_normalizado like '%' || $4 || '%') or c.nome ilike '%' || $2 || '%')
                 and ($5::uuid is null or l.id_agente = $5::uuid)
               order by coalesce(l.ultima_mensagem_lead_em, l.criado_em) desc limit $3""",
            id_escritorio, busca, limite, digitos, id_agente))

    async def conversa(self, id_escritorio: str, id_lead: str) -> dict[str, Any] | None:
        lead = _linha(await self.pool.fetchrow(
            """select l.*, c.nome, c.telefone_normalizado as telefone, e.codigo as etapa, a.nome as agente,
                      a.situacao as situacao_agente, (es.ia_desligada or es.situacao <> 'ativo') as ia_desligada_escritorio
               from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
               join agentesia_escritorios es on es.id = l.id_escritorio
               left join agentesia_agente_etapas e on e.id = l.id_etapa
               left join agentesia_agentes a on a.id = l.id_agente
               where l.id = $1::uuid and l.id_escritorio = $2::uuid""", id_lead, id_escritorio))
        if not lead:
            return None
        import asyncio
        # As partes da conversa são independentes: em paralelo (a tela aberta repete este pedido a cada 8 s).
        mensagens, memoria, fatos, turnos, eventos = await asyncio.gather(
            self.pool.fetch(
                """select id, autor, tipo, texto, texto_extraido, url_midia, enviada_em, situacao_envio, erro, id_turno
                   from agentesia_mensagens where id_lead = $1::uuid order by enviada_em, registrada_em""", id_lead),
            # Ficha de memória da conversa (feita pela IA quando a conversa fica longa); None enquanto não existe.
            self.pool.fetchrow(
                """select resumo, mensagens_resumidas, atualizado_em from agentesia_lead_resumo
                   where id_lead = $1::uuid and id_escritorio = $2::uuid""", id_lead, id_escritorio),
            self.pool.fetch(
                """select chave, valor, trecho, fonte, criado_em, substituido_em from agentesia_lead_fatos
                   where id_lead = $1::uuid order by criado_em""", id_lead),
            self.pool.fetch(
                """select id, modo, etapa_antes, etapa_depois, situacao, motivo, resposta, iniciado_em, concluido_em
                   from agentesia_turnos where id_lead = $1::uuid order by iniciado_em desc limit 50""", id_lead),
            self.pool.fetch(
                """select tipo, gravidade, responsavel, descricao, criado_em from agentesia_eventos
                   where id_lead = $1::uuid order by criado_em desc limit 50""", id_lead))
        lead["mensagens"], lead["memoria"], lead["fatos"] = _linhas(mensagens), _linha(memoria), _linhas(fatos)
        lead["turnos"], lead["eventos"] = _linhas(turnos), _linhas(eventos)
        # Aba "Rastro" (B11): o funil com a etapa ativa e a linha do tempo das passagens, recusas, barreiras e pausas.
        from app.gestao import rastro
        try:
            lead["funil"], lead["rastro"] = await rastro.montar(self.pool, lead)
        except Exception:                               # o rastro nunca derruba a conversa aberta
            import logging
            logging.getLogger("agentesia").exception("falha ao montar o rastro do lead %s", id_lead)
            lead["funil"], lead["rastro"] = None, []
        return lead

    async def mudar_estado_lead(self, id_escritorio: str, id_lead: str, estado: str, motivo: str) -> bool:
        resultado = await self.pool.execute(
            """update agentesia_leads set estado = $3, motivo_estado = $4, pausado_ate = null
               where id = $1::uuid and id_escritorio = $2::uuid""", id_lead, id_escritorio, estado, motivo)
        return resultado.endswith("1")

    # ------------------------------------------------------------------ avisos à equipe
    @staticmethod
    def _aviso(linha: dict[str, Any] | None) -> dict[str, Any] | None:
        if linha and isinstance(linha.get("destinatarios"), str):
            linha["destinatarios"] = json.loads(linha["destinatarios"] or "[]")
        return linha

    async def notificacoes(self, id_escritorio: str) -> list[dict[str, Any]]:
        return [self._aviso(x) for x in _linhas(await self.pool.fetch(  # type: ignore[misc]
            "select * from agentesia_notificacoes where id_escritorio = $1::uuid order by nome", id_escritorio))]

    async def notificacao(self, id_escritorio: str, tipo_evento: str) -> dict[str, Any] | None:
        return self._aviso(_linha(await self.pool.fetchrow(
            "select * from agentesia_notificacoes where id_escritorio = $1::uuid and tipo_evento = $2",
            id_escritorio, tipo_evento)))

    async def salvar_notificacao(self, id_escritorio: str, tipo_evento: str, *, nome: str, habilitada: bool,
                                 modelo_mensagem: str, destinatarios: list[dict[str, str]]) -> dict[str, Any]:
        return self._aviso(_linha(await self.pool.fetchrow(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, habilitada, modelo_mensagem, destinatarios)
               values ($1::uuid, $2, $3, $4, $5, $6::jsonb)
               on conflict (id_escritorio, tipo_evento) do update set nome = excluded.nome, habilitada = excluded.habilitada,
                 modelo_mensagem = excluded.modelo_mensagem, destinatarios = excluded.destinatarios
               returning *""", id_escritorio, tipo_evento, nome, habilitada, modelo_mensagem,
            json.dumps(destinatarios, ensure_ascii=False))))  # type: ignore[return-value]

    async def apagar_notificacao(self, id_escritorio: str, tipo_evento: str) -> bool:
        return (await self.pool.execute(
            "delete from agentesia_notificacoes where id_escritorio = $1::uuid and tipo_evento = $2",
            id_escritorio, tipo_evento)).endswith("1")

    async def enfileirar_acao(self, *, id_escritorio: str, tipo: str, dados: dict[str, Any], chave_unica: str,
                              id_lead: str | None = None) -> None:
        await self.pool.execute(
            """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
               values ($1::uuid, $2::uuid, $3, $4, $5::jsonb) on conflict (chave_unica) do nothing""",
            id_escritorio, id_lead, tipo, chave_unica, json.dumps(dados, ensure_ascii=False))

    # ------------------------------------------------------------------ histórico
    async def registrar_alteracao(self, *, id_usuario: str | None, id_escritorio: str | None, tabela: str,
                                  id_registro: str | None, acao: str, resumo: str,
                                  antes: Any = None, depois: Any = None,
                                  situacao: str = "ok", erro: str | None = None) -> None:
        """situacao='erro' + erro: ação de admin que falhou (colunas da migração 006). Sem a 006 a falha ainda fica
        registrada, com o erro no resumo."""
        valores = [id_usuario, id_escritorio, tabela, id_registro, acao, resumo,
                   None if antes is None else _j(antes), None if depois is None else _j(depois)]
        sql = """insert into agentesia_alteracoes (id_usuario, id_escritorio, tabela, id_registro, acao, resumo, antes, depois{extra})
                 values ($1::uuid, $2::uuid, $3, $4::uuid, $5, $6, $7::jsonb, $8::jsonb{params})"""
        if situacao == "ok" and not erro:
            await self.pool.execute(sql.format(extra="", params=""), *valores)
            return
        try:
            await self.pool.execute(sql.format(extra=", situacao, erro", params=", $9, $10"), *valores,
                                    situacao, (erro or "")[:2000] or None)
        except asyncpg.UndefinedColumnError:
            valores[5] = f"FALHOU: {resumo} ({erro or situacao})"[:2000]
            await self.pool.execute(sql.format(extra="", params=""), *valores)

    async def alteracoes(self, id_escritorio: str | None, limite: int = 200) -> list[dict[str, Any]]:
        # to_jsonb(h): lê situacao/erro sem quebrar no banco que ainda não tem a migração 006.
        return _linhas(await self.pool.fetch(
            """select h.id, h.tabela, h.id_registro, h.acao, h.resumo, h.antes, h.depois, h.criado_em,
                      coalesce(to_jsonb(h) ->> 'situacao', 'ok') as situacao, to_jsonb(h) ->> 'erro' as erro,
                      u.nome as usuario, u.papel, e.nome as escritorio
               from agentesia_alteracoes h
               left join agentesia_usuarios u on u.id = h.id_usuario
               left join agentesia_escritorios e on e.id = h.id_escritorio
               where ($1::uuid is null or h.id_escritorio = $1::uuid)
               order by h.criado_em desc limit $2""", id_escritorio, limite))
