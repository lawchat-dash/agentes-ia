"""Troca de etapa (de agente) feita pela EQUIPE: pelo painel da LawChat ou movendo o card no CRM da Helena.

A troca feita pela IA (campo `transferir_para` da resposta, ou a frase de passagem) mora no turno e no pipeline. Aqui
ficam as duas trocas que vêm de fora da conversa:

1. Painel (POST /api/conversas/{id}/ia, acao trocar_etapa): a equipe escolhe a etapa; o card vai junto pela fila.
2. CRM da Helena (webhook PANEL_CARD_STEP_CHANGE): a equipe arrastou o card para outra coluna; o lead passa para a
   etapa ligada àquela coluna (automação "etapa:<codigo>" do agente) e o próximo turno já responde com o agente dela.
   No n8n isso não existia: mover o card na Helena não mudava o agente.

As duas usam `trocar_pela_equipe`: grava a etapa num comando só (só muda se ainda não estava nela), deixa o histórico
(agentesia_lead_etapas com a origem, evento 'etapa_trocada'), a marca das boas-vindas do agente novo e as automações
do gatilho 'etapa:<codigo>' (etiquetas, nota, aviso e, no painel, o card).

Proteções contra laço e troca dupla no webhook do card:
- o card que NÓS movemos também gera PANEL_CARD_STEP_CHANGE: se o lead já está na etapa da coluna, nada muda
  ('ja_estava'); se o lead já seguiu adiante e o aviso chegou atrasado, a mudança que nós mesmos pedimos nos últimos
  10 minutos para aquela coluna é reconhecida ('eco_do_sistema') e o lead não volta;
- o mesmo aviso repetido pela Helena entra uma vez só (agentesia_eventos_recebidos);
- dois avisos ao mesmo tempo: a troca é um UPDATE condicional (só um deles muda a etapa e põe as ações na fila);
- o webhook nunca move o card de volta (ele já está na coluna): a ação 'mover_card' sai da lista.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from app import automacoes

EVENTO_CARD = "PANEL_CARD_STEP_CHANGE"
JANELA_DO_ECO_MIN = 10          # mudança de coluna pedida por nós há menos disto = aviso da nossa própria mudança


def _json(valor: Any) -> dict[str, Any]:
    if isinstance(valor, dict):
        return valor
    try:
        return json.loads(valor or "{}") if isinstance(valor, str) else {}
    except ValueError:
        return {}


async def _boas_vindas_do_agente_novo(pool: asyncpg.Pool, id_escritorio: str, id_lead: str, codigo: str,
                                      config_agente: dict[str, Any], quem: str) -> None:
    """Papel de destino (catálogo) com boas-vindas: grava a mesma marca que a troca feita pela IA grava, para o agente
    novo se apresentar na primeira resposta depois da troca. Sem ela, na troca pela equipe ele entrava calado."""
    from types import SimpleNamespace

    from app.banco.postgres import RepositorioPostgres
    from app.cerebro.turno import MARCA_BOAS_VINDAS

    papel = ((config_agente.get("catalogo") or {}).get("papeis") or {}).get(codigo)
    if not isinstance(papel, dict) or not str(papel.get("boas_vindas") or "").strip():
        return
    await RepositorioPostgres(pool).gravar_fatos(
        lead=SimpleNamespace(id=id_lead, id_escritorio=id_escritorio), id_turno=None,
        fatos=[{"chave": MARCA_BOAS_VINDAS, "valor": codigo, "trecho": f"(troca pela equipe, {quem})", "fonte": "sistema"}])


async def trocar_pela_equipe(pool: asyncpg.Pool, *, id_escritorio: str, id_lead: str, de: str | None, codigo: str,
                             config_agente: dict[str, Any], origem: str, quem: str, id_usuario: str | None = None,
                             mover_card: bool = True, detalhe: dict[str, Any] | None = None) -> bool:
    """Põe o lead na etapa `codigo` e dispara o que a troca dispara. Falso se ele já estava nela (nada é feito).

    origem: 'equipe' (painel) ou 'equipe_crm' (card movido na Helena). mover_card=False quando o card já está na
    coluna (webhook do card): mover de novo geraria outro aviso igual da Helena."""
    from app.contrato import servico as contrato_servico

    if not await contrato_servico.mover_lead_para_etapa(pool, id_lead, codigo, origem=origem):
        return False
    await pool.execute(
        """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
           values ($1::uuid, $2::uuid, 'etapa_trocada', 'info', 'cliente', $3, $4::jsonb)""",
        id_escritorio, id_lead, f"Etapa do lead: {de or '-'} → {codigo} ({quem}).",
        json.dumps({"de": de, "para": codigo, "origem": origem, "id_usuario": id_usuario, **(detalhe or {})},
                   ensure_ascii=False))
    await _boas_vindas_do_agente_novo(pool, id_escritorio, id_lead, codigo, config_agente, quem)
    crm = _json(await pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio))
    avisos = {r["tipo_evento"] for r in await pool.fetch(
        "select tipo_evento from agentesia_notificacoes where id_escritorio = $1::uuid and habilitada", id_escritorio)}
    marca = uuid.uuid4().hex[:8]
    acoes = automacoes.montar_acoes(config_agente, crm, [f"etapa:{codigo}"], id_lead=id_lead,
                                    id_turno=f"{origem}-{marca}", avisos=avisos)
    for acao in acoes:
        if acao["tipo"] == "mover_card" and not mover_card:
            continue
        await pool.execute(
            """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
               values ($1::uuid, $2::uuid, $3, $4, $5::jsonb) on conflict (chave_unica) do nothing""",
            id_escritorio, id_lead, acao["tipo"], acao["chave_unica"], json.dumps(acao["dados"], ensure_ascii=False))
    return True


# ---------------------------------------------------------------------------- card movido na Helena
def ler_evento_de_card(corpo: dict[str, Any]) -> dict[str, Any] | None:
    """PANEL_CARD_STEP_CHANGE em qualquer dos formatos prováveis (o corpo não é documentado pela Helena): o card no
    próprio `content` ou em `content.card`, a coluna nova em stepId/newStepId/step.id. None = não é desse evento."""
    if str(corpo.get("eventType") or "").upper() != EVENTO_CARD:
        return None
    conteudo = corpo.get("content") if isinstance(corpo.get("content"), dict) else {}
    card = conteudo.get("card") if isinstance(conteudo.get("card"), dict) else conteudo
    passo = card.get("step") if isinstance(card.get("step"), dict) else {}
    painel = card.get("panel") if isinstance(card.get("panel"), dict) else {}
    contatos = card.get("contactIds") or conteudo.get("contactIds") or []
    return {
        "id_card": str(card.get("id") or conteudo.get("cardId") or card.get("cardId") or "") or None,
        "id_etapa": str(conteudo.get("newStepId") or card.get("stepId") or passo.get("id") or conteudo.get("stepId")
                        or conteudo.get("currentStepId") or "") or None,
        "id_painel": str(card.get("panelId") or painel.get("id") or conteudo.get("panelId") or "") or None,
        "id_conta": str(conteudo.get("companyId") or card.get("companyId") or "") or None,
        "id_sessao": str(card.get("sessionId") or conteudo.get("sessionId") or "") or None,
        "id_contato": str(contatos[0]) if isinstance(contatos, list) and contatos else None,
        "quando": str(corpo.get("date") or card.get("updatedAt") or conteudo.get("updatedAt") or "") or None,
    }


def etapas_da_coluna(config_agente: dict[str, Any], id_coluna: str, etapa_inicial: str | None) -> list[str]:
    """Etapas do agente ligadas a esta coluna do CRM: 'etapa:<codigo>' com coluna_crm igual e o lead novo (coluna da
    etapa inicial). Mais de uma = coluna compartilhada (ex.: Período de Graça na coluna do SDR)."""
    etapas: list[str] = []
    for gatilho, regra in (config_agente.get("automacoes") or {}).items():
        if not isinstance(regra, dict) or str(regra.get("coluna_crm") or "") != id_coluna:
            continue
        codigo = gatilho.split(":", 1)[1] if gatilho.startswith("etapa:") else etapa_inicial if gatilho == "lead_novo" else None
        if codigo and codigo not in etapas:
            etapas.append(codigo)
    return etapas


_SELECT_LEAD = """select l.id, l.estado, l.id_agente, et.codigo as etapa, ag.config as config_agente,
                         cc.id_card_helena, cc.id_painel_helena,
                         (select e2.codigo from agentesia_agente_etapas e2 where e2.id_agente = l.id_agente and e2.principal
                          order by e2.ordem limit 1) as etapa_inicial
                  from agentesia_leads l
                  left join agentesia_agente_etapas et on et.id = l.id_etapa
                  left join agentesia_agentes ag on ag.id = l.id_agente
                  left join agentesia_crm_cards cc on cc.id_lead = l.id"""


async def _lead_do_card(pool: asyncpg.Pool, id_escritorio: str, evento: dict[str, Any]) -> dict[str, Any] | None:
    """Pelo card guardado; sem ele, pelo atendimento do card ou pelo contato (lead mais recente não encerrado)."""
    linha = await pool.fetchrow(_SELECT_LEAD + " where l.id_escritorio = $1::uuid and cc.id_card_helena = $2",
                                id_escritorio, evento["id_card"])
    if not linha and evento["id_sessao"]:
        linha = await pool.fetchrow(
            _SELECT_LEAD + """ where l.id_escritorio = $1::uuid and l.id_sessao_helena = $2 and l.estado <> 'encerrado'
                               order by l.criado_em desc limit 1""", id_escritorio, evento["id_sessao"])
    if not linha and evento["id_contato"]:
        linha = await pool.fetchrow(
            _SELECT_LEAD + """ join agentesia_contatos c on c.id = l.id_contato
                               where l.id_escritorio = $1::uuid and c.id_contato_helena = $2 and l.estado <> 'encerrado'
                               order by l.criado_em desc limit 1""", id_escritorio, evento["id_contato"])
    return dict(linha) if linha else None


async def receber_evento_de_card(pool: asyncpg.Pool, id_escritorio: str, corpo: dict[str, Any]) -> dict[str, Any] | None:
    """Webhook PANEL_CARD_STEP_CHANGE: a equipe moveu o card de coluna na Helena. None = não é esse evento."""
    evento = ler_evento_de_card(corpo)
    if evento is None:
        return None
    if not evento["id_card"] or not evento["id_etapa"]:
        return {"feito": "ignorado", "motivo": "card_sem_coluna"}
    conta = await pool.fetchval("select id_conta_helena::text from agentesia_escritorios where id = $1::uuid", id_escritorio)
    # Isolamento: veio a conta no evento, tem de ser a do escritório (escritório sem conta cadastrada também recusa).
    if evento["id_conta"] and evento["id_conta"].strip().lower() != str(conta or "").lower():
        return {"feito": "ignorado", "motivo": "conta_de_outro_escritorio"}
    quando = evento["quando"] or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    recebido = await pool.fetchval(
        """insert into agentesia_eventos_recebidos (id_escritorio, origem, id_externo, tipo, payload)
           values ($1::uuid, 'helena', $2, $3, $4::jsonb) on conflict (origem, id_externo) do nothing returning id""",
        id_escritorio, f"card_step:{evento['id_card']}:{evento['id_etapa']}:{quando}", EVENTO_CARD,
        json.dumps(corpo, ensure_ascii=False, default=str))
    if not recebido:
        return {"feito": "ignorado", "motivo": "repetido"}
    await _espelho_do_card(pool, id_escritorio, evento)
    resultado = await _mudou_de_coluna(pool, id_escritorio, evento)
    await pool.execute(
        """update agentesia_eventos_recebidos set situacao = $2, motivo = $3, processado_em = now() where id = $1""",
        recebido, "processado" if resultado["feito"] == "trocado" else "ignorado", resultado.get("motivo"))
    return resultado


async def _espelho_do_card(pool: asyncpg.Pool, id_escritorio: str, evento: dict[str, Any]) -> None:
    """Relatórios: o card já espelhado (agentesia_crm_espelho, migração 012) passa para a coluna nova na hora, sem
    esperar a varredura. Nome e fase da coluna vêm de outro card já visto nela; o resto a varredura completa."""
    try:
        await pool.execute(
            """update agentesia_crm_espelho e set id_etapa_helena = $3,
                      etapa_titulo = coalesce(o.etapa_titulo, e.etapa_titulo), fase = coalesce(o.fase, e.fase),
                      atualizado_em_helena = now(), visto_em = now()
                 from (select (select x.etapa_titulo from agentesia_crm_espelho x where x.id_escritorio = $1::uuid
                                  and x.id_etapa_helena = $3 and x.etapa_titulo is not null limit 1) as etapa_titulo,
                              (select x.fase from agentesia_crm_espelho x where x.id_escritorio = $1::uuid
                                  and x.id_etapa_helena = $3 and x.fase is not null limit 1) as fase) o
                where e.id_escritorio = $1::uuid and e.id_card_helena = $2 and e.id_etapa_helena is distinct from $3""",
            id_escritorio, evento["id_card"], evento["id_etapa"])
    except asyncpg.UndefinedTableError:                    # banco sem a 012: relatórios sem espelho
        pass


async def _mudou_de_coluna(pool: asyncpg.Pool, id_escritorio: str, evento: dict[str, Any]) -> dict[str, Any]:
    lead = await _lead_do_card(pool, id_escritorio, evento)
    if not lead:
        return {"feito": "ignorado", "motivo": "card_sem_lead"}
    id_lead = str(lead["id"])
    base = {"id_lead": id_lead}
    if lead["id_card_helena"] and lead["id_card_helena"] != evento["id_card"]:
        # O lead já tem outro card guardado (card repetido na Helena): mexer nele pelo outro bagunçaria o espelho.
        return {**base, "feito": "ignorado", "motivo": "outro_card_do_lead"}
    crm = _json(await pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio))
    if evento["id_painel"] and crm.get("id_painel") and evento["id_painel"] != crm["id_painel"]:
        return {**base, "feito": "ignorado", "motivo": "outro_painel"}
    # Espelho do card: a coluna onde ele está agora (vale também quando a etapa não muda).
    await pool.execute(
        """insert into agentesia_crm_cards (id_escritorio, id_lead, id_card_helena, id_painel_helena, id_etapa_helena,
                                            situacao, sincronizado_em)
           values ($1::uuid, $2::uuid, $3, $4, $5, 'ok', now())
           on conflict (id_lead) do update set id_etapa_helena = excluded.id_etapa_helena,
             id_painel_helena = coalesce(excluded.id_painel_helena, agentesia_crm_cards.id_painel_helena),
             situacao = 'ok', erro = null, sincronizado_em = now(), atualizado_em = now()""",
        id_escritorio, id_lead, evento["id_card"], evento["id_painel"] or crm.get("id_painel"), evento["id_etapa"])
    config = automacoes.config_efetiva(_json(lead["config_agente"]), crm)   # CRM automático: colunas fixas da conta
    if config.get("seguir_coluna_do_crm") is False:
        return {**base, "feito": "ignorado", "motivo": "seguir_coluna_desligado"}
    etapas = etapas_da_coluna(config, evento["id_etapa"], lead["etapa_inicial"])
    if not etapas:
        return {**base, "feito": "ignorado", "motivo": "coluna_sem_etapa"}
    if lead["etapa"] in etapas:
        return {**base, "feito": "ignorado", "motivo": "ja_estava"}          # inclui o aviso do card que nós movemos
    if len(etapas) > 1:
        return {**base, "feito": "ignorado", "motivo": "coluna_de_varias_etapas"}
    if lead["etapa"] == "contrato_assinado" or lead["estado"] == "encerrado":
        return {**base, "feito": "ignorado", "motivo": "lead_encerrado"}
    destino = etapas[0]
    eco = await pool.fetchval(
        """select exists(select 1 from agentesia_acoes where id_lead = $1::uuid and tipo = 'mover_card'
                         and dados->>'id_etapa_helena' = $2 and situacao in ('feita', 'executando')
                         and criado_em > now() - make_interval(mins => $3))""",
        id_lead, evento["id_etapa"], JANELA_DO_ECO_MIN)
    if eco:
        # Aviso atrasado do card que NÓS movemos (o lead já seguiu adiante): voltar o lead seria a troca dupla.
        await pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1::uuid, $2::uuid, 'card_eco_ignorado', 'info', 'lawchat', $3, $4::jsonb)""",
            id_escritorio, id_lead,
            f"A Helena avisou que o card foi para a coluna de {destino}, mas essa mudança foi pedida pela LawChat e o "
            f"lead já está em {lead['etapa']}: a etapa não voltou.",
            json.dumps({"coluna": evento["id_etapa"], "etapa_da_coluna": destino, "etapa_atual": lead["etapa"]}))
        return {**base, "feito": "ignorado", "motivo": "eco_do_sistema"}
    trocou = await trocar_pela_equipe(
        pool, id_escritorio=id_escritorio, id_lead=id_lead, de=lead["etapa"], codigo=destino, config_agente=config,
        origem="equipe_crm", quem="equipe, movendo o card no CRM da Helena", mover_card=False,
        detalhe={"id_card": evento["id_card"], "coluna": evento["id_etapa"]})
    if not trocou:
        return {**base, "feito": "ignorado", "motivo": "ja_estava"}
    return {**base, "feito": "trocado", "de": lead["etapa"], "para": destino}
