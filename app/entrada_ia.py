"""App "ia" do Easypanel: webhooks da Helena e da ZapSign, pipeline, fila de ações, follow-ups e laços de fundo.

Rodar:  uvicorn app.entrada_ia:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*
"""

from app.servidor import criar_app

app = criar_app("ia")
