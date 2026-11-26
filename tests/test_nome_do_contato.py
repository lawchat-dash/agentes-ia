"""O webhook da plataforma não traz o nome do lead (26/11: todos os contatos estavam "Sem nome"). Na primeira ação que
resolve o contato (criar o card do lead novo), o nome vem do cadastro do contato e fica guardado; depois não busca mais."""

from app.acoes import Executor


class Pool:
    def __init__(self):
        self.updates = []

    async def execute(self, sql, *args):
        self.updates.append((sql, args))
        return "UPDATE 1"


class Plataforma:
    def __init__(self, nome):
        self.nome, self.pedidos = nome, 0

    async def nome_do_contato(self, _id):
        self.pedidos += 1
        return self.nome


async def test_busca_o_nome_uma_vez_e_guarda():
    executor = Executor.__new__(Executor)
    executor._pool = Pool()
    plataforma = Plataforma("Maria Souza")
    contexto = {"lead": {"id_contato": "c1", "id_contato_helena": "h1", "nome": None}, "helena": plataforma}
    assert await executor._id_contato(contexto) == "h1"
    assert contexto["lead"]["nome"] == "Maria Souza" and plataforma.pedidos == 1
    assert "set nome = coalesce" in executor._pool.updates[-1][0]
    await executor._id_contato(contexto)                       # já tem nome: não pergunta de novo
    assert plataforma.pedidos == 1


async def test_falha_ao_buscar_nome_nao_derruba_a_acao():
    class Quebrada(Plataforma):
        async def nome_do_contato(self, _id):
            raise RuntimeError("fora do ar")
    executor = Executor.__new__(Executor)
    executor._pool = Pool()
    contexto = {"lead": {"id_contato": "c1", "id_contato_helena": "h1"}, "helena": Quebrada(None)}
    assert await executor._id_contato(contexto) == "h1" and not executor._pool.updates
