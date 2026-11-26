"""Saúde do número de WhatsApp: o selo dos cartões de "Meus agentes" e de Minha Conta › Integrações, e o
"Testar conexão" (só lê: nada muda na Helena).

Selo de cada número, pela última mensagem de lead recebida nele:
  recebendo     última mensagem há menos de LIMITE_HORAS
  parado        a última foi há mais tempo ("sem mensagens há X dias")
  sem_mensagens o número nunca recebeu mensagem
  sem_numero    o agente não tem número (voltou da lixeira, por exemplo)

O tipo vem do canal: "oficial" (API oficial da Meta, com a janela de 24 h para mensagens livres) ou "nao_oficial".

Testar conexão reaproveita `ativacao.preparar(aplicar=False)` (os mesmos passos da ativação: conta, número, webhook e
endereço público) e soma a última mensagem recebida no número.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.canal.helena_conta import HelenaConta
from app.gestao import ativacao

LIMITE_HORAS = 24
AVISO_OFICIAL = ("API oficial: fora da janela de 24 h desde a última mensagem do lead, só sai mensagem com modelo "
                 "aprovado pela Meta.")
WEBHOOK_PENDENTE = ("a assinatura que traz as mensagens não está certa na conta: em Minha Conta › Integrações, use "
                    "\"Conectar webhook\" (ou fale com a equipe LawChat)")
PASSOS_DO_TESTE = {"helena": "Conta da LawChat (token)", "canal": "Número de WhatsApp",
                   "webhook": "Recebimento das mensagens (webhook)", "alcance": "Endereço público do servidor"}


def selo(tem_numero: bool, ultima: datetime | None, agora: datetime | None = None) -> dict[str, Any]:
    if not tem_numero:
        return {"tipo": "sem_numero", "minutos": None}
    if ultima is None:
        return {"tipo": "sem_mensagens", "minutos": None}
    agora = agora or datetime.now(timezone.utc)
    minutos = max(0, int((agora - ultima).total_seconds() // 60))
    return {"tipo": "recebendo" if minutos < LIMITE_HORAS * 60 else "parado", "minutos": minutos}


async def numeros(pool: Any, id_escritorio: str) -> dict[str, Any]:
    """Cada número da conta (com o agente que usa) e cada agente (também os sem número), com selo e tipo."""
    ultimas = {r["id_canal"]: r["ultima"] for r in await pool.fetch(
        """select l.id_canal::text as id_canal, max(m.enviada_em) as ultima
           from agentesia_mensagens m join agentesia_leads l on l.id = m.id_lead
           where m.id_escritorio = $1::uuid and m.autor = 'lead' group by l.id_canal""", id_escritorio)}
    agora = datetime.now(timezone.utc)
    canais = []
    for c in await pool.fetch(
            """select c.id::text as id, c.id_canal_helena, c.numero_normalizado, c.tipo, c.ativo,
                      a.id::text as id_agente, a.nome as nome_agente
               from agentesia_canais c left join agentesia_agentes a on a.id_canal = c.id
               where c.id_escritorio = $1::uuid order by c.ativo desc, c.numero_normalizado""", id_escritorio):
        ultima = ultimas.get(c["id"])
        canais.append({**dict(c), "ultima_recebida": ultima.isoformat() if ultima else None,
                       "selo": selo(True, ultima, agora), "aviso_tipo": AVISO_OFICIAL if c["tipo"] == "oficial" else None})
    agentes = []
    for a in await pool.fetch(
            """select a.id::text as id, a.nome, a.situacao, a.id_canal::text as id_canal, c.numero_normalizado, c.tipo
               from agentesia_agentes a left join agentesia_canais c on c.id = a.id_canal
               where a.id_escritorio = $1::uuid order by a.criado_em""", id_escritorio):
        ultima = ultimas.get(a["id_canal"]) if a["id_canal"] else None
        agentes.append({**dict(a), "ultima_recebida": ultima.isoformat() if ultima else None,
                        "selo": selo(a["id_canal"] is not None, ultima, agora),
                        "aviso_tipo": AVISO_OFICIAL if a["tipo"] == "oficial" else None})
    return {"canais": canais, "agentes": agentes, "limite_horas": LIMITE_HORAS, "agora": agora.isoformat()}


async def testar(*, repo: Any, id_escritorio: str, id_canal: str, helena_de: Callable[[str], Awaitable[HelenaConta]],
                 http: Any = None) -> dict[str, Any] | None:
    """Confere a conexão de um número, passo a passo, sem mudar nada. None: o número não é deste escritório."""
    canal = await repo.pool.fetchrow(
        """select c.id::text as id, c.id_canal_helena, c.numero_normalizado, c.tipo, a.id::text as id_agente
           from agentesia_canais c left join agentesia_agentes a on a.id_canal = c.id
           where c.id = $1::uuid and c.id_escritorio = $2::uuid""", id_canal, id_escritorio)
    if not canal:
        return None
    agente = await repo.agente(id_escritorio, canal["id_agente"]) if canal["id_agente"] else None
    # Número livre (sem agente): um agente "de mentira" basta para os passos de conta, número e webhook.
    agente = agente or {"id": None, "config": {}, "etapas": [], "produto": "auxilio_acidente",
                        "id_canal_helena": canal["id_canal_helena"], "numero_canal": canal["numero_normalizado"]}
    conferido = await ativacao.preparar(repo=repo, id_escritorio=id_escritorio, agente=agente, modo="producao",
                                        aplicar=False, helena_de=helena_de, http=http)
    passos = [{"codigo": p.codigo, "titulo": PASSOS_DO_TESTE[p.codigo], "situacao": p.situacao,
               "detalhe": (WEBHOOK_PENDENTE if p.codigo == "webhook" and p.situacao == "aviso" else p.detalhe).replace("LawChat", "LawChat")}
              for p in conferido.passos if p.codigo in PASSOS_DO_TESTE]
    ultima = await repo.pool.fetchval(
        """select max(m.enviada_em) from agentesia_mensagens m join agentesia_leads l on l.id = m.id_lead
           where l.id_canal = $1::uuid and m.autor = 'lead'""", id_canal)
    s = selo(True, ultima)
    if s["tipo"] == "recebendo":
        passos.append({"codigo": "mensagens", "titulo": "Mensagens chegando", "situacao": "ok",
                       "detalhe": f"última mensagem de lead há {_tempo(s['minutos'])}"})
    elif s["tipo"] == "parado":
        passos.append({"codigo": "mensagens", "titulo": "Mensagens chegando", "situacao": "aviso",
                       "detalhe": f"sem mensagens há {_tempo(s['minutos'])}: mande uma mensagem de teste para o número"})
    else:
        passos.append({"codigo": "mensagens", "titulo": "Mensagens chegando", "situacao": "aviso",
                       "detalhe": "este número ainda não recebeu mensagem: mande uma mensagem de teste para ele"})
    erros = [p for p in passos if p["situacao"] == "erro"]
    avisos = [p for p in passos if p["situacao"] == "aviso"]
    return {"ok": not erros, "avisos": len(avisos), "passos": passos, "tipo": canal["tipo"],
            "aviso_tipo": AVISO_OFICIAL if canal["tipo"] == "oficial" else None,
            "conferido_em": datetime.now(timezone.utc).isoformat()}


def _tempo(minutos: int | None) -> str:
    if minutos is None:
        return "—"
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 48 * 60:
        return f"{minutos // 60} h"
    return f"{minutos // (24 * 60)} dias"
