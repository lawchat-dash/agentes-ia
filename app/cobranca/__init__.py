"""Cobrança por consumo de IA em R$ (modelo do Weaver). Ver docs/COBRANCA_TOKENS.md e db/migracoes/007.

Uma chave de IA só (a da LawChat, no .env). Cada escritório tem uma CARTEIRA (saldo em R$ e bônus do mês) e um LIVRO
de movimentos (agentesia_carteira_movimentos). Toda chamada de IA é gravada com tokens e custo em US$; um gatilho do
banco converte para R$ pela cotação vigente e aplica o markup (os dois ficam gravados na chamada). O débito sai em
lote (Cobrador, a cada minuto): soma as chamadas pendentes, lança um débito no livro e marca as chamadas, tudo na mesma
transação, com "for update skip locked" (nenhuma chamada é debitada duas vezes nem fica de fora).

  custo_brl_real = custo_usd × cotação
  custo_brl      = custo_usd × cotação × markup        (valor debitado)

"Pode gastar?" (bloqueado): no modo 'pre_pago', saldo + bônus − consumo ainda não debitado <= 0 bloqueia toda chamada
paga (turno, follow-up, resumos, mídia, embeddings) com o motivo 'sem_saldo'. Escritório sem carteira, em
'so_registrar' ou banco sem a 007: não bloqueia (só registra). A volta é sozinha: entrou crédito, a próxima mensagem
do lead é respondida; o que chegou durante a pausa ficou em silêncio (sem rajada de respostas atrasadas) e os
follow-ups do período foram cancelados.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("agentesia.cobranca")

MOTIVO = "sem_saldo"
MODOS = ("pre_pago", "so_registrar")
TIPOS_MANUAIS = ("bonus_manual", "ajuste", "recarga")      # o que o admin pode lançar à mão
FAIXA_BONUS = 80
CACHE_S = 15.0
COTACAO_PADRAO = 5.50
MARKUP_PADRAO = 1.00


def mes_atual(agora: datetime | None = None) -> str:
    from app.notificacoes import fuso
    return (agora or datetime.now(timezone.utc)).astimezone(fuso()).strftime("%Y-%m")


def calcular(custo_usd: float, cotacao: float, markup: float) -> tuple[float, float]:
    """(custo real em R$, valor cobrado em R$): a mesma conta do gatilho agentesia_precificar_chamada."""
    real = round(float(custo_usd or 0) * float(cotacao), 6)
    return real, round(float(custo_usd or 0) * float(cotacao) * float(markup), 6)


def markup_de(valor: Any = None, percentual: Any = None) -> float:
    """Markup como multiplicador. Aceita o multiplicador (1.3) ou o percentual sobre o custo (30 = +30%)."""
    if percentual not in (None, ""):
        try:
            p = float(percentual)
        except (TypeError, ValueError):
            raise ValueError("O markup em % precisa ser um número.") from None
        valor = 1 + p / 100
    try:
        m = round(float(valor), 4)
    except (TypeError, ValueError):
        raise ValueError("O markup precisa ser um número (1,00 = sem margem).") from None
    if m <= 0 or m > 20:
        raise ValueError("O markup vai de 0,01 a 20 (1,00 = cobra o custo; 1,30 = +30%).")
    return m


def validar_cotacao(valor: Any) -> float:
    try:
        c = round(float(valor), 4)
    except (TypeError, ValueError):
        raise ValueError("A cotação precisa ser um número (reais por dólar).") from None
    if c <= 0 or c >= 100:
        raise ValueError("A cotação precisa estar entre 0 e 100 reais por dólar.")
    return c


# ============================================================================ banco tem a 007?
_TEM_007: dict[str, tuple[float, bool]] = {}


async def tem_cobranca(conexao: Any) -> bool:
    """A migração 007 foi aplicada? (guardado por 5 minutos; sem ela tudo segue como antes, sem bloquear)."""
    item = _TEM_007.get("v")
    if item and item[0] > time.monotonic():
        return item[1]
    try:
        tem = bool(await conexao.fetchval(
            """select exists(select 1 from information_schema.columns where table_schema = 'public'
                             and table_name = 'agentesia_chamadas_ia' and column_name = 'cobranca')"""))
    except Exception:
        log.exception("falha ao conferir a migração 007")
        tem = False
    _TEM_007["v"] = (time.monotonic() + 300, tem)
    return tem


# ============================================================================ gravar chamadas (ponto único)
def _sem_preco(c: Any) -> bool:
    tokens = (c.tokens_entrada or 0) + (c.tokens_saida or 0) + (getattr(c, "tokens_cache", 0) or 0)
    return bool(c.sucesso and tokens and not (c.custo_usd or 0) and c.modelo and c.modelo != "falso")


async def gravar_chamadas(conexao: Any, *, id_escritorio: str | None, chamadas: list[Any], id_turno: str | None = None,
                          id_lead: str | None = None, id_agente: str | None = None, codigo_etapa: str | None = None,
                          origem: str = "producao") -> None:
    """Grava as chamadas de IA. tokens_entrada = toda a entrada (inclusive cache); tokens_cache = a parte do cache.
    O R$ (cotação × markup) é calculado pelo gatilho do banco; lead, agente e etapa vêm do turno quando não forem dados."""
    if not chamadas:
        return
    linhas = [(id_escritorio, id_turno, c.papel, c.modelo,
               (c.tokens_entrada or 0) + (getattr(c, "tokens_cache", 0) or 0) + (getattr(c, "tokens_cache_escrita", 0) or 0),
               c.tokens_saida or 0, c.custo_usd or 0, c.duracao_ms, c.sucesso, c.erro) for c in chamadas]
    if not await tem_cobranca(conexao):
        await conexao.executemany(
            """insert into agentesia_chamadas_ia (id_escritorio, id_turno, papel, modelo, tokens_entrada, tokens_saida,
                                                   custo_usd, duracao_ms, sucesso, erro)
               values ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10)""", linhas)
        return
    await conexao.executemany(
        """insert into agentesia_chamadas_ia (id_escritorio, id_turno, papel, modelo, tokens_entrada, tokens_saida,
                                               custo_usd, duracao_ms, sucesso, erro, tokens_cache, id_lead, id_agente,
                                               codigo_etapa, origem, sem_preco)
           values ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::uuid, $13::uuid, $14, $15, $16)""",
        [(*linha, (getattr(c, "tokens_cache", 0) or 0), id_lead, id_agente, codigo_etapa, origem, _sem_preco(c))
         for linha, c in zip(linhas, chamadas)])


# ============================================================================ pode gastar?
@dataclass(frozen=True)
class Situacao:
    modo: str
    saldo_brl: float
    bonus_brl: float
    pendente_brl: float          # consumo gravado e ainda não debitado
    pausado_por_saldo: bool

    @property
    def disponivel_brl(self) -> float:
        return round(self.saldo_brl + self.bonus_brl - self.pendente_brl, 6)

    @property
    def bloqueado(self) -> bool:
        return self.modo == "pre_pago" and self.disponivel_brl <= 0


async def situacao(conexao: Any, id_escritorio: str) -> Situacao | None:
    """Carteira do escritório agora. None: sem a 007 ou sem carteira (não bloqueia)."""
    if not await tem_cobranca(conexao):
        return None
    linha = await conexao.fetchrow(
        """select c.modo, c.saldo_brl::float8 as saldo, c.bonus_brl::float8 as bonus, c.pausado_por_saldo,
                  (select coalesce(sum(ch.custo_brl), 0)::float8 from agentesia_chamadas_ia ch
                    where ch.id_escritorio = c.id_escritorio and ch.cobranca = 'pendente') as pendente
           from agentesia_carteiras c where c.id_escritorio = $1::uuid""", id_escritorio)
    if not linha:
        return None
    return Situacao(linha["modo"], linha["saldo"], linha["bonus"], linha["pendente"], linha["pausado_por_saldo"])


_CACHE: dict[str, tuple[float, bool]] = {}


def esquecer(id_escritorio: str | None = None) -> None:
    """Entrou crédito (ou mudou o modo): a próxima conferência lê o banco na hora."""
    if id_escritorio is None:
        _CACHE.clear()
        _CACHE_RESTANTE.clear()
    else:
        _CACHE.pop(str(id_escritorio), None)
        _CACHE_RESTANTE.pop(str(id_escritorio), None)


async def bloqueado(conexao: Any, id_escritorio: str | None) -> bool:
    """O bloqueio único antes de toda chamada paga. Guardado por 15 s; erro ao conferir não bloqueia (só registra)."""
    if not id_escritorio:
        return False
    chave = str(id_escritorio)
    item = _CACHE.get(chave)
    if item and item[0] > time.monotonic():
        return item[1]
    try:
        atual = await situacao(conexao, chave)
        resultado = bool(atual and atual.bloqueado)
    except Exception:
        log.exception("falha ao conferir o saldo do escritório %s", chave)
        return False
    _CACHE[chave] = (time.monotonic() + CACHE_S, resultado)
    return resultado


_CACHE_RESTANTE: dict[str, tuple[float, float | None]] = {}
CACHE_RESTANTE_S = 60.0


def percentual(disponivel_brl: float, consumido_desde_brl: float) -> float | None:
    """% que resta do que o escritório tinha logo depois da última entrada de crédito. Função pura."""
    total = float(disponivel_brl) + float(consumido_desde_brl)
    if total <= 0:
        return None                                  # sem crédito nenhum: quem fala é o bloqueio (sem_saldo)
    return max(0.0, min(100.0, round(float(disponivel_brl) / total * 100, 2)))


async def percentual_restante(conexao: Any, id_escritorio: str | None) -> float | None:
    """Quanto ainda resta dos créditos da IA (pré-pago), em %: o disponível agora sobre o que havia logo depois da
    última entrada de crédito (recarga, bônus, ajuste positivo) = disponível + consumido desde então. Guardado por
    60 s. None: sem a 007, sem carteira, fora do pré-pago, sem entrada de crédito ou erro ao ler (não avisa)."""
    if not id_escritorio:
        return None
    chave = str(id_escritorio)
    item = _CACHE_RESTANTE.get(chave)
    if item and item[0] > time.monotonic():
        return item[1]
    resultado: float | None = None
    try:
        atual = await situacao(conexao, chave)
        if atual and atual.modo == "pre_pago":
            consumido = await conexao.fetchval(
                """select coalesce(sum(ch.custo_brl), 0)::float8 from agentesia_chamadas_ia ch
                   where ch.id_escritorio = $1::uuid and ch.cobranca <> 'isenta'
                     and ch.criado_em >= (select max(m.criado_em) from agentesia_carteira_movimentos m
                                          where m.id_escritorio = $1::uuid and m.valor_brl > 0)""", chave)
            if consumido is not None:
                resultado = percentual(atual.disponivel_brl, float(consumido or 0))
    except Exception:
        log.exception("falha ao ler os créditos restantes do escritório %s", chave)
        return None
    _CACHE_RESTANTE[chave] = (time.monotonic() + CACHE_RESTANTE_S, resultado)
    return resultado


# ============================================================================ lançamentos
async def lancar(conexao: Any, id_escritorio: str, tipo: str, valor: float, *, motivo: str | None = None,
                 id_usuario: str | None = None, chave: str | None = None,
                 detalhe: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Um movimento no livro (e na carteira, na mesma transação). None: a chave já tinha sido usada."""
    linha = await conexao.fetchrow(
        """select (m).id, (m).tipo, (m).valor_brl::float8 as valor_brl, (m).saldo_depois::float8 as saldo_depois,
                  (m).bonus_depois::float8 as bonus_depois, (m).criado_em
           from (select agentesia_carteira_lancar($1::uuid, $2, $3::numeric, $4, $5, $6::uuid, $7::jsonb, null) as m) x""",
        id_escritorio, tipo, valor, chave, motivo, id_usuario, json.dumps(detalhe or {}, ensure_ascii=False))
    esquecer(id_escritorio)
    return dict(linha) if linha and linha["id"] else None


