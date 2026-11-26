"""App "painel" do Easypanel: front compilado (painel/dist) e API de gestão /api/*. Sem laços de fundo.

Rodar:  uvicorn app.entrada_painel:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*
"""

from app.servidor import criar_app

app = criar_app("painel")
