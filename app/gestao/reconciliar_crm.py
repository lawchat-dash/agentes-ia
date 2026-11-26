"""Reconciliação leve do CRM: varre os cards do painel do CRM de cada conta e guarda só o que mudou.

O caminho principal continua sendo o webhook (PANEL_CARD_STEP_CHANGE em app/troca_etapa.py). Esta varredura cobre o
que escapa: card movido sem aviso, aviso perdido e os cards antigos, de antes da integração.

  - roda no app "ia", em segundo plano (laço em app/main.py), a cada INTERVALO_S; nunca na abertura de uma tela;
  - incremental: pede os cards do painel ordenados pela última atualização (mais novos primeiro) e para na primeira
    página que já é toda mais velha que o ponto da varredura anterior (agentesia_crm_varredura.cursor_atualizado);
  - importação única: na primeira vez (ou quando o painel pede de novo em Relatórios) percorre o painel inteiro, até
    PAGINAS_IMPORTACAO páginas, com uma pausa curta entre elas para não gastar a cota da conta (que é dividida com o
    atendimento);
  - percorre TODOS os painéis da conta (o Dashboard filtra por painel), não só o painel escolhido para a IA;
  - grava em agentesia_crm_espelho (um registro por card, só quando algo mudou; desde a 013 também painel, responsável,
    etiquetas, atendimento e o número do canal do lead ligado) e, nos leads que já têm card ligado
    em agentesia_crm_cards, atualiza só a coluna do card quando ela mudou. Não cria card, não move card, não troca a
    etapa do lead e não dispara automação: o espelho é para os relatórios.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.gestao.rotas_relatorios import fase_do_titulo

# Tipo da coluna do painel de colunas fixas (onboarding, config do CRM "etapas_por_tipo") -> fase do Dashboard.
FASE_DO_TIPO = {"SDR": "sdr", "COMERCIAL": "closer", "CONTRATO": "contratos", "AGUARDANDO_ASSINATURA": "assinatura",
                "CONTRATO_ASSINADO": "assinado", "DESQUALIFICADO": "desqualificado"}


def fase_do_card(id_etapa: str | None, titulo: str | None, etapas_por_tipo: dict[str, str] | None = None) -> str:
    """Fase da coluna: pelo tipo marcado na configuração do CRM; sem ele, pelo nome da coluna."""
    for tipo, coluna in (etapas_por_tipo or {}).items():
        if id_etapa and str(coluna) == str(id_etapa) and tipo in FASE_DO_TIPO:
            return FASE_DO_TIPO[tipo]
    return fase_do_titulo(titulo)

log = logging.getLogger("agentesia")

INTERVALO_S = 15 * 60          # varredura incremental de cada conta
CHECAR_PEDIDOS_S = 60          # importação pedida pelo painel começa em até 1 min
POR_PAGINA = 100
PAGINAS_INCREMENTAL = 5
PAGINAS_IMPORTACAO = 300       # até 30 mil cards por conta na importação
PAUSA_ENTRE_PAGINAS_S = 0.4
MARGEM = timedelta(minutes=5)  # relógio da plataforma x o nosso


def _data(valor: Any) -> datetime | None:
    if not valor or not isinstance(valor, str):
        return None
    try:
        d = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def ler_card(card: dict[str, Any]) -> dict[str, Any] | None:
    id_card = card.get("id")
    if not id_card:
        return None
    contatos = card.get("contactIds") or [c.get("id") for c in card.get("contacts") or [] if isinstance(c, dict)]
    passo = card.get("step") if isinstance(card.get("step"), dict) else {}
    valor = card.get("monetaryAmount")
    try:
        valor = round(float(valor), 2) if valor not in (None, "") else None
    except (TypeError, ValueError):
        valor = None
    status = str(card.get("status") or "").upper()
    resp = card.get("responsibleUser")
    if isinstance(resp, dict):
        resp_nome = resp.get("name") or resp.get("fullName") or resp.get("displayName") or resp.get("email")
        resp_id = card.get("responsibleUserId") or resp.get("id")
    else:
        resp_nome, resp_id = (resp if isinstance(resp, str) else None), card.get("responsibleUserId")
    etiquetas = card.get("tagIds") or [t.get("id") for t in card.get("tags") or [] if isinstance(t, dict)]
    painel = card.get("panel") if isinstance(card.get("panel"), dict) else {}
    return {
        "id_card": str(id_card), "id_painel": str(card.get("panelId") or "") or None,
        "id_etapa": str(card.get("stepId") or passo.get("id") or "") or None,
        "etapa_titulo": card.get("stepTitle") or passo.get("title"),
        "id_contato": str(contatos[0]) if contatos and contatos[0] else None,
        "titulo": (card.get("title") or "")[:300] or None, "valor": valor,
        "arquivado": bool(card.get("archived")) or status in ("ARCHIVED", "DELETED"),
        "criado_em": _data(card.get("createdAt")), "atualizado_em": _data(card.get("updatedAt")),
        "titulo_painel": card.get("panelTitle") or painel.get("title"),
        "fase_helena": str(card.get("stepPhase") or passo.get("phase") or "") or None,
        "situacao": status or None,
        "id_responsavel": str(resp_id) if resp_id else None,
        "responsavel_nome": (str(resp_nome)[:200] if resp_nome else None),
        "ids_etiquetas": [str(t) for t in etiquetas if t],
        "id_sessao": str(card.get("sessionId") or "") or None,
    }


async def listar_cards(helena: Any, id_painel: str, pagina: int, por_pagina: int | None = None) -> tuple[list[dict[str, Any]], bool]:
    """Uma página dos cards do painel (mais recentes primeiro). Usa o mesmo cliente das outras chamadas do CRM."""
    por_pagina = por_pagina or POR_PAGINA
    dados = await helena._pedir("GET", "crm/v2/panel/card", params={
        "PanelId": id_painel, "PageSize": por_pagina, "PageNumber": pagina,
        "OrderBy": "updatedAt", "OrderDirection": "DESCENDING"}) or {}
    itens = dados.get("items", dados.get("data", [])) if isinstance(dados, dict) else (dados if isinstance(dados, list) else [])
    mais = dados.get("hasMorePages", dados.get("hasNextPage")) if isinstance(dados, dict) else None
    if mais is None:
        mais = len(itens) >= por_pagina
    return [c for c in itens if isinstance(c, dict)], bool(mais) and bool(itens)


_GRAVAR = """
with alvo as (
  select coalesce((select cc.id_lead from agentesia_crm_cards cc where cc.id_escritorio = $1::uuid and cc.id_card_helena = $2),
                  (select l.id from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
                    where l.id_escritorio = $1::uuid and $7::text is not null and c.id_contato_helena = $7
                    order by l.criado_em desc limit 1)) as id_lead
)
insert into agentesia_crm_espelho (id_escritorio, id_card_helena, id_painel_helena, id_etapa_helena, etapa_titulo, fase,
                                   id_contato_helena, id_lead, titulo, valor, arquivado, criado_em_helena,
                                   atualizado_em_helena, visto_em, titulo_painel, fase_helena, situacao_helena,
                                   id_responsavel, responsavel_nome, ids_etiquetas, etiquetas, id_sessao_helena, numero_canal)
