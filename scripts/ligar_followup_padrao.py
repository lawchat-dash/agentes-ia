"""Liga o follow-up com o padrão do produto nos produtos JÁ ativos (antes da regra "vem ligado", docs/FOLLOWUP.md).

Por padrão só LISTA (não muda nada). Para ligar, o dono decide e passa --aplicar com o alvo:
  python scripts/ligar_followup_padrao.py                                   # lista todos e o follow-up de cada um
  python scripts/ligar_followup_padrao.py --escritorio <uuid>               # só um escritório
  python scripts/ligar_followup_padrao.py --produto <id_ativado> --aplicar  # liga um (pode repetir --produto)
  python scripts/ligar_followup_padrao.py --todos-desligados --aplicar      # liga todos os ATIVOS que estão desligados

Banco: --banco ou AGENTESIA_BANCO_URL (o .env é lido). Cada ligação fica em agentesia_alteracoes ("script").
A mesma ação existe no painel: LawChat › Follow-up (POST /api/admin/followup/ligar).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def principal(argv: list[str] | None = None, pool: Any = None) -> int:
    """pool: só nos testes (o banco local aceita uma conexão); senão abre uma pelo --banco."""
    import asyncpg

    from app.config import carregar
    from app.followup import padrao

    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--banco", default=None, help="URL do Postgres (padrão: AGENTESIA_BANCO_URL)")
    args.add_argument("--escritorio", default=None, help="só este escritório (uuid)")
    args.add_argument("--produto", action="append", default=[], help="id do produto ativado a ligar (pode repetir)")
    args.add_argument("--todos-desligados", action="store_true", help="todos os produtos ATIVOS com follow-up desligado")
    args.add_argument("--aplicar", action="store_true", help="liga de verdade (sem isto, só mostra o que faria)")
    opcoes = args.parse_args(argv)

    proprio = pool is None
    if proprio:
        url = opcoes.banco or carregar().banco_url or os.environ.get("AGENTESIA_BANCO_URL")
        if not url:
            print("Sem banco: use --banco ou AGENTESIA_BANCO_URL.")
            return 2
        pool = await asyncpg.create_pool(url, min_size=1, max_size=1, statement_cache_size=0)
    try:
        produtos = await padrao.panorama(pool, opcoes.escritorio)
        print(f"{'escritório':28} {'produto':32} {'situação':9} follow-up")
        for p in produtos:
            fu = p["followup"]
            estado = "LIGADO" if fu["ligado"] else ("desligado" if fu["configurado"] else "sem config")
            print(f"{p['escritorio'][:28]:28} {p['nome'][:32]:32} {p['status'][:9]:9} {estado} ({', '.join(fu['resumo'])})  {p['id_ativado']}")
        if opcoes.todos_desligados:
            alvo = [p["id_ativado"] for p in produtos if p["status"] == "ativo" and not p["followup"]["ligado"]]
        else:
            ids = {p["id_ativado"] for p in produtos}
            alvo = [i for i in dict.fromkeys(opcoes.produto) if i in ids]
            for faltou in set(opcoes.produto) - ids:
                print(f"! produto {faltou} não encontrado (ou sem agente / na lixeira / de outro escritório)")
        if not alvo:
            print("\nNada a ligar." if (opcoes.produto or opcoes.todos_desligados) else "\nSó listagem. Use --produto ou --todos-desligados com --aplicar para ligar.")
            return 0
        if not opcoes.aplicar:
            print(f"\nSimulação: ligaria {len(alvo)} produto(s). Rode de novo com --aplicar para ligar.")
            return 0
        for id_ativado in alvo:
            feito = await padrao.ligar_com_padrao(pool, id_ativado, id_usuario=None, origem="script")
            if feito:
                print(f"ligado: {feito['nome']} ({', '.join(feito['followup']['resumo'])})" + (f"  ! {feito['aviso']}" if feito["aviso"] else ""))
        return 0
    finally:
        if proprio:
            await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(principal()))
