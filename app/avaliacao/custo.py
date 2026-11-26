"""Custo das conversas: soma por papel (repo.chamadas + lead de IA + juiz), teto da bateria e estimativa sem API.

O teto vem antes de qualquer chamada: antes de cada turno (e de cada fala do lead de IA e de cada juiz), o custo
previsto é RESERVADO; se gasto + reservas em voo + o previsto passaria do teto, a simulação para ("teto_de_custo").
A reserva é o que segura o teto com conversas em paralelo: N rodadas ao mesmo tempo não conferem o mesmo saldo.
Ao registrar o gasto de verdade, a reserva é liberada.

A estimativa (`estimar`) roda os cenários com o modelo roteirizado (de graça), mede o tamanho real de cada pedido
(sistema + conteúdo, ~4 caracteres por token) e aplica o preço do modelo de app/modelo.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Iterable

from app.modelo import PRECOS_USD_POR_MILHAO, calcular_custo

CARACTERES_POR_TOKEN = 4
SAIDA_MEDIA = {"extrator": 120, "etapa": 160, "auditor": 60, "lead_simulado": 80, "juiz": 700}   # tokens de saída
CHAMADAS_DO_JUIZ = 1
ENTRADA_LEAD_IA = 2500                               # tokens de entrada de uma fala do lead de IA (cartão + conversa)
ENTRADA_JUIZ = 6000                                  # tokens de entrada de um juiz (transcrição + critérios)
# O auditor só roda quando o extrator marca um sinal (o modelo roteirizado nunca marca): a estimativa conta 1 chamada
# por conversa, com o prompt do auditor (~400 tokens, medido em app/cerebro/auditor.py) + as últimas 30 mensagens.
CHAMADAS_DO_AUDITOR = 1
SISTEMA_AUDITOR = 450
MENSAGENS_DO_AUDITOR = 30


def previsto_lead_ia(modelo: str = "gpt-4.1-mini") -> float:
    return calcular_custo(modelo, ENTRADA_LEAD_IA, SAIDA_MEDIA["lead_simulado"], 0)


def previsto_juiz(modelo: str = "gpt-4.1", transcricoes: int = 1) -> float:
    return calcular_custo(modelo, ENTRADA_JUIZ * transcricoes, SAIDA_MEDIA["juiz"], 0)


def _como_dict(chamada: Any) -> dict[str, Any]:
    if isinstance(chamada, dict):
        return chamada
    if is_dataclass(chamada):
        return asdict(chamada)
    return vars(chamada)


def somar(chamadas: Iterable[Any]) -> dict[str, Any]:
    """{por_papel: {papel: usd}, total_usd, tokens_entrada, tokens_saida, tokens_cache, chamadas}."""
    por_papel: dict[str, float] = {}
    total = entrada = saida = cache = quantas = 0
    for bruta in chamadas:
        c = _como_dict(bruta)
        custo = float(c.get("custo_usd") or 0)
        papel = c.get("papel") or "?"
        por_papel[papel] = round(por_papel.get(papel, 0.0) + custo, 6)
        total += custo
        entrada += int(c.get("tokens_entrada") or 0)
        saida += int(c.get("tokens_saida") or 0)
        cache += int(c.get("tokens_cache") or 0)
        quantas += 1
    return {"por_papel": dict(sorted(por_papel.items())), "total_usd": round(total, 6), "tokens_entrada": entrada,
            "tokens_saida": saida, "tokens_cache": cache, "chamadas": quantas}


class TetoEstourado(Exception):
    pass


@dataclass
class Teto:
    """Limite de gasto da bateria inteira (todas as conversas e rodadas)."""

    limite_usd: float
    estimativa_turno_usd: float = 0.01               # usado antes do primeiro turno medido
    gasto_usd: float = 0.0
    turnos: int = 0
    parou: bool = False
    em_voo_usd: float = 0.0                          # reservado por chamadas que ainda não terminaram

    def __post_init__(self) -> None:
        if self.limite_usd is None or self.limite_usd <= 0:
            raise ValueError("o teto de custo precisa ser maior que zero (--teto-usd)")

    @property
    def media_turno_usd(self) -> float:
        return self.gasto_usd / self.turnos if self.turnos else self.estimativa_turno_usd

    def registrar(self, chamadas: Iterable[Any], turnos: int = 1, *, reserva: float = 0.0) -> None:
        """Soma o gasto de verdade e libera a reserva feita antes da chamada."""
        self.gasto_usd += sum(float(_como_dict(c).get("custo_usd") or 0) for c in chamadas)
        self.turnos += turnos
        self.liberar(reserva)

    def liberar(self, reserva: float) -> None:
        self.em_voo_usd = max(0.0, self.em_voo_usd - (reserva or 0.0))

    def pode_seguir(self, proximo_usd: float | None = None) -> bool:
        """Cabe mais um turno (ou a chamada de `proximo_usd`) sem passar do teto, contando as reservas em voo?"""
        previsto = self.gasto_usd + self.em_voo_usd + (self.media_turno_usd if proximo_usd is None else proximo_usd)
        if previsto > self.limite_usd:
            self.parou = True
            return False
        return True

    def reservar(self, proximo_usd: float | None = None) -> float | None:
        """Reserva o custo previsto (o turno médio, por padrão) e devolve o valor reservado; None = não cabe."""
        previsto = self.media_turno_usd if proximo_usd is None else proximo_usd
        if not self.pode_seguir(previsto):
            return None
        self.em_voo_usd += previsto
        return previsto


# ---------------------------------------------------------------------------- estimativa sem API
def preco(modelo: str) -> tuple[float, float, float]:
    if modelo not in PRECOS_USD_POR_MILHAO:
        raise ValueError(f"modelo sem preço em app/modelo.py: {modelo}")
    return PRECOS_USD_POR_MILHAO[modelo]


@dataclass
class Estimativa:
    modelo: str
    rodadas: int
    por_cenario: list[dict[str, Any]] = field(default_factory=list)
    total_usd: float = 0.0
    total_com_cache_usd: float = 0.0

    def texto(self) -> str:
        entrada, saida, cache = preco(self.modelo)
        linhas = [f"Estimativa do modo real ({self.modelo}: US$ {entrada:.2f} entrada / US$ {saida:.2f} saída "
                  f"/ US$ {cache:.2f} cache por milhão de tokens), {self.rodadas} rodada(s) por cenário:", ""]
        linhas.append(f"{'cenário':<42} {'turnos':>6} {'chamadas':>8} {'tokens ent.':>11} {'auditor':>14} {'US$/conversa':>12}")
        for c in self.por_cenario:
            auditor = c.get("auditor") or "desligado"
            linhas.append(f"{c['id']:<42} {c['turnos']:>6} {c['chamadas']:>8} {c['tokens_entrada']:>11} {auditor:>14} "
                          f"{c['usd_conversa']:>12.4f}")
        linhas += ["", f"Total sem cache: US$ {self.total_usd:.2f}   (com cache do prompt: ~US$ {self.total_com_cache_usd:.2f})"]
        if any(c.get("auditor") for c in self.por_cenario):
            linhas.append(f"O auditor entra com {CHAMADAS_DO_AUDITOR} chamada por conversa (ele só roda quando o extrator "
                          "marca um sinal), pelo preço do modelo dele.")
        linhas.append("É estimativa: tamanhos medidos com o modelo roteirizado; a primeira rodada real mede o custo de verdade.")
        return "\n".join(linhas)


def _tokens_da_conversa(pedidos: list[dict[str, Any]], mensagens: int) -> int:
    """Tamanho das últimas `mensagens` da conversa, medido no maior pedido da etapa (o histórico mais longo)."""
    conteudos = [p.get("conteudo") or "" for p in pedidos if p.get("papel") == "etapa"]
    if not conteudos:
        return 0
    linhas = [l for l in max(conteudos, key=len).splitlines() if ": " in l]
    return len("\n".join(linhas[-mensagens:])) // CARACTERES_POR_TOKEN


def estimar_pedidos(pedidos: list[dict[str, Any]], modelo: str, *, juiz: bool = False, lead_ia: bool = False,
                    modelo_juiz: str = "gpt-4.1", modelo_auditor: str | None = None) -> dict[str, Any]:
    """Custo de uma conversa a partir dos pedidos que o modelo roteirizado recebeu.

    Cada pedido paga o preço do modelo que pediu (extrator e etapa podem ser modelos diferentes); sem preço conhecido,
    vale o `modelo`. Com `modelo_auditor`, soma as chamadas previstas do auditor (CHAMADAS_DO_AUDITOR).
    """
    preco(modelo)
    if modelo_auditor:
        preco(modelo_auditor)
    usd = usd_cache = 0.0
    tokens = 0
    sistemas_vistos: set[str] = set()
    for pedido in pedidos:
        nome = pedido.get("modelo") if pedido.get("modelo") in PRECOS_USD_POR_MILHAO else modelo
        sistema_t = len(pedido.get("sistema") or "") // CARACTERES_POR_TOKEN
        conteudo_t = len(pedido.get("conteudo") or "") // CARACTERES_POR_TOKEN
        saida_t = SAIDA_MEDIA.get(pedido.get("papel") or "", 150)
        tokens += sistema_t + conteudo_t
        usd += calcular_custo(nome, sistema_t + conteudo_t, saida_t, 0)
        # Com cache: o sistema repetido (>= 1024 tokens) entra pelo preço de cache a partir da 2ª vez.
        repetido = pedido.get("sistema") in sistemas_vistos and sistema_t >= 1024
        sistemas_vistos.add(pedido.get("sistema"))
        usd_cache += calcular_custo(nome, conteudo_t + (0 if repetido else sistema_t), saida_t, sistema_t if repetido else 0)
    chamadas = len(pedidos)
    if modelo_auditor:
        faltam = max(0, CHAMADAS_DO_AUDITOR - sum(1 for p in pedidos if p.get("papel") == "auditor"))
        entrada_t = SISTEMA_AUDITOR + _tokens_da_conversa(pedidos, MENSAGENS_DO_AUDITOR)
        custo_auditor = faltam * calcular_custo(modelo_auditor, entrada_t, SAIDA_MEDIA["auditor"], 0)
        usd, usd_cache, chamadas, tokens = usd + custo_auditor, usd_cache + custo_auditor, chamadas + faltam, tokens + faltam * entrada_t
    if lead_ia:
        extra = sum(1 for p in pedidos if p.get("papel") == "etapa")
        custo_lead = extra * calcular_custo(modelo, 800, SAIDA_MEDIA["lead_simulado"], 0)
        usd, usd_cache, chamadas = usd + custo_lead, usd_cache + custo_lead, chamadas + extra
    if juiz:
        transcricao_t = sum(len(p.get("conteudo") or "") for p in pedidos[-2:]) // CARACTERES_POR_TOKEN + 1500
        custo_juiz = calcular_custo(modelo_juiz, transcricao_t, SAIDA_MEDIA["juiz"], 0)
        usd, usd_cache, chamadas = usd + custo_juiz, usd_cache + custo_juiz, chamadas + CHAMADAS_DO_JUIZ
    return {"usd": round(usd, 6), "usd_cache": round(usd_cache, 6), "tokens_entrada": tokens, "chamadas": chamadas}
