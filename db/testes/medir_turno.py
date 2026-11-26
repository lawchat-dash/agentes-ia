"""Mede o turno da IA com o banco local e uma latência artificial por consulta (imita o servidor no Brasil falando com o
Supabase em us-west-2: ~200 ms por ida). Modelo falso e Helena falsa: nada de API real nem de IA paga.

Uso (banco local já de pé: node db/testes/servidor_local.mjs PORTA):
    AGENTESIA_TESTE_PG_URL=postgresql://postgres:postgres@127.0.0.1:PORTA/postgres \
    .venv/Scripts/python.exe -m db.testes.medir_turno [--latencia-ms 200] [--modelo-ms 0] [--espera-s 3] [--digitar]

Mostra, por turno: chegada do webhook -> início do turno (sobra além do delay), início -> 1ª parte enviada,
início -> fim, idas ao banco (no webhook e no turno) e os passos gravados em agentesia_turnos.resposta["tempos"].
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg.connection  # noqa: E402

LATENCIA_S = 0.2
CONSULTAS: list[float] = []                       # instante (monotonic) de cada ida ao banco


_NO_POOL: ContextVar[bool] = ContextVar("latencia_ja_contada", default=False)


def _com_latencia() -> None:
    """Cada ida ao banco espera LATENCIA_S.

    O servidor local (PGlite) só funciona com UMA conexão (com várias, os comandos de conexões diferentes se misturam
    na sessão única dele). Então a latência das consultas feitas pelo pool (pool.fetch*, pool.execute*) é esperada
    ANTES de pegar a conexão: consultas juntas (asyncio.gather) esperam a rede em paralelo, como no Postgres de verdade
    com pool de 10, e só a execução (~ms) fica em fila. Consultas numa conexão já pega (transações) esperam a latência
    segurando a conexão (um pouco pessimista: em produção as outras consultas usariam outra conexão)."""
    import asyncpg.pool

    original_do_execute = asyncpg.connection.Connection._do_execute
    original_execute = asyncpg.connection.Connection.execute

    async def _do_execute(self, *args, **kwargs):
        if not _NO_POOL.get():
            CONSULTAS.append(time.monotonic())
            await asyncio.sleep(LATENCIA_S)
        return await original_do_execute(self, *args, **kwargs)

    async def execute(self, query, *args, timeout=None):
        if not args and not _NO_POOL.get():      # BEGIN/COMMIT e SQL sem parâmetro (o resto passa por _do_execute)
            CONSULTAS.append(time.monotonic())
            await asyncio.sleep(LATENCIA_S)
        return await original_execute(self, query, *args, timeout=timeout)

    asyncpg.connection.Connection._do_execute = _do_execute
    asyncpg.connection.Connection.execute = execute

    for nome in ("fetch", "fetchrow", "fetchval", "execute", "executemany"):
        original = getattr(asyncpg.pool.Pool, nome)

        def embrulhar(original):
            async def com_rede(self, *args, **kwargs):
                CONSULTAS.append(time.monotonic())
                await asyncio.sleep(LATENCIA_S)
                ficha = _NO_POOL.set(True)
                try:
                    return await original(self, *args, **kwargs)
                finally:
                    _NO_POOL.reset(ficha)
            return com_rede
        setattr(asyncpg.pool.Pool, nome, embrulhar(original))


async def _cenario(pool, espera_s: float):
    """Escritório, canal e agente do catálogo (como o da LawChat), número de teste com espera fixa."""
    conta, numero_canal = str(uuid.uuid4()), "55119" + str(uuid.uuid4().int)[:8]
    segredo = await pool.fetchval("insert into vault.decrypted_secrets (decrypted_secret) values ('token-x') returning id")
    escritorio = await pool.fetchval(
        """insert into agentesia_escritorios (nome, id_conta_helena, id_segredo_helena, config)
           values ('Escritório Medição', $1::uuid, $2, $3::jsonb) returning id""",
        conta, segredo, json.dumps({"numeros_teste": ["5511988887777"], "espera_teste_s": espera_s}))
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
        escritorio, numero_canal, "ch-" + conta[:8])
    config = {"catalogo": {"papeis": {"sdr": {}, "closer": {}}}, "funcoes": {"avisos": True},
              "automacoes": {"primeira_resposta": {"nota": "Lead em atendimento pela IA."}},
              "followup": {"ativo": True}}
    agente = await pool.fetchval(
        """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, situacao, config)
           values ($1, $2, 'Júlia', 'catalogo', 'ativo', $3::jsonb) returning id""", escritorio, canal, json.dumps(config))
    for ordem, (codigo, principal) in enumerate([("sdr", True), ("closer", False)], 1):
        await pool.execute(
            "insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal, instrucao) values ($1, $2, $3, $4, $5)",
            agente, codigo, ordem, principal, "Roteiro do papel: pergunte a idade e o que aconteceu.")
    return conta, numero_canal


async def main() -> None:
    global LATENCIA_S
    p = argparse.ArgumentParser()
    p.add_argument("--latencia-ms", type=float, default=200)
    p.add_argument("--modelo-ms", type=float, default=0)
    p.add_argument("--espera-s", type=float, default=3)
    p.add_argument("--digitar", action="store_true")
    p.add_argument("--conexoes", type=int, default=1)   # o PGlite só aguenta 1 (veja _com_latencia)
    args = p.parse_args()
    LATENCIA_S = args.latencia_ms / 1000

    from app.banco.postgres import RepositorioPostgres
    from app.config import Configuracao
    from app.modelo import ModeloFalso
    from app.pipeline import Atendimento
    from tests.test_pipeline import HelenaFalsa, webhook

    url = os.environ["AGENTESIA_TESTE_PG_URL"]
    repo = await RepositorioPostgres.conectar(url, max_conexoes=args.conexoes)
    conta, numero_canal = await _cenario(repo._pool, args.espera_s)
    _com_latencia()

    def extrator(_sistema, conteudo):
        novas = conteudo.split("MENSAGENS NOVAS DO LEAD:")[-1]
        fatos = [{"chave": "idade", "valor": 40, "trecho": "tenho 40 anos"}] if "40 anos" in novas else []
        return {"fatos": fatos, "sinais": [], "intencoes": {}}

    def etapa(_sistema, _conteudo):
        return {"mensagens": [{"texto": "Entendi! Me conta o que aconteceu?"}], "transferir_para": "", "ferramenta": ""}

    modelo = ModeloFalso({"extrator": extrator, "etapa": etapa})
    if args.modelo_ms:
        gerar = modelo.gerar

        async def gerar_lento(**kw):
            await asyncio.sleep(args.modelo_ms / 1000)
            return await gerar(**kw)
        modelo.gerar = gerar_lento  # type: ignore[method-assign]

    helena = HelenaFalsa()
    envios: list[float] = []
    enviar = helena.enviar

    async def enviar_medindo(**kw):
        envios.append(time.monotonic())
        return await enviar(**kw)
    helena.enviar = enviar_medindo  # type: ignore[method-assign]

    inicios: list[float] = []
    abrir = repo.abrir_turno

    async def abrir_medindo(**kw):
        inicios.append(time.monotonic())
        return await abrir(**kw)
    repo.abrir_turno = abrir_medindo  # type: ignore[method-assign]

    config = Configuracao(banco_url=url, helena_url="http://helena.invalid", modelo_padrao="falso", modelo_falso=True,
                          espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2)
    atendimento = Atendimento(repo, modelo, config, helena, digitar=args.digitar)

    print(f"latência {args.latencia_ms:.0f} ms/consulta, modelo {args.modelo_ms:.0f} ms/chamada, delay {args.espera_s:.1f} s")
    try:
        for i, texto in enumerate(["oi, boa tarde", "tenho 40 anos e caí da moto"], 1):
            corpo = webhook(texto, para=numero_canal)
            corpo["content"]["companyId"] = conta
            CONSULTAS.clear()
            envios.clear()
            inicios.clear()
            t0 = time.monotonic()
            await atendimento.receber(corpo)
            t_webhook = time.monotonic()
            idas_webhook = len(CONSULTAS)
            await atendimento.aguardar_esperas()
            t_fim = time.monotonic()
            idas_total = len(CONSULTAS)
            inicio = inicios[-1] if inicios else float("nan")
            idas_turno = sum(1 for c in CONSULTAS if c >= t_webhook)
            antes_do_turno = sum(1 for c in CONSULTAS if t_webhook <= c < inicio)
            print(f"\nturno {i}: '{texto}'")
            print(f"  webhook respondeu em        {(t_webhook - t0) * 1000:7.0f} ms  ({idas_webhook} idas ao banco)")
            print(f"  chegada -> início do turno  {(inicio - t0) * 1000:7.0f} ms  (sobra além do delay: "
                  f"{(inicio - t0 - args.espera_s) * 1000:.0f} ms; {antes_do_turno} idas antes de abrir o turno)")
            if envios:
                print(f"  início -> 1ª parte enviada  {(envios[0] - inicio) * 1000:7.0f} ms")
                print(f"  chegada -> 1ª parte enviada {(envios[0] - t0) * 1000:7.0f} ms")
            print(f"  início -> fim do turno      {(t_fim - inicio) * 1000:7.0f} ms")
            print(f"  idas ao banco no turno      {idas_turno:7d}  (total com o webhook: {idas_total})")
        linhas = await repo._pool.fetch(
            """select resposta->'tempos' as tempos from agentesia_turnos t join agentesia_escritorios e on e.id = t.id_escritorio
               where e.id_conta_helena = $1::uuid order by iniciado_em""", uuid.UUID(conta))
        for n, linha in enumerate(linhas, 1):
            if linha["tempos"]:
                print(f"\ntempos gravados no turno {n}: {linha['tempos']}")
    finally:
        await repo.fechar()


if __name__ == "__main__":
    asyncio.run(main())
