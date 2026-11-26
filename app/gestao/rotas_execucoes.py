"""Execuções (Superadmin): cada turno da IA, como as execuções do n8n. Só a equipe LawChat (ADMIN).

  GET /api/admin/execucoes/filtros      contas e agentes para os filtros
  GET /api/admin/execucoes              lista (mais novas primeiro, paginada) com filtros:
        conta, agente, busca (nome, número ou id do lead), situacao (respondido|sem_resposta|erro|processando),
        status (resultado: sucesso|sem_resposta|ignorado|descartado|erro|timeout|erro_5xx|erro_banco|interrompido|
        processando, vários com vírgula, ou "erros" = todos os de erro), troca=1 (só com troca de etapa),
        erro=1 (só com erro), de/ate (data-hora ISO), pagina, por_pagina
  GET /api/admin/execucoes/resumo       contadores do período (total, por resultado, erros, timeouts, taxa de erro,
                                        tempo médio, p95) e a série por hora (por dia acima de 3 dias); mesmos
                                        filtros; sem "de", as últimas 24 h
  GET /api/admin/execucoes/{id}         detalhe: mensagens do lead que entraram, o prompt que rodou, a decisão da IA,
                                        as mensagens que saíram, eventos e travas do turno, tempos, chamadas e custo,
                                        e a execução anterior/seguinte do mesmo lead

Dados: agentesia_turnos (+ leads, contatos, agentes, escritórios), agentesia_mensagens e agentesia_eventos por id_turno
(lidos pelo índice do lead), agentesia_chamadas_ia por id_turno (custo e tokens), agentesia_acoes do turno. Só leitura.

Resultado (deu certo ou errado, e por quê): calculado na consulta (_RESULTADO) a partir de situacao/motivo do turno, do
evento de erro do turno (o pipeline grava em 'erro_no_turno' o tipo, o módulo, a linha e o status HTTP), do erro das
chamadas de IA e das mensagens que falharam no envio. Turnos antigos, sem esse detalhe, caem pelo nome do erro no motivo.
Privacidade: telefone mascarado na lista e no detalhe; CPF/RG mascarados nos fatos, na ficha e no texto do prompt;
nenhum campo com cara de token/senha sai (vira "[oculto]").
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.gestao import rastro
from app.gestao.rotas import ADMIN, Contexto, _repo

api = APIRouter(prefix="/api/admin/execucoes")

UUID = re.compile(r"[0-9a-fA-F-]{36}")
SITUACOES = {"respondido": ["respondido"], "sem_resposta": ["silencio", "descartado"], "erro": ["erro"],
             "processando": ["processando"]}
ROTULO_SITUACAO = {"respondido": "Respondido", "silencio": "Sem resposta", "descartado": "Sem resposta",
                   "erro": "Erro", "processando": "Processando"}

# Eventos que mostram uma correção ou trava do motor atuando no turno (vão para "Correções e travas").
TITULOS_EXTRA = {
    "fato_pela_pergunta": "Fato tirado da pergunta da IA",
    "pergunta_ja_respondida": "Pergunta já respondida: a IA não repetiu",
    "segunda_tentativa_falhou": "Correção da IA falhou: seguiu com a 1ª resposta",
    "contrato_correcao_repetida": "Contrato: correção repetida, equipe assume",
}
TRAVAS = {"troca_barrada_faltam_fatos", "fato_pela_pergunta", "pergunta_ja_respondida", "portao_de_fatos",
          "destino_recusado", "troca_precoce_recusada", "transferencia_adiada_pergunta_aberta", "trocas_demais",
          "destino_ignorado", "destino_para_tras_ignorado", "sinal_recusado", "formato_invalido", "ia_fora_do_formato",
          "fora_do_tema", "tentativa_de_manipular", "trava_persistente", "segunda_tentativa_falhou",
          "contrato_correcao_repetida", "troca_pela_frase"}

# ------------------------------------------------------------------ resultado da execução
STATUS = {
    "sucesso": "Sucesso", "sem_resposta": "Sem resposta", "ignorado": "Ignorado", "descartado": "Refeito",
    "erro": "Erro", "timeout": "Timeout", "erro_5xx": "Erro 5xx", "erro_banco": "Erro de banco",
    "interrompido": "Interrompido", "processando": "Processando",
}
ERROS = ("erro", "timeout", "erro_5xx", "erro_banco", "interrompido")
ORIGENS = {"ia": "Modelo de IA", "plataforma": "Plataforma de atendimento", "banco": "Banco de dados",
           "servidor": "Servidor"}
# Motivos de silêncio em que a IA nem rodou (não é decisão dela): IA desligada, fora do horário, sem crédito...
IGNORADOS = {
    "escritorio_inativo": "Escritório inativo", "ia_desligada_no_escritorio": "IA desligada no escritório",
    "canal_sem_agente": "Canal sem agente", "agente_pausado": "Agente pausado",
    "agente_sem_etapa": "Agente sem etapa cadastrada", "modo_teste": "Modo teste: número fora da lista de teste",
    "etapa_terminal": "Lead no fim do funil", "sem_prompt": "Etapa sem prompt",
    "fora_do_horario": "Fora do horário do escritório", "janela_fechada": "Janela de 24 h do número oficial fechada",
    "equipe_respondeu": "A equipe já tinha respondido", "limite_de_consumo": "Limite de consumo do mês atingido",
    "sem_saldo": "Sem crédito de IA", "conversa_consigo_mesmo": "Conversa do número com ele mesmo",
    "numero_bloqueado": "Número bloqueado",
}
ESTADOS_LEAD = {"lead_pausado": "IA desativada neste lead (pausado ou com a equipe)", "lead_encerrado": "Lead encerrado"}
DESCARTES = {"chegou_mensagem_nova": "Chegou mensagem nova: a IA refez a resposta com tudo junto",
             "etapa_mudou": "A etapa mudou no meio: a IA refez a resposta", "estado_mudou": "O lead mudou de estado no meio"}
CODIGOS_IA = {
    "provedor_fora_do_ar": "o provedor de IA respondeu com erro de servidor", "sem_conexao": "sem conexão com o provedor de IA",
    "limite_de_uso": "limite de uso do provedor de IA (429)", "sem_credito": "sem crédito na conta do provedor de IA",
    "chave_recusada": "chave da IA recusada", "sem_permissao": "chave da IA sem permissão",
    "pedido_invalido": "pedido recusado pelo provedor de IA", "saida_invalida": "resposta da IA fora do formato",
    "saida_cortada": "resposta da IA cortada no limite de tokens", "recusa_do_modelo": "o modelo recusou responder",
}
TIMEOUTS = ("TimeoutError", "ReadTimeout", "WriteTimeout", "ConnectTimeout", "PoolTimeout", "APITimeoutError",
            "QueryCanceledError")
TIPOS_BANCO = ("BancoOcupado", "TooManyConnectionsError", "ConnectionDoesNotExistError", "InterfaceError", "InternalClientError",
               "PostgresConnectionError", "CannotConnectNowError", "ConnectionFailureError", "PostgresError",
               "InFailedSQLTransactionError", "DeadlockDetectedError", "UndefinedColumnError", "UndefinedTableError",
               "UniqueViolationError", "ForeignKeyViolationError", "NotNullViolationError", "DataError")
_TEMPO_ESGOTADO = r"time[d]? ?out|passou de [0-9]+ ?s"


def _lista_sql(valores: Any) -> str:
    return "array[" + ", ".join("'" + v.replace("'", "''") + "'" for v in valores) + "]::text[]"


# Erro do turno: o último evento de erro gravado nele e o último erro das chamadas de IA (só para turnos com erro).
# Mensagens da IA que falharam no envio (só para turnos respondidos). As duas usam o índice do lead.
_CLASSIFICACAO = """
  left join lateral (
       select ev.detalhe ->> 'tipo' as tipo_evento, ev.detalhe ->> 'modulo' as modulo, ev.detalhe ->> 'onde' as onde,
              coalesce(ev.detalhe ->> 'mensagem', ev.detalhe ->> 'detalhe') as mensagem_evento,
              ev.detalhe ->> 'status' as status_http, ev.descricao as descricao_erro, ev.detalhe as detalhe_erro,
              (select ci.erro from agentesia_chamadas_ia ci where ci.id_turno = t.id and not ci.sucesso
                order by ci.criado_em desc limit 1) as erro_ia
         from (select 1) um
         left join lateral (
              select e.detalhe, e.descricao from agentesia_eventos e
               where e.id_lead = t.id_lead and e.id_turno = t.id
                 and e.tipo in ('erro_no_turno', 'turno_interrompido', 'ia_nao_respondeu')
               order by (e.tipo = 'ia_nao_respondeu'), e.criado_em desc limit 1) ev on true
        where t.situacao = 'erro') x on true
  left join lateral (
       select count(*) as falhas_envio, max(m.erro) as erro_envio from agentesia_mensagens m
        where t.situacao = 'respondido' and m.id_lead = t.id_lead and m.id_turno = t.id and m.autor <> 'lead'
          and m.situacao_envio = 'falhou') env on true
