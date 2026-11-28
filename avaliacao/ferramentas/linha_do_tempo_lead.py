"""Linha do tempo de um lead de produção (mensagens, eventos, turnos e fatos), só leitura.
Uso: .venv/Scripts/python.exe avaliacao/ferramentas/linha_do_tempo_lead.py <id_lead> <arquivo_saida.txt>
Lê AGENTESIA_BANCO_URL do .env.producao (nunca commitado). Horários em UTC (Brasília = UTC-3)."""
import asyncio, sys, json, asyncpg
sys.stdout.reconfigure(encoding="utf-8")
url = next(l.split("=",1)[1].strip() for l in open(".env.producao",encoding="utf-8") if l.startswith("AGENTESIA_BANCO_URL="))
L=sys.argv[1]; OUT=sys.argv[2]
s=lambda v: "" if v is None else str(v)
async def m():
    c=await asyncpg.connect(url,statement_cache_size=0)
    linhas=[]
    for r in await c.fetch("select coalesce(enviada_em,registrada_em) t, autor, tipo, texto, texto_extraido ext, url_midia, situacao_envio, erro from agentesia_mensagens where id_lead=$1::uuid order by 1",L):
        t=r["t"]; linhas.append((t, f"MSG {t:%H:%M:%S} [{r['autor']}/{r['tipo']}] {s(r['texto'])[:700]}" + (f" (transcr: {s(r['ext'])[:300]})" if r['ext'] else "") + (f" <{s(r['url_midia'])[-60:]}>" if r['url_midia'] else "") + (f" !{r['situacao_envio']} {r['erro']}" if r['erro'] else "")))
    for r in await c.fetch("select criado_em t, tipo, gravidade, descricao, detalhe::text d from agentesia_eventos where id_lead=$1::uuid order by 1",L):
        linhas.append((r["t"], f"EVT {r['t']:%H:%M:%S} {r['tipo']} [{r['gravidade']}] {s(r['descricao'])[:250]} {s(r['d'])[:400]}"))
    for r in await c.fetch("select iniciado_em t, modo, etapa_antes, etapa_depois, situacao, motivo, contexto::text ctx from agentesia_turnos where id_lead=$1::uuid order by 1",L):
        ctx=json.loads(r["ctx"] or "{}")
        repro=ctx.get("reprovacoes")
        linhas.append((r["t"], f"TURNO {r['t']:%H:%M:%S} {r['modo']} {r['etapa_antes']}->{r['etapa_depois']} {r['situacao']} {s(r['motivo'])} | reprov={json.dumps(repro,ensure_ascii=False)[:700] if repro else ''} | fatos_novos={json.dumps(ctx.get('fatos_novos'),ensure_ascii=False)[:400] if ctx.get('fatos_novos') else ''}"))
    linhas.sort(key=lambda x:x[0])
    open(OUT,"w",encoding="utf-8").write("\n".join(l for _,l in linhas))
    print("ctx keys exemplo:", list(json.loads((await c.fetchval("select contexto::text from agentesia_turnos where id_lead=$1::uuid order by iniciado_em desc limit 1",L)) or "{}"))[:30])
    for f in await c.fetch("select * from agentesia_lead_fatos where id_lead=$1::uuid",L):
        d=dict(f); print({k:s(v)[:100] for k,v in d.items() if k not in ('id','id_escritorio','id_lead')})
    await c.close()
asyncio.run(m())