async def debitar_pendentes(conexao: Any, id_escritorio: str | None = None) -> list[dict[str, Any]]:
    """Débito em lote de tudo que está pendente (um movimento por escritório)."""
    linhas = await conexao.fetch(
        "select escritorio, movimento, valor::float8 as valor, quantidade from agentesia_debitar_consumo($1::uuid)",
        id_escritorio)
    for l in linhas:
        esquecer(str(l["escritorio"]))
    return [dict(l) for l in linhas]


async def renovar_bonus(conexao: Any, mes: str | None = None, id_escritorio: str | None = None) -> int:
    """Bônus do plano do mês para quem ainda não recebeu (idempotente por mês)."""
    mes = mes or mes_atual()
    ids = await conexao.fetch(
        """select id_escritorio from agentesia_carteiras
           where id_plano is not null and bonus_mes is distinct from $1 and ($2::uuid is null or id_escritorio = $2::uuid)""",
        mes, id_escritorio)
    feitos = 0
    for linha in ids:
        if await conexao.fetchval("select agentesia_renovar_bonus($1, $2)", linha["id_escritorio"], mes) is not None:
            feitos += 1
            esquecer(str(linha["id_escritorio"]))
    return feitos


async def confirmar_recarga(conexao: Any, id_recarga: str, *, id_usuario: str | None = None,
                            id_externo: str | None = None, detalhe: dict[str, Any] | None = None) -> str | None:
    """Credita a recarga uma vez só (repetir devolve o mesmo movimento)."""
    id_movimento = await conexao.fetchval(
        "select agentesia_confirmar_recarga($1::uuid, $2::uuid, $3, $4::jsonb)",
        id_recarga, id_usuario, id_externo, json.dumps(detalhe or {}, ensure_ascii=False))
    id_escritorio = await conexao.fetchval("select id_escritorio from agentesia_recargas where id = $1::uuid", id_recarga)
    esquecer(str(id_escritorio) if id_escritorio else None)
    return str(id_movimento) if id_movimento else None