select $1::uuid, $2, $3, $4, $5, $6, $7, alvo.id_lead, $8, $9, $10, $11, $12, now(), $13, $14, $15, $16, $17,
       coalesce($18::text[], '{}'), coalesce($19::text[], '{}'), $20,
       (select k.numero_normalizado from agentesia_leads l join agentesia_canais k on k.id = l.id_canal where l.id = alvo.id_lead)
  from alvo
on conflict (id_escritorio, id_card_helena) do update set
  id_painel_helena = excluded.id_painel_helena, id_etapa_helena = excluded.id_etapa_helena,
  etapa_titulo = excluded.etapa_titulo, fase = excluded.fase, id_contato_helena = excluded.id_contato_helena,
  id_lead = coalesce(excluded.id_lead, agentesia_crm_espelho.id_lead), titulo = excluded.titulo, valor = excluded.valor,
  arquivado = excluded.arquivado, criado_em_helena = coalesce(excluded.criado_em_helena, agentesia_crm_espelho.criado_em_helena),
  atualizado_em_helena = excluded.atualizado_em_helena, visto_em = now(),
  titulo_painel = coalesce(excluded.titulo_painel, agentesia_crm_espelho.titulo_painel),
  fase_helena = excluded.fase_helena, situacao_helena = excluded.situacao_helena,
  id_responsavel = excluded.id_responsavel, responsavel_nome = excluded.responsavel_nome,
  ids_etiquetas = excluded.ids_etiquetas, etiquetas = excluded.etiquetas,
  id_sessao_helena = coalesce(excluded.id_sessao_helena, agentesia_crm_espelho.id_sessao_helena),
  numero_canal = coalesce(excluded.numero_canal, agentesia_crm_espelho.numero_canal)
