"""O sistema manda o áudio e o vídeo de como assinar antes do link (validação de 27/11)."""
from app.contrato import dados as cdados

ROTEIRO = """# CONTEXTO

Fala da assinatura. https://x.supabase.co/storage/v1/object/public/agent-media/a/audio/1-fora.ogg

---

# PRIMEIRA MENSAGEM DESTA ETAPA

Se ainda não estiverem no histórico, envie cada mídia sozinha:

https://x.supabase.co/storage/v1/object/public/agent-media/a/audio/2-como-assinar.ogg

https://x.supabase.co/storage/v1/object/public/agent-media/a/video/3-video-assinar.mp4

Depois: "Conseguiu abrir o link certinho?"

---

# OBJETIVO
https://x.supabase.co/storage/v1/object/public/agent-media/a/audio/4-outro.ogg
"""


def test_pega_so_as_midias_da_secao_na_ordem():
    assert cdados.midias_de_como_assinar(ROTEIRO) == [
        "https://x.supabase.co/storage/v1/object/public/agent-media/a/audio/2-como-assinar.ogg",
        "https://x.supabase.co/storage/v1/object/public/agent-media/a/video/3-video-assinar.mp4"]


def test_sem_secao_ou_sem_arquivo_nao_manda_nada():
    assert cdados.midias_de_como_assinar("# CONTEXTO\nnada") == []
    assert cdados.midias_de_como_assinar("### Primeira mensagem desta etapa\n\n[[audio:Como Fazer a Assinatura]]\n") == []
    assert cdados.midias_de_como_assinar(None) == []


def test_texto_do_link_com_midia():
    texto = cdados.texto({}, "link_com_midia", link="https://zapsign/x")
    assert "https://zapsign/x" in texto and "vídeo acima" in texto
