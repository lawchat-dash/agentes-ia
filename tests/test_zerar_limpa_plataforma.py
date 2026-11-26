"""Zerar o número de teste também limpa a plataforma (26/11): o lead zerado continuava com a etiqueta
"🤖 IA Desativada" e sem nota no chat. Agora tira a etiqueta e as das etapas, põe a do SDR, volta o card para a coluna
SDR e deixa uma nota. Falha na plataforma não desfaz o zerar."""

from types import SimpleNamespace

from app.gestao import rotas_filtro


class Pool:
    def __init__(self, crm):
        self.crm = crm

    async def fetchval(self, _sql, *_args):
        return self.crm


class Helena:
    def __init__(self, falhar=False):
        self.feito, self.falhar = [], falhar

    async def etiquetar(self, contato, nomes, remover=False):
        if self.falhar:
            raise RuntimeError("fora do ar")
        self.feito.append(("tirar" if remover else "por", contato, tuple(nomes)))

    async def mover_card(self, card, coluna):
        self.feito.append(("card", card, coluna))

    async def nota(self, sessao, texto):
        self.feito.append(("nota", sessao, texto))


async def _rodar(monkeypatch, helena, crm=None, linhas=None):
    import app.banco.postgres as pg
    import app.canal.helena_conta as hc

    async def token(_pool, _esc):
        return "tok"
    monkeypatch.setattr(pg, "token_helena", token)
    monkeypatch.setattr(hc, "HelenaConta", lambda *_a, **_k: helena)
    pedido = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cfg=SimpleNamespace(helena_url="https://x.invalid"))))
    repo = SimpleNamespace(pool=Pool(crm if crm is not None else {"etapas_por_tipo": {"SDR": "col-sdr"}}))
    linhas = linhas if linhas is not None else [{"id_sessao_helena": "s1", "id_contato_helena": "c1", "id_card_helena": "card1"}]
    return await rotas_filtro._limpar_na_plataforma(pedido, repo, "esc", linhas)


async def test_zerar_tira_ia_desativada_volta_o_card_e_anota(monkeypatch):
    helena = Helena()
    feito = await _rodar(monkeypatch, helena)
    assert feito == {"etiquetas": True, "card": True, "nota": True}
    tirar = next(f for f in helena.feito if f[0] == "tirar")
    assert "🤖 IA Desativada" in tirar[2] and "🛒 Comercial" in tirar[2] and "📞 SDR" not in tirar[2]
    assert ("por", "c1", ("📞 SDR",)) in helena.feito
    assert ("card", "card1", "col-sdr") in helena.feito
    assert ("nota", "s1", rotas_filtro.NOTA_ZERADO) in helena.feito


async def test_falha_na_plataforma_nao_quebra_o_zerar(monkeypatch):
    feito = await _rodar(monkeypatch, Helena(falhar=True))
    assert feito["etiquetas"] is False and feito["erro_etiquetas"] == "RuntimeError" and feito["nota"] is True


async def test_sem_lead_ou_sem_coluna_nao_mexe(monkeypatch):
    assert await _rodar(monkeypatch, Helena(), linhas=[]) == {"etiquetas": False, "card": False, "nota": False}
    helena = Helena()
    feito = await _rodar(monkeypatch, helena, crm={})
    assert feito["card"] is False and not any(f[0] == "card" for f in helena.feito)