where (agentesia_crm_espelho.id_etapa_helena, agentesia_crm_espelho.etapa_titulo, agentesia_crm_espelho.fase,
       agentesia_crm_espelho.arquivado, agentesia_crm_espelho.titulo, agentesia_crm_espelho.valor,
       agentesia_crm_espelho.atualizado_em_helena, agentesia_crm_espelho.id_lead, agentesia_crm_espelho.titulo_painel,
       agentesia_crm_espelho.id_responsavel, agentesia_crm_espelho.responsavel_nome, agentesia_crm_espelho.ids_etiquetas,
       agentesia_crm_espelho.etiquetas, agentesia_crm_espelho.situacao_helena, agentesia_crm_espelho.numero_canal)
      is distinct from
      (excluded.id_etapa_helena, excluded.etapa_titulo, excluded.fase, excluded.arquivado, excluded.titulo, excluded.valor,
       excluded.atualizado_em_helena, coalesce(excluded.id_lead, agentesia_crm_espelho.id_lead),
       coalesce(excluded.titulo_painel, agentesia_crm_espelho.titulo_painel), excluded.id_responsavel,
       excluded.responsavel_nome, excluded.ids_etiquetas, excluded.etiquetas, excluded.situacao_helena,
       coalesce(excluded.numero_canal, agentesia_crm_espelho.numero_canal))
returning id
"""


# Banco ainda sem a migração 013: grava só as colunas da 012 (o resto chega quando a 013 for aplicada).
_GRAVAR_012 = """
insert into agentesia_crm_espelho (id_escritorio, id_card_helena, id_painel_helena, id_etapa_helena, etapa_titulo, fase,
                                   id_contato_helena, id_lead, titulo, valor, arquivado, criado_em_helena,
                                   atualizado_em_helena, visto_em)
select $1::uuid, $2, $3, $4, $5, $6, $7,
       coalesce((select cc.id_lead from agentesia_crm_cards cc where cc.id_escritorio = $1::uuid and cc.id_card_helena = $2),
                (select l.id from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
                  where l.id_escritorio = $1::uuid and $7::text is not null and c.id_contato_helena = $7
                  order by l.criado_em desc limit 1)),
       $8, $9, $10, $11, $12, now()
on conflict (id_escritorio, id_card_helena) do update set
  id_painel_helena = excluded.id_painel_helena, id_etapa_helena = excluded.id_etapa_helena,
  etapa_titulo = excluded.etapa_titulo, fase = excluded.fase, id_contato_helena = excluded.id_contato_helena,
  id_lead = coalesce(excluded.id_lead, agentesia_crm_espelho.id_lead), titulo = excluded.titulo, valor = excluded.valor,
  arquivado = excluded.arquivado, criado_em_helena = coalesce(excluded.criado_em_helena, agentesia_crm_espelho.criado_em_helena),
  atualizado_em_helena = excluded.atualizado_em_helena, visto_em = now()
where (agentesia_crm_espelho.id_etapa_helena, agentesia_crm_espelho.etapa_titulo, agentesia_crm_espelho.arquivado,
       agentesia_crm_espelho.titulo, agentesia_crm_espelho.valor, agentesia_crm_espelho.atualizado_em_helena,
       agentesia_crm_espelho.id_lead)
      is distinct from
      (excluded.id_etapa_helena, excluded.etapa_titulo, excluded.arquivado, excluded.titulo, excluded.valor,
       excluded.atualizado_em_helena, coalesce(excluded.id_lead, agentesia_crm_espelho.id_lead))