# ============================================================================ avisos (80% do bônus, bônus e saldo acabaram)
def _brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def avisos_devidos(carteira: dict[str, Any], mes: str) -> list[dict[str, Any]]:
    """Que avisos esta carteira ainda deve mandar (uma vez por mês, ou uma vez por pausa). Função pura."""
    if carteira.get("modo") != "pre_pago":
        return []
    ja = carteira.get("avisos") or {}
    if isinstance(ja, str):
        ja = json.loads(ja or "{}")
    nome = carteira.get("nome") or "o escritório"
    saldo, bonus, base = float(carteira["saldo_brl"]), float(carteira["bonus_brl"]), float(carteira["bonus_do_mes_brl"])
    devidos: list[dict[str, Any]] = []
    if carteira.get("pausado_por_saldo"):
        marca = str(carteira.get("pausado_em") or "")
        if ja.get("saldo_zero") != marca:
            devidos.append({"chave": "saldo_zero", "marca": marca, "tipo_evento": "saldo_esgotado", "faixa": 100,
                            "gravidade": "critico",
                            "texto": f"🚫 *Saldo da IA acabou*\nEscritório: {nome}\nA IA parou de responder. As conversas "
                                     "seguem na Helena com a equipe. Peça uma recarga no painel (Consumo e saldo): ela "
                                     "volta sozinha quando o crédito entrar."})
        return devidos
    if base > 0:
        usado = (base - bonus) / base * 100
        if bonus <= 0 and ja.get("bonus_100") != mes:
            devidos.append({"chave": "bonus_100", "marca": mes, "tipo_evento": "bonus_esgotado", "faixa": 100,
                            "gravidade": "aviso",
                            "texto": f"⚠️ *Bônus do mês da IA acabou*\nEscritório: {nome}\nAgora o consumo sai do saldo "
                                     f"({_brl(saldo)}). Quando o saldo acabar, a IA pausa."})
        elif usado >= FAIXA_BONUS and bonus > 0 and ja.get("bonus_80") != mes:
            devidos.append({"chave": "bonus_80", "marca": mes, "tipo_evento": "bonus_alto", "faixa": FAIXA_BONUS,
                            "gravidade": "aviso",
                            "texto": f"⚠️ *{usado:.0f}% do bônus do mês da IA usado*\nEscritório: {nome}\nRestam "
                                     f"{_brl(bonus)} de bônus e {_brl(saldo)} de saldo."})
    return devidos


