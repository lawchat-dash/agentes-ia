"""Cria alguém da LawChat e mostra a senha provisória uma vez.

Uso:
  .venv/Scripts/python -m app.gestao.criar_admin email@exemplo.com "Nome"            (dono da LawChat)
  .venv/Scripts/python -m app.gestao.criar_admin email@exemplo.com "Nome" --equipe   (equipe LawChat)

O primeiro acesso do sistema deve ser um dono. Depois, o dono adiciona o resto da equipe pelo painel
(LawChat › Equipe LawChat).
"""

from __future__ import annotations

import asyncio
import sys

import asyncpg

from app import config as configuracao
from app.gestao import seguranca


async def principal(email: str, nome: str, papel: str) -> None:
    cfg = configuracao.carregar()
    if not cfg.banco_url:
        sys.exit("Defina AGENTESIA_BANCO_URL no .env.")
    conexao = await asyncpg.connect(cfg.banco_url, statement_cache_size=0)
    try:
        if await conexao.fetchval("select 1 from agentesia_usuarios where email = $1", email.lower()):
            sys.exit("Já existe um usuário com este e-mail.")
        senha = seguranca.senha_provisoria()
        await conexao.execute(
            """insert into agentesia_usuarios (email, nome, senha_hash, papel)
               values ($1, $2, $3, $4)""", email.lower(), nome, seguranca.gerar_hash(senha), papel)
    finally:
        await conexao.close()
    print(f"{'Dono' if papel == 'dono_lawchat' else 'Equipe'} LawChat criado: {email.lower()}")
    print(f"Senha provisória (troque no primeiro acesso): {senha}")


if __name__ == "__main__":
    argumentos = [a for a in sys.argv[1:] if a != "--equipe"]
    if len(argumentos) != 2:
        sys.exit(__doc__)
    asyncio.run(principal(argumentos[0], argumentos[1], "admin_lawchat" if "--equipe" in sys.argv else "dono_lawchat"))