"""
_COLUNAS_RESULTADO = """x.tipo_evento, x.modulo, x.onde, x.mensagem_evento, x.status_http, x.descricao_erro, x.detalhe_erro,
       x.erro_ia, env.falhas_envio, env.erro_envio"""
_TIPO_ERRO = "coalesce(x.tipo_evento, case when t.motivo like 'erro_interno:%' then split_part(t.motivo, ':', 2) end)"
_DO_BANCO = f"(x.modulo like 'asyncpg%' or x.onde like 'banco/%' or {_TIPO_ERRO} = any({_lista_sql(TIPOS_BANCO)}))"
_RESULTADO = f"""(case
  when t.situacao = 'processando' then 'processando'
  when t.motivo = 'turno_interrompido' then 'interrompido'
  when t.situacao = 'erro' then (case
       when {_TIPO_ERRO} = any({_lista_sql(TIMEOUTS)}) then 'timeout'
       when {_DO_BANCO} then 'erro_banco'
       when x.status_http ~ '^5[0-9][0-9]$' then 'erro_5xx'
       when {_TIPO_ERRO} like 'ErroHelena%' and coalesce(x.mensagem_evento, '') ~ 'HTTP 5[0-9][0-9]' then 'erro_5xx'
       when t.motivo ~ ':(provedor_fora_do_ar|sem_conexao)'
            and concat_ws(' ', x.erro_ia, x.mensagem_evento) ~* '{_TEMPO_ESGOTADO}' then 'timeout'
       when t.motivo ~ ':provedor_fora_do_ar' then 'erro_5xx'
       else 'erro' end)
  when t.situacao = 'respondido' then (case
       when coalesce(env.falhas_envio, 0) = 0 then 'sucesso'
       when env.erro_envio ~* '{_TEMPO_ESGOTADO}' then 'timeout'
       when env.erro_envio ~ 'HTTP 5[0-9][0-9]' then 'erro_5xx'
       else 'erro' end)
  when t.situacao = 'descartado' then 'descartado'
  when t.motivo = any({_lista_sql([*IGNORADOS, *ESTADOS_LEAD])}) then 'ignorado'
  else 'sem_resposta'
end)"""


def _int(valor: Any) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _resultado(r: Any) -> dict[str, Any]:
    """Status, origem, causa em português, o erro (tipo, mensagem, arquivo:linha) e se vai/foi tentado de novo."""
    status, motivo, situacao = r["resultado"], r["motivo"] or "", r["situacao"]
    partes = motivo.split(":")
    codigo = partes[1] if len(partes) > 1 else ""
    tipo = r["tipo_evento"] or (codigo if partes[0] == "erro_interno" else None)
    modulo, onde = r["modulo"] or "", r["onde"] or ""
    detalhe = _obj(r["detalhe_erro"]) if r["detalhe_erro"] is not None else {}
    detalhe = detalhe if isinstance(detalhe, dict) else {}
    nova_tentativa = motivo.endswith(":nova_tentativa")
    retomado = status == "descartado"
    origem: str | None = None
    if status == "interrompido":
        origem = "servidor"
        enviadas = _int(detalhe.get("enviadas"))
        retomado = enviadas == 0 if enviadas is not None else "responde de novo" in (r["descricao_erro"] or "")
    elif situacao == "respondido" and status in ERROS:
        origem = "plataforma"
    elif situacao == "erro":
        if modulo.startswith("asyncpg") or onde.startswith("banco/") or tipo in TIPOS_BANCO:
            origem = "banco"
        elif modulo.startswith("httpx") or onde.startswith("canal/") or (tipo or "").startswith("ErroHelena"):
            origem = "plataforma"
        elif codigo in CODIGOS_IA or modulo.startswith(("openai", "anthropic")):
            origem = "ia"
        else:
            origem = "servidor"
    de_origem = ORIGENS.get(origem or "", "origem desconhecida").lower()

    if status == "sucesso":
        causa = "Respondeu" + (" e trocou de etapa" if motivo.startswith("transferencia") else "")
    elif status == "sem_resposta":
        causa = f"A IA decidiu não responder ({motivo})" if motivo else "A IA decidiu não responder"
    elif status == "ignorado":
        causa = IGNORADOS.get(motivo) or ESTADOS_LEAD.get(motivo) or motivo
    elif status == "descartado":
        causa = DESCARTES.get(partes[0], motivo)
    elif status == "processando":
        causa = "Ainda rodando"
    elif status == "interrompido":
        causa = "O servidor reiniciou (deploy ou queda) no meio do turno" + (
            ": nada tinha saído e a IA respondeu de novo sozinha" if retomado else ": parte da resposta pode ter saído")
    elif situacao == "respondido":
        causa = f"Respondeu, mas {int(r['falhas_envio'] or 0)} parte(s) não foram enviadas pela plataforma"
    elif codigo in CODIGOS_IA:
        etapa = {"extrator": "no extrator", "etapa": "no agente", "turno": "no turno", "auditor": "no auditor"}.get(
            partes[0], f"em {partes[0]}")
        causa = (f"Tempo esgotado esperando a IA {etapa}" if status == "timeout"
                 else f"Falha da IA {etapa}: {CODIGOS_IA[codigo]}")
    elif status == "timeout":
        causa = f"Tempo esgotado ({de_origem})"
    elif status == "erro_banco":
        causa = {"BancoOcupado": "Banco ocupado: nenhuma conexão livre a tempo",
                 "TooManyConnectionsError": "Conexões do banco esgotadas",
                 "ConnectionDoesNotExistError": "A conexão com o banco caiu no meio",
                 "InterfaceError": "Conexão do banco em estado inválido"}.get(tipo or "", f"Erro no banco ({tipo})")
    elif status == "erro_5xx":
        causa = f"Erro de servidor 5xx ({de_origem})"
    elif partes[0] == "erro_interno":
        causa = f"Erro inesperado no código ({tipo})"
    else:
        causa = motivo or "Erro"
    if nova_tentativa:
        causa += ". Vai tentar de novo sozinha"
    erro = None
    if status in ERROS:
        mensagem = r["mensagem_evento"] or r["erro_ia"] or r["erro_envio"] or r["descricao_erro"]
        erro = {"tipo": tipo, "mensagem": mensagem, "onde": r["onde"], "status": _int(r["status_http"])}
    return {"status": status, "rotulo": STATUS.get(status, status), "erro_grupo": status in ERROS,
            "origem": origem, "origem_rotulo": ORIGENS.get(origem or ""), "causa": causa, "erro": erro,
            "nova_tentativa": nova_tentativa, "retomado": retomado}


def _etapas_ms(passos: Any) -> dict[str, float | None]:
    """Duração das etapas do turno (de resposta.tempos.passos_ms): contexto, IA, envio, ações depois do envio."""
    passos = _obj(passos) if passos is not None else {}
    passos = passos if isinstance(passos, dict) else {}

    def ms(*nomes: str) -> float | None:
        valores = [float(passos[n]) for n in nomes if isinstance(passos.get(n), (int, float))]
        return round(sum(valores), 1) if valores else None
    return {"contexto": ms("carregar_contexto"), "ia": ms("ia_total") or ms("extrator", "agente", "agente_correcao", "auditor"),
            "envio": ms("envio"), "acoes": ms("pos_envio"), "gravacoes": ms("gravacoes")}


# ------------------------------------------------------------------ privacidade
# "tokens_entrada"/"tokens_saida" (contagem) não são segredo; "token", "token_helena", "access_token" são.
_CHAVE_SEGREDO = re.compile(r"^(token|token_\w+|\w+_token|\w*senha\w*|\w*segredo\w*|api_?key|\w+_api_?key|chave_api"
                            r"|authorization|cookie|password|secret)$", re.I)
_CHAVE_DOCUMENTO = re.compile(r"cpf|(^|_)rg($|_)|identidade|documento_numero|numero_documento", re.I)
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_DOC_ROTULADO = re.compile(r"(?i)\b(cpf|rg|identidade)(\W{1,15})([0-9][0-9.\-/ xX]{4,18}[0-9xX])")


def _mascara_doc(valor: Any) -> str:
    texto = str(valor if valor is not None else "")
    digitos = re.sub(r"\D", "", texto)
    if not digitos:
        return texto
    return "***" + digitos[-2:] if len(digitos) > 2 else "***"


def mascarar_texto(texto: str) -> str:
    texto = _CPF.sub(lambda m: "***.***.***-" + m.group(0)[-2:], texto)
    return _DOC_ROTULADO.sub(lambda m: m.group(1) + m.group(2) + _mascara_doc(m.group(3)), texto)


def limpar(valor: Any) -> Any:
    """Cópia sem segredos e com CPF/RG mascarados (chaves de documento, fatos {chave: cpf, valor} e texto livre)."""
    if isinstance(valor, dict):
        doc = isinstance(valor.get("chave"), str) and bool(_CHAVE_DOCUMENTO.search(valor["chave"]))
        saida: dict[str, Any] = {}
        for k, v in valor.items():
            if isinstance(k, str) and _CHAVE_SEGREDO.search(k):
                saida[k] = "[oculto]"
            elif isinstance(k, str) and _CHAVE_DOCUMENTO.search(k) and not isinstance(v, (dict, list)):
                saida[k] = _mascara_doc(v)
            elif doc and k in ("valor", "trecho") and not isinstance(v, (dict, list)):
                saida[k] = _mascara_doc(v)
            else:
                saida[k] = limpar(v)
        return saida
    if isinstance(valor, list):
        return [limpar(v) for v in valor]
    if isinstance(valor, str):
        return mascarar_texto(valor)
    return valor


def mascarar_telefone(numero: str | None) -> str | None:
    d = re.sub(r"\D", "", numero or "")
    if not d:
        return None
    if len(d) >= 12 and d.startswith("55"):
        d = d[2:]
    if len(d) >= 10:
        return f"({d[:2]}) *****-{d[-4:]}"
    return "***" + d[-4:]


def _obj(valor: Any) -> Any:
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except json.JSONDecodeError:
            return valor
    return valor


def _data(texto: str | None, nome: str) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Data inválida em {nome}.") from None


def _uuid(texto: str | None, nome: str) -> str | None:
    if not texto:
        return None
    if not UUID.fullmatch(texto):
        raise HTTPException(400, f"{nome} inválido.")
    return texto


def _situacao(situacao: str, motivo: str | None) -> dict[str, Any]:
    grupo = next((g for g, lista in SITUACOES.items() if situacao in lista), situacao)
    return {"situacao": situacao, "grupo": grupo, "rotulo": ROTULO_SITUACAO.get(situacao, situacao), "motivo": motivo}


def _titulo(tipo: str) -> str:
    return TITULOS_EXTRA.get(tipo) or rastro.titulo_do_evento(tipo)


async def _nomes_por_agente(pool: Any, ids: set[str]) -> dict[str, dict[str, str]]:
    if not ids:
        return {}
    linhas = await pool.fetch("select id::text as id, config from agentesia_agentes where id = any($1::uuid[])", list(ids))
    return {r["id"]: rastro.nomes_das_etapas(rastro._obj(r["config"])) for r in linhas}


# ------------------------------------------------------------------ rotas
@api.get("/filtros")
async def filtros(pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    contas = await pool.fetch("select id::text as id, nome from agentesia_escritorios order by nome")
    agentes = await pool.fetch(
        "select id::text as id, nome, id_escritorio::text as id_escritorio from agentesia_agentes order by nome")
    return {"contas": [dict(r) for r in contas], "agentes": [dict(r) for r in agentes],
            "situacoes": [{"valor": "respondido", "rotulo": "Respondido"}, {"valor": "sem_resposta", "rotulo": "Sem resposta"},
                          {"valor": "erro", "rotulo": "Erro"}, {"valor": "processando", "rotulo": "Processando"}],
            "status": [{"valor": "erros", "rotulo": "Todos os erros"}]
                      + [{"valor": k, "rotulo": v} for k, v in STATUS.items()]}


_JUNCOES = """
  from agentesia_turnos t
  join agentesia_leads l on l.id = t.id_lead
  join agentesia_contatos ct on ct.id = l.id_contato
  join agentesia_escritorios e on e.id = t.id_escritorio
  left join agentesia_agentes a on a.id = l.id_agente