async def mandar_avisos(conexao: Any, mes: str | None = None) -> int:
    """Põe na fila os avisos devidos: evento no painel e WhatsApp do aviso "consumo_limite" (ação aviso_consumo).
    Saldo esgotado também vai para a central da LawChat (evento saldo_esgotado)."""
    mes = mes or mes_atual()
    carteiras = await conexao.fetch(
        """select c.id_escritorio, c.modo, c.saldo_brl::float8 as saldo_brl, c.bonus_brl::float8 as bonus_brl,
                  c.bonus_do_mes_brl::float8 as bonus_do_mes_brl, c.pausado_por_saldo, c.pausado_em, c.avisos, e.nome
           from agentesia_carteiras c join agentesia_escritorios e on e.id = c.id_escritorio where c.modo = 'pre_pago'""")
    novos = 0
    for c in carteiras:
        for aviso in avisos_devidos(dict(c), mes):
            chave = f"saldo:{c['id_escritorio']}:{aviso['chave']}:{aviso['marca']}"
            feito = await conexao.fetchval(
                """insert into agentesia_acoes (id_escritorio, tipo, chave_unica, dados)
                   values ($1, 'aviso_consumo', $2, $3::jsonb) on conflict (chave_unica) do nothing returning true""",
                c["id_escritorio"], chave,
                json.dumps({"texto": aviso["texto"], "faixa": aviso["faixa"], "tipo_evento": aviso["tipo_evento"],
                            "gravidade": aviso["gravidade"]}, ensure_ascii=False))
            await conexao.execute(
                "update agentesia_carteiras set avisos = avisos || jsonb_build_object($2::text, $3::text) where id_escritorio = $1",
                c["id_escritorio"], aviso["chave"], aviso["marca"])
            novos += bool(feito)
    return novos


