"""A IA não pode mandar ao lead o formato interno do histórico de mídia ("[mídia enviada: ...]")."""
from app.cerebro.catalogo import conferir


def test_balao_com_marca_de_midia_enviada_e_barrado():
    erros = conferir([{"tipo": "texto", "texto": "[mídia enviada:"}, {"tipo": "midia", "url": "https://x/a.ogg"}], "closer")
    assert any("marcadores" in e for e in erros)


def test_sem_acento_tambem_e_barrado():
    assert conferir([{"tipo": "texto", "texto": "[midia enviada: honorarios.ogg]"}], "sdr")


def test_texto_normal_passa():
    assert conferir([{"tipo": "texto", "texto": "Conseguiu ouvir o áudio que te mandei?"}], "closer") == []
