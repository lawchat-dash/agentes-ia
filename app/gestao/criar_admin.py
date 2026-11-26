"""Cria alguém da LawChat e mostra a senha provisória uma vez.

Uso:
  .venv/Scripts/python -m app.gestao.criar_admin email@exemplo.com "Nome"            (dono da LawChat)
  .venv/Scripts/python -m app.gestao.criar_admin email@exemplo.com "Nome" --equipe   (equipe LawChat)
  ... --producao        usa o banco do .env.producao (em vez do .env local)
  ... --escolher-senha  você digita a senha (escondida) em vez de receber uma provisória

O primeiro acesso do sistema deve ser um dono. Depois, o dono adiciona o resto da equipe pelo painel
(LawChat › Equipe LawChat).
"""

from __future__ import annotations

import asyncio
import getpass
import pathlib
import sys

import asyncpg

from app import config as configuracao
from app.gestao import seguranca


def _banco_da_producao() -> str | None:
    arquivo = pathlib.Path(".env.producao")
    if not arquivo.exists():
        return None
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if linha.startswith("AGENTESIA_BANCO_URL="):
            return linha.split("=", 1)[1].strip()
    return None


def _pedir_senha() -> str:
    while True:
        senha = getpass.getpass("Senha (mínimo 8 caracteres, não aparece na tela): ")
        if len(senha) < 8:
            print("Curta demais. Tente de novo.")
            continue
        if getpass.getpass("Repita a senha: ") != senha:
            print("As duas não batem. Tente de novo.")
            continue
        return senha


async def principal(email: str, nome: str, papel: str, producao: bool = False, escolher: bool = False) -> None:
    banco_url = _banco_da_producao() if producao else configuracao.carregar().banco_url
    if not banco_url:
        sys.exit("Defina AGENTESIA_BANCO_URL no .env.producao." if producao else "Defina AGENTESIA_BANCO_URL no .env.")
    conexao = await asyncpg.connect(banco_url, statement_cache_size=0)
    try:
        if await conexao.fetchval("select 1 from agentesia_usuarios where email = $1", email.lower()):
            sys.exit("Já existe um usuário com este e-mail.")
        senha = _pedir_senha() if escolher else seguranca.senha_provisoria()
        await conexao.execute(
            """insert into agentesia_usuarios (email, nome, senha_hash, papel)
               values ($1, $2, $3, $4)""", email.lower(), nome, seguranca.gerar_hash(senha), papel)
    finally:
        await conexao.close()
    print(f"{'Dono' if papel == 'dono_lawchat' else 'Equipe'} LawChat criado: {email.lower()}")
    if not escolher:
        print(f"Senha provisória (troque no primeiro acesso): {senha}")


if __name__ == "__main__":
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(argumentos) != 2:
        sys.exit(__doc__)
    asyncio.run(principal(argumentos[0], argumentos[1], "admin_lawchat" if "--equipe" in sys.argv else "dono_lawchat",
                          producao="--producao" in sys.argv, escolher="--escolher-senha" in sys.argv))