async def ciclo(conexao: Any) -> dict[str, int]:
    """Uma volta do cobrador: debita o pendente, renova o bônus do mês e manda os avisos."""
    if not await tem_cobranca(conexao):
        return {"debitos": 0, "bonus": 0, "avisos": 0}
    debitos = await debitar_pendentes(conexao)
    bonus = await renovar_bonus(conexao)
    avisos = await mandar_avisos(conexao)
    return {"debitos": len(debitos), "bonus": bonus, "avisos": avisos}


class Cobrador:
    """Laço de fundo (a cada AGENTESIA_COBRANCA_INTERVALO_S, padrão 60 s). Vários servidores podem rodar juntos: o
    débito usa skip locked, o bônus é idempotente por chave e os avisos têm chave única."""

    def __init__(self, pool: Any, intervalo_s: float = 60.0) -> None:
        import asyncio

        self._pool = pool
        self._intervalo = intervalo_s
        self._parar = asyncio.Event()

    async def rodar(self) -> None:
        import asyncio

        while not self._parar.is_set():
            try:
                await ciclo(self._pool)
            except Exception:
                log.exception("falha no ciclo de cobrança")
            try:
                await asyncio.wait_for(self._parar.wait(), self._intervalo)
            except asyncio.TimeoutError:
                pass

    def parar(self) -> None:
        self._parar.set()