""" + _CLASSIFICACAO

_SELECT_LISTA = f"""
select * from (
select t.id::text as id, t.id_escritorio::text as id_escritorio, e.nome as conta, t.id_lead::text as id_lead,
       l.id_agente::text as id_agente, a.nome as agente, ct.nome as lead_nome, ct.telefone_normalizado as telefone,
       t.modo, t.etapa_antes, t.etapa_depois, t.situacao, t.motivo, t.iniciado_em, t.concluido_em,
       t.contexto -> 'catalogo' ->> 'transferir_para' as transferir_para,
       t.contexto -> 'catalogo' ->> 'ferramenta' as ferramenta,
       t.contexto -> 'catalogo' ->> 'ferramenta_barrada' as ferramenta_barrada,
       t.resposta -> 'tempos' -> 'passos_ms' as passos_ms,
       c.custo_brl, c.custo_usd, c.tokens_entrada, c.tokens_saida, c.chamadas, c.chamadas_falhas,
       {_COLUNAS_RESULTADO}, {_RESULTADO} as resultado
  {_JUNCOES}
  left join lateral (
       select coalesce(sum(ci.custo_brl), 0) as custo_brl, coalesce(sum(ci.custo_usd), 0) as custo_usd,
              coalesce(sum(ci.tokens_entrada), 0) as tokens_entrada, coalesce(sum(ci.tokens_saida), 0) as tokens_saida,
              count(*) as chamadas, count(*) filter (where not ci.sucesso) as chamadas_falhas
         from agentesia_chamadas_ia ci where ci.id_turno = t.id) c on true
"""


def _item(r: Any, nomes: dict[str, dict[str, str]]) -> dict[str, Any]:
    nomes_agente = nomes.get(r["id_agente"] or "", rastro.NOMES_ETAPAS)
    duracao = (int((r["concluido_em"] - r["iniciado_em"]).total_seconds() * 1000)
               if r["concluido_em"] and r["iniciado_em"] else None)
    trocou = bool(r["etapa_depois"]) and r["etapa_depois"] != r["etapa_antes"]
    ferramenta = r["ferramenta"] or None
    return {
        "id": r["id"], "iniciado_em": r["iniciado_em"].isoformat(),
        "concluido_em": r["concluido_em"].isoformat() if r["concluido_em"] else None, "duracao_ms": duracao,
        "id_escritorio": r["id_escritorio"], "conta": r["conta"], "id_agente": r["id_agente"], "agente": r["agente"],
        "id_lead": r["id_lead"], "lead": {"nome": r["lead_nome"], "telefone": mascarar_telefone(r["telefone"])},
        "modo": r["modo"],
        "etapa_antes": r["etapa_antes"], "etapa_depois": r["etapa_depois"], "trocou_etapa": trocou,
        "nome_antes": nomes_agente.get(r["etapa_antes"] or "", r["etapa_antes"]),
        "nome_depois": nomes_agente.get(r["etapa_depois"] or "", r["etapa_depois"]),
        **_situacao(r["situacao"], r["motivo"]),
        "resultado": limpar(_resultado(r)),
        "etapas_ms": _etapas_ms(r["passos_ms"]),
        "tool": {"transferir_para": r["transferir_para"] or None, "ferramenta": ferramenta,
                 "ferramenta_barrada": r["ferramenta_barrada"] or None,
                 "chamou": bool(r["transferir_para"] or ferramenta)},
        "custo": {"brl": float(r["custo_brl"] or 0), "usd": float(r["custo_usd"] or 0),
                  "tokens_entrada": int(r["tokens_entrada"] or 0), "tokens_saida": int(r["tokens_saida"] or 0),
                  "chamadas": int(r["chamadas"] or 0), "chamadas_falhas": int(r["chamadas_falhas"] or 0)},
    }


def _filtros_sql(args: list[Any], *, conta: str | None, agente: str | None, busca: str, situacao: str, troca: bool,
                 erro: bool, inicio: datetime | None, fim: datetime | None) -> list[str]:
    """Condições sobre o turno (usam os índices de agentesia_turnos); o status é filtrado por fora (é calculado)."""
    onde: list[str] = []

    def arg(valor: Any) -> str:
        args.append(valor)
        return f"${len(args)}"

    if (id_conta := _uuid(conta, "Conta")):
        onde.append(f"t.id_escritorio = {arg(id_conta)}::uuid")
    if (id_agente := _uuid(agente, "Agente")):
        onde.append(f"l.id_agente = {arg(id_agente)}::uuid")
    if situacao:
        if situacao not in SITUACOES:
            raise HTTPException(400, "Situação inválida.")
        onde.append(f"t.situacao = any({arg(SITUACOES[situacao])}::text[])")
    if erro:
        onde.append("t.situacao = 'erro'")
    if troca:
        onde.append("t.etapa_depois is not null and t.etapa_depois is distinct from t.etapa_antes")
    if inicio:
        onde.append(f"t.iniciado_em >= {arg(inicio)}")
    if fim:
        onde.append(f"t.iniciado_em < {arg(fim)}")
    busca = busca.strip()[:80]
    if busca:
        digitos = re.sub(r"\D", "", busca)
        partes = [f"ct.nome ilike {arg('%' + busca.replace('%', '').replace('_', '') + '%')}"]
        if len(digitos) >= 4:
            partes.append(f"ct.telefone_normalizado like {arg('%' + digitos + '%')}")
        if UUID.fullmatch(busca):
            partes.append(f"t.id_lead = {arg(busca)}::uuid")
        onde.append("(" + " or ".join(partes) + ")")
    return onde


def _status(status: str) -> list[str]:
    if not status:
        return []
    lista = list(ERROS) if status == "erros" else [s for s in status.split(",") if s]
    if any(s not in STATUS for s in lista):
        raise HTTPException(400, "Status inválido.")
    return lista


@api.get("")
async def listar(pedido: Request, _: Contexto = Depends(ADMIN), conta: str | None = None, agente: str | None = None,
                 busca: str = "", situacao: str = "", status: str = "", troca: bool = False, erro: bool = False,
                 de: str | None = None, ate: str | None = None, pagina: int = Query(1, ge=1, le=10_000),
                 por_pagina: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    args: list[Any] = []
    onde = _filtros_sql(args, conta=conta, agente=agente, busca=busca, situacao=situacao, troca=troca, erro=erro,
                        inicio=_data(de, "de"), fim=_data(ate, "ate"))
    sql = _SELECT_LISTA + (" where " + " and ".join(onde) if onde else "") + ") b"
    if (lista := _status(status)):
        args.append(lista)
        sql += f" where b.resultado = any(${len(args)}::text[])"
    args.extend([por_pagina + 1, (pagina - 1) * por_pagina])
    sql += f" order by b.iniciado_em desc, b.id desc limit ${len(args) - 1} offset ${len(args)}"
    linhas = await pool.fetch(sql, *args)
    tem_mais = len(linhas) > por_pagina
    linhas = linhas[:por_pagina]
    nomes = await _nomes_por_agente(pool, {r["id_agente"] for r in linhas if r["id_agente"]})
    return {"itens": [_item(r, nomes) for r in linhas], "pagina": pagina, "por_pagina": por_pagina, "tem_mais": tem_mais}


@api.get("/resumo")
async def resumo(pedido: Request, _: Contexto = Depends(ADMIN), conta: str | None = None, agente: str | None = None,
                 busca: str = "", situacao: str = "", status: str = "", troca: bool = False, erro: bool = False,
                 de: str | None = None, ate: str | None = None) -> dict[str, Any]:
    """Contadores do período e a série por hora. Tempo médio e p95: só os turnos em que a IA rodou e terminaram
    (fora os ignorados e os ainda processando). Taxa de erro: erros / (total - ignorados - processando)."""
    pool = _repo(pedido).pool
    fim = _data(ate, "ate") or datetime.now(timezone.utc)
    inicio = _data(de, "de") or fim - timedelta(hours=24)
    if fim <= inicio:
        raise HTTPException(400, "O fim do período precisa ser depois do início.")
    if fim - inicio > timedelta(days=93):
        raise HTTPException(400, "Período longo demais (máximo 93 dias).")
    por_dia = fim - inicio > timedelta(days=3)
    args: list[Any] = []
    onde = _filtros_sql(args, conta=conta, agente=agente, busca=busca, situacao=situacao, troca=troca, erro=erro,
                        inicio=inicio, fim=fim)
    filtro_status = ""
    if (lista := _status(status)):
        args.append(lista)
        filtro_status = f" where b.resultado = any(${len(args)}::text[])"
    fatia = "day" if por_dia else "hour"
    linhas = await pool.fetch(f"""
        select b.resultado, date_trunc('{fatia}', b.iniciado_em at time zone 'America/Sao_Paulo') as fatia,
               count(*) as n, sum(b.duracao_ms) as soma_ms, array_agg(b.duracao_ms) filter (where b.duracao_ms is not null) as duracoes
          from (select t.iniciado_em, {_RESULTADO} as resultado,
                       case when t.concluido_em is not null
                            then extract(epoch from (t.concluido_em - t.iniciado_em)) * 1000 end as duracao_ms
                  {_JUNCOES} where {" and ".join(onde)}) b{filtro_status}
         group by 1, 2""", *args)

    contagem = {k: 0 for k in STATUS}
    duracoes: list[float] = []
    serie: dict[datetime, dict[str, int]] = {}
    for r in linhas:
        contagem[r["resultado"]] = contagem.get(r["resultado"], 0) + int(r["n"])
        if r["resultado"] not in ("ignorado", "processando"):
            duracoes.extend(float(v) for v in (r["duracoes"] or []))
        balde = serie.setdefault(r["fatia"], {"sucesso": 0, "erros": 0, "outros": 0})
        grupo = "sucesso" if r["resultado"] == "sucesso" else "erros" if r["resultado"] in ERROS else "outros"
        balde[grupo] += int(r["n"])
    total = sum(contagem.values())
    erros = sum(contagem[k] for k in ERROS)
    rodaram = total - contagem["ignorado"] - contagem["processando"]
    duracoes.sort()
    p95 = duracoes[max(0, math.ceil(0.95 * len(duracoes)) - 1)] if duracoes else None   # posição mais próxima

    # Série contínua (horas ou dias sem execução aparecem zeradas), no horário de Brasília.
    from app.notificacoes import fuso
    brasilia = fuso()
    passo = timedelta(days=1) if por_dia else timedelta(hours=1)
    atual = inicio.astimezone(brasilia).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    if por_dia:
        atual = atual.replace(hour=0)
    ultimo = fim.astimezone(brasilia).replace(tzinfo=None)
    pontos = []
    while atual < ultimo and len(pontos) < 2500:
        valores = serie.get(atual, {"sucesso": 0, "erros": 0, "outros": 0})
        pontos.append({"inicio": atual.replace(tzinfo=brasilia).isoformat(), **valores})
        atual += passo
    return {
        "de": inicio.isoformat(), "ate": fim.isoformat(), "fatia": "dia" if por_dia else "hora",
        "total": total, "por_status": contagem, "sucesso": contagem["sucesso"], "erros": erros,
        "timeouts": contagem["timeout"], "taxa_erro": round(erros / rodaram, 4) if rodaram else 0.0,
        "tempo_medio_ms": round(sum(duracoes) / len(duracoes)) if duracoes else None,
        "p95_ms": round(p95) if p95 is not None else None, "serie": pontos,
    }


def _prompt(contexto: Any) -> dict[str, Any]:
    """O que foi ao modelo: o sistema e o conteúdo da etapa (a última tentativa), o extrator e as tentativas."""
    if not isinstance(contexto, dict):
        return {"sistema": None, "conteudo": str(contexto) if contexto else None, "resposta_bruta": None,
                "extrator": None, "tentativas": [], "barreira": None}
    etapa = contexto.get("etapa") if isinstance(contexto.get("etapa"), dict) else {}
    extrator = contexto.get("extrator") if isinstance(contexto.get("extrator"), dict) else None

    def texto(v: Any) -> str | None:
        if v is None:
            return None
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2, default=str)

    return {
        "sistema": texto(etapa.get("sistema")), "conteudo": texto(etapa.get("conteudo")),
        "resposta_bruta": etapa.get("resposta"),
        "extrator": {"conteudo": texto(extrator.get("conteudo")), "resposta": extrator.get("resposta")} if extrator else None,
        "tentativas": contexto.get("tentativas") or [], "barreira": contexto.get("barreira"),
        "auditor": contexto.get("auditor"),
    }


@api.get("/{id_turno}")
async def detalhe(id_turno: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    _uuid(id_turno, "Execução")
    pool = _repo(pedido).pool
    r = await pool.fetchrow(_SELECT_LISTA + " where t.id = $1::uuid) b", id_turno)
    if not r:
        raise HTTPException(404, "Execução não encontrada.")
    linha = await pool.fetchrow("select contexto, resposta from agentesia_turnos where id = $1::uuid", id_turno)
    nomes = await _nomes_por_agente(pool, {r["id_agente"]} if r["id_agente"] else set())
    item = _item(r, nomes)
    contexto = _obj(linha["contexto"])
    resposta = _obj(linha["resposta"]) if linha["resposta"] is not None else {}
    resposta = resposta if isinstance(resposta, dict) else {"bruto": resposta}

    mensagens = [dict(m) for m in await pool.fetch(
        """select id::text as id, autor, tipo, texto, texto_extraido, url_midia, enviada_em, situacao_envio, erro
             from agentesia_mensagens where id_lead = $1::uuid and id_turno = $2::uuid order by enviada_em, registrada_em""",
        r["id_lead"], id_turno)]
    for m in mensagens:
        m["enviada_em"] = m["enviada_em"].isoformat()
    eventos = []
    for e in await pool.fetch(
            """select tipo, gravidade, responsavel, descricao, detalhe, criado_em from agentesia_eventos
                where id_lead = $1::uuid and id_turno = $2::uuid order by criado_em""", r["id_lead"], id_turno):
        eventos.append({"tipo": e["tipo"], "titulo": _titulo(e["tipo"]), "gravidade": e["gravidade"],
                        "responsavel": e["responsavel"], "descricao": e["descricao"],
                        "detalhe": rastro._obj(e["detalhe"]), "criado_em": e["criado_em"].isoformat(),
                        "trava": e["tipo"] in TRAVAS or (rastro.tipo_do_evento(e["tipo"]) in ("recusa", "barreira"))})
    chamadas = [{**dict(c), "custo_usd": float(c["custo_usd"] or 0), "custo_brl": float(c["custo_brl"] or 0),
                 "criado_em": c["criado_em"].isoformat()} for c in await pool.fetch(
        """select papel, modelo, tokens_entrada, tokens_saida, tokens_cache, custo_usd, custo_brl, duracao_ms, sucesso,
                  erro, criado_em from agentesia_chamadas_ia where id_turno = $1::uuid order by criado_em""", id_turno)]
    anterior, seguinte = await pool.fetchval(
        """select id::text from agentesia_turnos where id_lead = $1::uuid and (iniciado_em, id) < ($2, $3::uuid)
            order by iniciado_em desc, id desc limit 1""", r["id_lead"], r["iniciado_em"], id_turno), await pool.fetchval(
        """select id::text from agentesia_turnos where id_lead = $1::uuid and (iniciado_em, id) > ($2, $3::uuid)
            order by iniciado_em, id limit 1""", r["id_lead"], r["iniciado_em"], id_turno)

    acoes = [{"tipo": a["tipo"], "situacao": a["situacao"], "tentativas": a["tentativas"], "erro": a["erro"],
               "criado_em": a["criado_em"].isoformat(), "atualizado_em": a["atualizado_em"].isoformat(),
               "duracao_ms": int((a["atualizado_em"] - a["criado_em"]).total_seconds() * 1000)
               if a["situacao"] in ("feita", "falhou", "cancelada") else None}
              for a in await pool.fetch(
                  """select tipo, situacao, tentativas, erro, criado_em, atualizado_em from agentesia_acoes
                      where id_turno = $1::uuid order by criado_em""", id_turno)]
    # Tentativa deste turno: 1 + os turnos logo antes dele, do mesmo lead, que fecharam pedindo nova tentativa.
    antes = await pool.fetch(
        """select motivo from agentesia_turnos where id_lead = $1::uuid and (iniciado_em, id) < ($2, $3::uuid)
            order by iniciado_em desc, id desc limit 5""", r["id_lead"], r["iniciado_em"], id_turno)
    tentativa = 1
    for t in antes:
        if not (t["motivo"] or "").endswith(":nova_tentativa"):
            break
        tentativa += 1
    tentativas = {"turno": tentativa, "chamadas_ia": len(chamadas),
                  "chamadas_ia_falharam": sum(1 for c in chamadas if not c["sucesso"]),
                  "acoes_repetidas": sum(max(0, int(a["tentativas"] or 0) - 1) for a in acoes)}

    catalogo = contexto.get("catalogo") if isinstance(contexto, dict) and isinstance(contexto.get("catalogo"), dict) else {}
    decisao = {
        "transferir_para": catalogo.get("transferir_para") or None, "ferramenta": catalogo.get("ferramenta") or None,
        "ferramenta_barrada": catalogo.get("ferramenta_barrada"), "origem_destino": catalogo.get("origem_destino"),
        "notificacao": catalogo.get("notificacao") or None, "destinos": catalogo.get("destinos") or [],
        "acoes": catalogo.get("acoes") or [],
        "intencoes": resposta.get("intencoes") or {}, "fatos_novos": resposta.get("fatos_novos") or [],
        "fatos_rejeitados": resposta.get("fatos_rejeitados") or [], "reprovacoes": resposta.get("reprovacoes") or [],
        "decisoes": resposta.get("decisoes") or [], "faltam": resposta.get("faltam") or [],
        "sinais": resposta.get("sinais") or [], "estado_lead": resposta.get("estado_lead"),
        "motivo_estado": resposta.get("motivo_estado"), "ficha": resposta.get("ficha"),
    }
    return limpar({
        **item,
        "entrada": [m for m in mensagens if m["autor"] == "lead"],
        "saida": [m for m in mensagens if m["autor"] != "lead"],
        "mensagens_planejadas": resposta.get("mensagens") or [],
        "prompt": _prompt(contexto),
        "decisao": decisao,
        "eventos": eventos,
        "travas": [e for e in eventos if e["trava"]],
        "tempos": resposta.get("tempos"),
        "chamadas": chamadas,
        "acoes_turno": acoes,
        "tentativas": tentativas,
        "linha_do_tempo": _linha_do_tempo(item, mensagens, eventos, chamadas, acoes, resposta.get("tempos")),
        "navegacao": {"anterior": anterior, "seguinte": seguinte},
    })


_MARCAS = {"primeira_parte_enviada": "Primeira parte chegou à plataforma"}


def _linha_do_tempo(item: dict[str, Any], mensagens: list[dict[str, Any]], eventos: list[dict[str, Any]],
                    chamadas: list[dict[str, Any]], acoes: list[dict[str, Any]], tempos: Any) -> list[dict[str, Any]]:
    """O que aconteceu no turno, em ordem: começo, mensagens, chamadas de IA, eventos, ações e o fim, com o tempo desde o
    começo (ms). As chamadas de IA ficam na hora em que foram gravadas (perto do fim da IA), com a duração ao lado."""
    inicio = datetime.fromisoformat(item["iniciado_em"])
    pontos: list[dict[str, Any]] = []

    def ponto(em: str | datetime, tipo: str, titulo: str, texto: str | None = None, estado: str = "info",
              duracao_ms: float | None = None) -> None:
        quando = em if isinstance(em, datetime) else datetime.fromisoformat(em)
        pontos.append({"em": quando.isoformat(), "ms": int((quando - inicio).total_seconds() * 1000), "tipo": tipo,
                       "titulo": titulo, "texto": texto, "estado": estado, "duracao_ms": duracao_ms})

    ponto(inicio, "inicio", "Turno começou")
    for m in mensagens:
        trecho = (m["texto"] or m["texto_extraido"] or m["tipo"] or "")[:120]
        if m["autor"] == "lead":
            ponto(m["enviada_em"], "lead", "Mensagem do lead", trecho)
        else:
            falhou = m["situacao_envio"] == "falhou"
            ponto(m["enviada_em"], "envio", "Envio falhou" if falhou else "Mensagem enviada" if m["situacao_envio"] == "enviada"
                  else "Envio sem confirmação", (m["erro"] + ": " if falhou and m["erro"] else "") + trecho,
                  "bad" if falhou else "ok" if m["situacao_envio"] == "enviada" else "warn")
    fim = datetime.fromisoformat(item["concluido_em"]) if item["concluido_em"] else None
    for c in chamadas:                               # gravada depois do fim (turno que quebrou): fica no fim
        em = datetime.fromisoformat(c["criado_em"])
        ponto(min(em, fim) if fim else em, "ia", f"IA: {c['papel']} ({c['modelo']})", c["erro"] if not c["sucesso"] else None,
              "ok" if c["sucesso"] else "bad", c["duracao_ms"])
    for e in eventos:
        ponto(e["criado_em"], "evento", e["titulo"], e["descricao"],
              "bad" if e["gravidade"] in ("erro", "critico") else "warn" if e["gravidade"] == "aviso" else "info")
    for a in acoes:
        ponto(a["criado_em"], "acao", f"Ação {a['tipo']} pedida")
        if a["duracao_ms"] is not None:
            ponto(a["atualizado_em"], "acao", f"Ação {a['tipo']}: {a['situacao']}"
                  + (f" ({a['tentativas']} tentativas)" if (a["tentativas"] or 0) > 1 else ""), a["erro"],
                  "ok" if a["situacao"] == "feita" else "bad" if a["situacao"] == "falhou" else "warn", a["duracao_ms"])
    marcas = tempos.get("marcas_ms") if isinstance(tempos, dict) and isinstance(tempos.get("marcas_ms"), dict) else {}
    for nome, ms in marcas.items():
        if isinstance(ms, (int, float)):
            ponto(inicio + timedelta(milliseconds=ms), "marca", _MARCAS.get(nome, nome.replace("_", " ")))
    if item["concluido_em"]:
        resultado = item["resultado"]
        ponto(item["concluido_em"], "fim", f"Turno terminou: {resultado['rotulo']}", resultado["causa"],
              "bad" if resultado["erro_grupo"] else "ok" if resultado["status"] == "sucesso" else "info",
              item["duracao_ms"])
    pontos.sort(key=lambda p: (p["ms"], p["tipo"] == "fim"))
    return pontos