returning id
"""


async def _gravar(pool: Any, *args: Any) -> Any:
    global _SEM_013
    if not _SEM_013:
        try:
            return await pool.fetchval(_GRAVAR, *args)
        except asyncpg.UndefinedColumnError:
            _SEM_013 = True
            log.warning("varredura do CRM: banco sem a migração 013; gravando só as colunas da 012")
    return await pool.fetchval(_GRAVAR_012, *args[:12])

_SEM_013 = False


async def varrer_escritorio(pool: Any, id_escritorio: str, helena: Any, *, importar: bool | None = None) -> dict[str, Any]:
    """Uma varredura da conta. importar=None decide sozinha (importa se nunca importou ou se o painel pediu)."""
    crm = await pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio)
    crm = json.loads(crm) if isinstance(crm, str) else (crm or {})
    id_painel = crm.get("id_painel")
    if not id_painel:
        return {"feito": "ignorado", "motivo": "sem_painel"}
    estado = await pool.fetchrow(
        "select cursor_atualizado, importado_em, importar_pedido_em from agentesia_crm_varredura where id_escritorio = $1::uuid",
        id_escritorio)
    if importar is None:
        importar = not estado or estado["importado_em"] is None or estado["importar_pedido_em"] is not None
    cursor = None if importar or not estado else estado["cursor_atualizado"]
    limite = PAGINAS_IMPORTACAO if importar else PAGINAS_INCREMENTAL

    # Todos os painéis da conta (o escolhido para a IA primeiro) e os nomes das colunas e das etiquetas.
    paineis: list[dict[str, Any]] = []
    try:
        paineis = [p for p in await helena.paineis() if p.get("id")]
    except Exception as erro:                              # sem a lista, segue só com o painel da IA
        log.warning("varredura do CRM: não leu os painéis da conta (%s)", erro)
    if not any(str(p["id"]) == str(id_painel) for p in paineis):
        paineis.insert(0, {"id": id_painel, "titulo": crm.get("titulo_painel"), "etapas": []})
    paineis.sort(key=lambda p: str(p["id"]) != str(id_painel))
    nomes_etiquetas: dict[str, str] = {}
    try:
        if hasattr(helena, "etiquetas"):
            nomes_etiquetas = {str(t["id"]): t.get("nome") or "" for t in await helena.etiquetas() if t.get("id")}
    except Exception as erro:
        log.warning("varredura do CRM: não leu as etiquetas da conta (%s)", erro)
    por_tipo = crm.get("etapas_por_tipo") if isinstance(crm.get("etapas_por_tipo"), dict) else {}

    vistos = mudados = colunas = 0
    maior = cursor
    paginas = 0
    for painel in paineis:
        titulos = {str(e["id"]): e.get("titulo") or "" for e in painel.get("etapas") or [] if e.get("id")}
        tipos = por_tipo if str(painel["id"]) == str(id_painel) else {}
        pagina = 1
        while pagina <= limite:
            cards, mais = await listar_cards(helena, str(painel["id"]), pagina)
            paginas += 1
            velhos = 0
            for bruto in cards:
                card = ler_card(bruto)
                if not card:
                    continue
                vistos += 1
                atualizado = card["atualizado_em"]
                if cursor and atualizado and atualizado < cursor - MARGEM:
                    velhos += 1
                    continue
                if atualizado and (maior is None or atualizado > maior):
                    maior = atualizado
                titulo = card["etapa_titulo"] or titulos.get(card["id_etapa"] or "")
                nomes = [nomes_etiquetas[t] for t in card["ids_etiquetas"] if nomes_etiquetas.get(t)]
                if await _gravar(pool, id_escritorio, card["id_card"], card["id_painel"] or str(painel["id"]),
                                       card["id_etapa"], titulo, fase_do_card(card["id_etapa"], titulo, tipos),
                                       card["id_contato"], card["titulo"], card["valor"], card["arquivado"],
                                       card["criado_em"], atualizado, card["titulo_painel"] or painel.get("titulo"),
                                       card["fase_helena"], card["situacao"], card["id_responsavel"],
                                       card["responsavel_nome"], card["ids_etiquetas"], nomes, card["id_sessao"]):
                    mudados += 1
                # Lead que já tem este card ligado: só a coluna, e só se mudou (o webhook pode ter se perdido).
                if card["id_etapa"]:
                    feito = await pool.execute(
                        """update agentesia_crm_cards set id_etapa_helena = $3, sincronizado_em = now(), atualizado_em = now()
                            where id_escritorio = $1::uuid and id_card_helena = $2 and id_etapa_helena is distinct from $3""",
                        id_escritorio, card["id_card"], card["id_etapa"])
                    colunas += int(str(feito).split()[-1] or 0) if feito else 0
            if not mais or (cursor and cards and velhos == len(cards)):
                break
            pagina += 1
            await asyncio.sleep(PAUSA_ENTRE_PAGINAS_S)

    await pool.execute(
        """insert into agentesia_crm_varredura (id_escritorio, cursor_atualizado, importado_em, ultima_em, cards_vistos,
                                                cards_mudados, erro)
           values ($1::uuid, $2, case when $3 then now() end, now(), $4, $5, null)
           on conflict (id_escritorio) do update set
             cursor_atualizado = greatest(coalesce(excluded.cursor_atualizado, agentesia_crm_varredura.cursor_atualizado),
                                          agentesia_crm_varredura.cursor_atualizado),
             importado_em = coalesce(excluded.importado_em, agentesia_crm_varredura.importado_em),
             importar_pedido_em = case when $3 then null else agentesia_crm_varredura.importar_pedido_em end,
             ultima_em = now(), cards_vistos = excluded.cards_vistos, cards_mudados = excluded.cards_mudados,
             erro = null, atualizado_em = now()""",
        id_escritorio, maior, bool(importar), vistos, mudados)
    return {"feito": "importado" if importar else "incremental", "vistos": vistos, "mudados": mudados,
            "colunas_atualizadas": colunas, "paginas": paginas, "paineis": len(paineis)}


async def _anotar_erro(pool: Any, id_escritorio: str, erro: str) -> None:
    await pool.execute(
        """insert into agentesia_crm_varredura (id_escritorio, ultima_em, erro) values ($1::uuid, now(), $2)
           on conflict (id_escritorio) do update set ultima_em = now(), erro = excluded.erro, atualizado_em = now()""",
        id_escritorio, erro[:300])


async def contas_para_varrer(pool: Any, agora: datetime, limite: int = 20) -> list[str]:
    """Contas com CRM ligado cuja última varredura passou do intervalo, ou com importação pedida."""
    linhas = await pool.fetch(
        """select i.id_escritorio::text as id from agentesia_integracoes i
             left join agentesia_crm_varredura v on v.id_escritorio = i.id_escritorio
            where i.tipo = 'crm' and coalesce(i.config->>'id_painel', '') <> ''
              and (v.id_escritorio is null or v.importar_pedido_em is not null or v.ultima_em is null
                   or v.ultima_em < $1)
            order by v.importar_pedido_em nulls last, v.ultima_em nulls first limit $2""",
        agora - timedelta(seconds=INTERVALO_S), limite)
    return [r["id"] for r in linhas]


class Reconciliador:
    """Laço de fundo do app "ia": a cada minuto vê quem precisa de varredura e roda uma conta por vez."""

    def __init__(self, pool: Any, helena_url: str, http: Any = None) -> None:
        self._pool, self._url, self._http = pool, helena_url, http
        self._parar = asyncio.Event()

    def parar(self) -> None:
        self._parar.set()

    async def uma_rodada(self) -> list[dict[str, Any]]:
        from app.banco.postgres import token_helena
        from app.canal.helena_conta import ErroHelenaApi, HelenaConta

        feitos = []
        try:
            ids = await contas_para_varrer(self._pool, datetime.now(timezone.utc))
        except Exception as erro:                          # banco sem a migração 012: o laço fica quieto
            if "agentesia_crm_varredura" in str(erro):
                return []
            raise
        for id_escritorio in ids:
            if self._parar.is_set():
                break
            token = await token_helena(self._pool, id_escritorio)
            if not token:
                await _anotar_erro(self._pool, id_escritorio, "conta sem token")
                continue
            try:
                resultado = await varrer_escritorio(self._pool, id_escritorio, HelenaConta(token, self._url, self._http))
            except ErroHelenaApi as erro:
                await _anotar_erro(self._pool, id_escritorio, erro.motivo)
                resultado = {"feito": "erro", "motivo": erro.motivo}
            feitos.append({"id_escritorio": id_escritorio, **resultado})
        return feitos

    async def rodar(self) -> None:
        while not self._parar.is_set():
            try:
                await self.uma_rodada()
            except Exception:
                log.exception("falha na varredura do CRM")
            try:
                await asyncio.wait_for(self._parar.wait(), CHECAR_PEDIDOS_S)
            except asyncio.TimeoutError:
                pass
