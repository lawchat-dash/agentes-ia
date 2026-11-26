"""Camada de modelo: o único lugar que fala com o provedor de IA.

Dois provedores, escolhidos pelo nome do modelo: OpenAI (GPT, o padrão) e Anthropic (Claude).

Todo agente chama `gerar(...)`, que:
  * envia o esquema de saída e devolve o JSON já validado;
  * mede tokens, custo e duração na própria chamada;
  * traduz o erro do provedor em um motivo legível;
  * tenta mais uma vez quando a saída vem inválida.

A IA nunca aciona ferramenta: ela só devolve dados no formato pedido, e o código age.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

# Preço por milhão de tokens (entrada, saída, entrada em cache), em dólar.
# Tabela da Anthropic de 03/11/2026. Modelo fora da tabela conta custo zero.
PRECOS_USD_POR_MILHAO: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-2": (8.00, 40.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    # OpenAI: conferido em 26/11/2026 em developers.openai.com/api/docs/pricing (Standard, contexto curto).
    # gpt-4.1-nano não aparece mais na página: fica o último valor conhecido.
    "gpt-4.1": (2.00, 8.00, 0.50),
    "gpt-4.1-mini": (0.40, 1.60, 0.10),
    "gpt-4.1-nano": (0.10, 0.40, 0.025),
    "gpt-4o": (2.50, 10.00, 1.25),
    "gpt-4o-mini": (0.15, 0.60, 0.075),
    # Família GPT-6: entrada, saída e cache conferidos na página oficial em 26/11/2026 (antes o cache era estimado em
    # 1/4 da entrada, acima do preço real).
    "gpt-6-luna": (0.10, 0.50, 0.01),
    "gpt-6.1-sol": (2.00, 10.00, 0.10),
    "gpt-6.2-sol": (2.00, 10.00, 0.10),
    "gpt-6-astra": (10.00, 50.00, 1.00),
    "gpt-6.2-astra": (8.00, 40.00, 0.40),
    # Transcrição: (entrada de TEXTO, saída, -). A entrada de ÁUDIO tem preço próprio em PRECO_AUDIO_USD_POR_MILHAO.
    "gpt-4o-mini-transcribe": (1.25, 5.00, 0.0),
    "gpt-4o-transcribe": (2.50, 10.00, 0.0),
    # Embedding da base de conhecimento (só entrada).
    "text-embedding-3-small": (0.02, 0.0, 0.0),
    "text-embedding-3-large": (0.13, 0.0, 0.0),
}
# Tokens de ÁUDIO de entrada da transcrição (a OpenAI separa em usage.input_token_details.audio_tokens).
# Página do modelo em 26/11/2026 (developers.openai.com/api/docs/models/gpt-4o-mini-transcribe): "Audio input" US$ 1,25
# e US$ 2,50 (gpt-4o-transcribe). A tabela antiga da OpenAI dava US$ 3,00 / 6,00: se voltar, muda só aqui.
PRECO_AUDIO_USD_POR_MILHAO: dict[str, float] = {
    "gpt-4o-mini-transcribe": 1.25,
    "gpt-4o-transcribe": 2.50,
}
# Sem tokens no uso: preço por minuto de áudio (estimativa oficial da OpenAI para cada modelo de transcrição).
USD_POR_MINUTO_TRANSCRICAO: dict[str, float] = {
    "gpt-4o-mini-transcribe": 0.003,
    "gpt-4o-transcribe": 0.006,
}
# Escrita no cache da Anthropic (cache_creation_input_tokens): 1,25 x o preço da entrada.
FATOR_CACHE_ESCRITA = 1.25

# Modelos que aceitam o parâmetro de reserva em caso de recusa.
_COM_RESERVA = {"claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5"}

# Teto de tokens de saída quando quem chama não pede outro (`gerar(max_tokens=...)`).
MAX_TOKENS_OPENAI = 4000
MAX_TOKENS_ANTHROPIC = 16000


class ErroModelo(Exception):
    """Falha ao gerar. `motivo` é um código curto para o histórico e para o aviso."""

    def __init__(self, motivo: str, detalhe: str = "") -> None:
        super().__init__(f"{motivo}: {detalhe}" if detalhe else motivo)
        self.motivo = motivo
        self.detalhe = detalhe


@dataclass
class Chamada:
    """Registro de uma chamada de IA (vira linha em agentesia_chamadas_ia)."""

    papel: str
    modelo: str
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache: int = 0
    tokens_cache_escrita: int = 0      # Anthropic: entrada gravada no cache (cobrada a 1,25 x a entrada)
    custo_usd: float = 0.0
    duracao_ms: int = 0
    sucesso: bool = True
    erro: str | None = None


@dataclass
class Resultado:
    dados: dict[str, Any]
    chamadas: list[Chamada] = field(default_factory=list)


log = logging.getLogger("agentesia.modelo")
_SEM_PRECO_AVISADOS: set[str] = set()


def timeout_da_ia() -> float:
    """Tempo máximo de uma chamada ao provedor (AGENTESIA_IA_TIMEOUT_S, padrão 60 s). O padrão dos SDKs é 600 s: uma
    conexão pendurada segurava o lead 10 a 30 min e deixava a reserva vencer no meio do turno."""
    try:
        return max(5.0, float(os.environ.get("AGENTESIA_IA_TIMEOUT_S", "60")))
    except ValueError:
        return 60.0


def cliente_openai() -> Any:
    import httpx
    import openai

    return openai.AsyncOpenAI(timeout=httpx.Timeout(timeout_da_ia(), connect=5.0), max_retries=1)


def cliente_anthropic() -> Any:
    import anthropic
    import httpx

    return anthropic.AsyncAnthropic(timeout=httpx.Timeout(timeout_da_ia(), connect=5.0), max_retries=1)


def calcular_custo(modelo: str, entrada: int, saida: int, cache: int, cache_escrita: int = 0) -> float:
    """`entrada` são os tokens cobrados pelo preço cheio; `cache`, os lidos do cache; `cache_escrita`, os gravados no
    cache (Anthropic, 1,25 x a entrada)."""
    preco = PRECOS_USD_POR_MILHAO.get(modelo)
    if not preco:
        # A OpenAI devolve o nome com data ("gpt-4.1-2025-04-14"): usa o preço do modelo-base.
        base = next((nome for nome in PRECOS_USD_POR_MILHAO
                     if re.fullmatch(re.escape(nome) + r"-\d{4}-\d{2}-\d{2}", modelo)), None)
        preco = PRECOS_USD_POR_MILHAO.get(base or "")
    if not preco:
        if modelo and modelo != "falso" and modelo not in _SEM_PRECO_AVISADOS:
            _SEM_PRECO_AVISADOS.add(modelo)               # uma vez por modelo: o consumo deste modelo fica subcontado
            log.warning("modelo %s sem preço em PRECOS_USD_POR_MILHAO: custo contado como zero", modelo)
        return 0.0
    return round((entrada * preco[0] + saida * preco[1] + cache * preco[2]
                  + cache_escrita * preco[0] * FATOR_CACHE_ESCRITA) / 1_000_000, 6)


def _modelo_base(modelo: str, tabela: dict[str, Any]) -> str | None:
    if modelo in tabela:
        return modelo
    return next((nome for nome in tabela if re.fullmatch(re.escape(nome) + r"-\d{4}-\d{2}-\d{2}", modelo)), None)


def calcular_custo_transcricao(modelo: str, audio: int, texto: int, saida: int) -> float:
    """Transcrição por tokens: áudio de entrada, texto de entrada (o prompt) e texto de saída, cada um pelo seu preço."""
    base = _modelo_base(modelo, PRECO_AUDIO_USD_POR_MILHAO)
    preco_audio = PRECO_AUDIO_USD_POR_MILHAO.get(base or "", 0.0)
    if not preco_audio:
        return calcular_custo(modelo, audio + texto, saida, 0)       # modelo sem preço de áudio: tudo como texto
    return round(audio * preco_audio / 1_000_000 + calcular_custo(modelo, texto, saida, 0), 6)


def custo_por_minuto_transcricao(modelo: str, segundos: float) -> float:
    base = _modelo_base(modelo, USD_POR_MINUTO_TRANSCRICAO)
    return round(max(0.0, float(segundos)) / 60 * USD_POR_MINUTO_TRANSCRICAO.get(base or "", 0.0), 6)


# Caracteres do começo do sistema que identificam o agente e o papel na chave do cache (o resto do sistema pode ter o
# que muda por lead, como os FATOS DO SISTEMA no fim).
PREFIXO_DA_CHAVE = 6000


def chave_de_cache(papel: str, modelo: str, sistema: str) -> str:
    """`prompt_cache_key` estável por agente + papel: o papel e um resumo (hash) do começo do sistema, que é o roteiro e as
    regras fixas do agente. Sem id de lead nem nada que mude entre chamadas. Curta (a OpenAI limita o tamanho)."""
    import hashlib

    resumo = hashlib.sha256(f"{modelo}\n{sistema[:PREFIXO_DA_CHAVE]}".encode("utf-8")).hexdigest()[:16]
    return f"lc-{re.sub(r'[^a-z0-9_]+', '', papel.lower())[:24]}-{resumo}"


_COMO_PASSAR_A_CHAVE: dict[type, str | None] = {}


def _como_passar_a_chave(cliente: Any) -> str | None:
    """Como mandar o prompt_cache_key: "parametro" (SDK com o parâmetro, ou cliente falso com **kwargs), "corpo"
    (SDK antigo: vai em extra_body) ou None (cliente que não aceita nenhum dos dois)."""
    import inspect

    completions = getattr(getattr(cliente, "chat", None), "completions", None)
    tipo = type(completions)
    if tipo not in _COMO_PASSAR_A_CHAVE:
        try:
            parametros = inspect.signature(completions.create).parameters
        except (TypeError, ValueError, AttributeError):
            parametros = {}
        if "prompt_cache_key" in parametros or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros.values()):
            _COMO_PASSAR_A_CHAVE[tipo] = "parametro"
        else:
            _COMO_PASSAR_A_CHAVE[tipo] = "corpo" if "extra_body" in parametros else None
    return _COMO_PASSAR_A_CHAVE[tipo]


class Modelo(Protocol):
    async def gerar(
        self,
        *,
        papel: str,
        sistema: str,
        conteudo: str,
        esquema: dict[str, Any],
        modelo: str,
        esforco: str = "medium",
        validar: Callable[[dict[str, Any]], None] | None = None,
        max_tokens: int | None = None,
    ) -> Resultado: ...


class ModeloAnthropic:
    """Claude pela API da Anthropic, com saída estruturada."""

    def __init__(self, cliente: Any | None = None) -> None:
        if cliente is None:
            cliente = cliente_anthropic()
        self._cliente = cliente

    async def gerar(
        self,
        *,
        papel: str,
        sistema: str,
        conteudo: str,
        esquema: dict[str, Any],
        modelo: str,
        esforco: str = "medium",
        validar: Callable[[dict[str, Any]], None] | None = None,
        max_tokens: int | None = None,
    ) -> Resultado:
        chamadas: list[Chamada] = []
        ultimo_erro: ErroModelo | None = None
        for _tentativa in range(2):
            chamada = Chamada(papel=papel, modelo=modelo)
            chamadas.append(chamada)
            inicio = time.monotonic()
            try:
                dados = await self._uma_chamada(chamada, sistema, conteudo, esquema, modelo, esforco, max_tokens)
                if validar:
                    try:
                        validar(dados)
                    except Exception as erro:  # saída fora do combinado
                        raise ErroModelo("saida_invalida", str(erro)) from erro
                chamada.duracao_ms = int((time.monotonic() - inicio) * 1000)
                return Resultado(dados=dados, chamadas=chamadas)
            except ErroModelo as erro:
                chamada.duracao_ms = int((time.monotonic() - inicio) * 1000)
                chamada.sucesso = False
                chamada.erro = str(erro)
                ultimo_erro = erro
                # Só vale repetir quando o problema é a saída; o SDK já repete erro de rede e 5xx.
                if erro.motivo not in ("saida_invalida", "saida_cortada"):
                    break
        assert ultimo_erro is not None
        ultimo_erro.chamadas = chamadas  # type: ignore[attr-defined]
        raise ultimo_erro

    async def _uma_chamada(
        self,
        chamada: Chamada,
        sistema: str,
        conteudo: str,
        esquema: dict[str, Any],
        modelo: str,
        esforco: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        import anthropic

        parametros: dict[str, Any] = dict(
            model=modelo,
            max_tokens=max_tokens or MAX_TOKENS_ANTHROPIC,
            # As instruções ficam no começo e não mudam entre turnos: entram no cache.
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": conteudo}],
            output_config={"effort": esforco, "format": {"type": "json_schema", "schema": esquema}},
        )
        try:
            if modelo in _COM_RESERVA:
                # Se o modelo recusar por política, a própria API tenta num modelo reserva.
                resposta = await self._cliente.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **parametros
                )
            else:
                resposta = await self._cliente.messages.create(**parametros)
        except anthropic.AuthenticationError as erro:
            raise ErroModelo("chave_recusada", str(erro)) from erro
        except anthropic.PermissionDeniedError as erro:
            raise ErroModelo("sem_permissao", str(erro)) from erro
        except anthropic.RateLimitError as erro:
            raise ErroModelo("limite_de_uso", str(erro)) from erro
        except anthropic.BadRequestError as erro:
            motivo = "sem_credito" if "credit" in str(erro).lower() else "pedido_invalido"
            raise ErroModelo(motivo, str(erro)) from erro
        except anthropic.APIStatusError as erro:
            raise ErroModelo("provedor_fora_do_ar", f"{erro.status_code}") from erro
        except anthropic.APIConnectionError as erro:
            raise ErroModelo("sem_conexao", str(erro)) from erro

        uso = resposta.usage
        chamada.modelo = getattr(resposta, "model", modelo) or modelo
        chamada.tokens_entrada = getattr(uso, "input_tokens", 0) or 0
        chamada.tokens_saida = getattr(uso, "output_tokens", 0) or 0
        chamada.tokens_cache = getattr(uso, "cache_read_input_tokens", 0) or 0
        chamada.tokens_cache_escrita = getattr(uso, "cache_creation_input_tokens", 0) or 0
        chamada.custo_usd = calcular_custo(
            chamada.modelo, chamada.tokens_entrada, chamada.tokens_saida, chamada.tokens_cache, chamada.tokens_cache_escrita
        )

        if resposta.stop_reason == "refusal":
            raise ErroModelo("recusa_do_modelo")
        if resposta.stop_reason == "max_tokens":
            raise ErroModelo("saida_cortada")
        texto = next((b.text for b in resposta.content if b.type == "text"), None)
        if not texto:
            raise ErroModelo("saida_invalida", "resposta sem texto")
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError as erro:
            raise ErroModelo("saida_invalida", "não é JSON") from erro
        if not isinstance(dados, dict):
            raise ErroModelo("saida_invalida", "JSON não é objeto")
        return dados


class ModeloOpenAI:
    """GPT pela API da OpenAI, com saída estruturada (JSON no esquema, modo estrito).

    Não usa ferramentas: o modelo devolve os dados no formato pedido e o código age.
    """

    def __init__(self, cliente: Any | None = None) -> None:
        if cliente is None:
            import openai

            cliente = cliente_openai()
        self._cliente = cliente

    async def gerar(
        self,
        *,
        papel: str,
        sistema: str,
        conteudo: str,
        esquema: dict[str, Any],
        modelo: str,
        esforco: str = "medium",
        validar: Callable[[dict[str, Any]], None] | None = None,
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> Resultado:
        chamadas: list[Chamada] = []
        ultimo_erro: ErroModelo | None = None
        for _tentativa in range(2):
            chamada = Chamada(papel=papel, modelo=modelo)
            chamadas.append(chamada)
            inicio = time.monotonic()
            try:
                dados = await self._uma_chamada(chamada, papel, sistema, conteudo, esquema, modelo, esforco, temperatura,
                                                max_tokens)
                if validar:
                    try:
                        validar(dados)
                    except Exception as erro:
                        raise ErroModelo("saida_invalida", str(erro)) from erro
                chamada.duracao_ms = int((time.monotonic() - inicio) * 1000)
                return Resultado(dados=dados, chamadas=chamadas)
            except ErroModelo as erro:
                chamada.duracao_ms = int((time.monotonic() - inicio) * 1000)
                chamada.sucesso = False
                chamada.erro = str(erro)
                ultimo_erro = erro
                if erro.motivo not in ("saida_invalida", "saida_cortada"):
                    break
        assert ultimo_erro is not None
        ultimo_erro.chamadas = chamadas  # type: ignore[attr-defined]
        raise ultimo_erro

    async def _uma_chamada(
        self,
        chamada: Chamada,
        papel: str,
        sistema: str,
        conteudo: str,
        esquema: dict[str, Any],
        modelo: str,
        esforco: str,
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        import openai

        parametros: dict[str, Any] = dict(
            model=modelo,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": conteudo}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": f"saida_{papel}", "schema": esquema, "strict": True},
            },
            max_completion_tokens=max_tokens or MAX_TOKENS_OPENAI,
        )
        # Chave do cache da OpenAI: pedidos com a mesma chave vão para a mesma máquina e reaproveitam o prefixo (inclusive
        # entre leads diferentes do mesmo agente). SDK antigo sem o parâmetro: vai pelo corpo do pedido.
        como = _como_passar_a_chave(self._cliente)
        if como == "parametro":
            parametros["prompt_cache_key"] = chave_de_cache(papel, modelo, sistema)
        elif como == "corpo":
            parametros["extra_body"] = {"prompt_cache_key": chave_de_cache(papel, modelo, sistema)}
        if modelo.startswith("gpt-4"):
            # Temperatura baixa: zero para extrair fatos, um pouco de variação para conversar.
            parametros["temperature"] = 0 if papel == "extrator" else (0.4 if temperatura is None else max(0.0, min(float(temperatura), 2.0)))
        else:
            # Modelos de raciocínio não aceitam temperatura; o controle é o esforço.
            parametros["reasoning_effort"] = esforco if esforco in ("low", "medium", "high") else "medium"
        try:
            resposta = await self._cliente.chat.completions.create(**parametros)
        except openai.AuthenticationError as erro:
            raise ErroModelo("chave_recusada", str(erro)) from erro
        except openai.PermissionDeniedError as erro:
            raise ErroModelo("sem_permissao", str(erro)) from erro
        except openai.RateLimitError as erro:
            sem_credito = getattr(erro, "code", None) == "insufficient_quota"
            raise ErroModelo("sem_credito" if sem_credito else "limite_de_uso", str(erro)) from erro
        except openai.BadRequestError as erro:
            raise ErroModelo("pedido_invalido", str(erro)) from erro
        except openai.APIStatusError as erro:
            raise ErroModelo("provedor_fora_do_ar", f"{erro.status_code}") from erro
        except openai.APIConnectionError as erro:
            raise ErroModelo("sem_conexao", str(erro)) from erro

        uso = resposta.usage
        cache = getattr(getattr(uso, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        chamada.modelo = getattr(resposta, "model", modelo) or modelo
        chamada.tokens_cache = cache
        chamada.tokens_entrada = max(0, (getattr(uso, "prompt_tokens", 0) or 0) - cache)
        chamada.tokens_saida = getattr(uso, "completion_tokens", 0) or 0
        chamada.custo_usd = calcular_custo(
            chamada.modelo, chamada.tokens_entrada, chamada.tokens_saida, chamada.tokens_cache
        )

        escolha = resposta.choices[0]
        if getattr(escolha.message, "refusal", None):
            raise ErroModelo("recusa_do_modelo", str(escolha.message.refusal)[:200])
        if escolha.finish_reason == "length":
            raise ErroModelo("saida_cortada")
        if escolha.finish_reason == "content_filter":
            raise ErroModelo("recusa_do_modelo", "filtro de conteúdo")
        texto = escolha.message.content
        if not texto:
            raise ErroModelo("saida_invalida", "resposta sem texto")
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError as erro:
            raise ErroModelo("saida_invalida", "não é JSON") from erro
        if not isinstance(dados, dict):
            raise ErroModelo("saida_invalida", "JSON não é objeto")
        return dados


class ModeloPorNome:
    """Escolhe o provedor pelo nome do modelo: `claude-...` vai para a Anthropic, o resto para a OpenAI.

    Assim cada agente pode usar um modelo diferente só trocando o nome na configuração.
    Os clientes são criados só quando usados, para não exigir as duas chaves.
    """

    def __init__(self) -> None:
        self._provedores: dict[str, Modelo] = {}

    def _provedor(self, modelo: str) -> Modelo:
        nome = "anthropic" if modelo.startswith("claude-") else "openai"
        if nome not in self._provedores:
            try:
                self._provedores[nome] = ModeloAnthropic() if nome == "anthropic" else ModeloOpenAI()
            except Exception as erro:  # chave ausente
                raise ErroModelo("chave_recusada", f"provedor {nome} sem chave configurada: {erro}") from erro
        return self._provedores[nome]

    async def gerar(
        self,
        *,
        papel: str,
        sistema: str,
        conteudo: str,
        esquema: dict[str, Any],
        modelo: str,
        esforco: str = "medium",
        validar: Callable[[dict[str, Any]], None] | None = None,
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> Resultado:
        provedor = self._provedor(modelo)
        extra = {"temperatura": temperatura} if temperatura is not None and isinstance(provedor, ModeloOpenAI) else {}
        return await provedor.gerar(
            papel=papel, sistema=sistema, conteudo=conteudo, esquema=esquema,
            modelo=modelo, esforco=esforco, validar=validar, max_tokens=max_tokens, **extra,
        )


Roteiro = Callable[[str, str], dict[str, Any] | Awaitable[dict[str, Any]]]


class ModeloFalso:
    """Modelo de mentira para testes: cada papel responde com uma função (sistema, conteudo) -> dados."""

    def __init__(self, respostas: dict[str, Roteiro | list[dict[str, Any]] | dict[str, Any]]) -> None:
        self._respostas = respostas
        self.pedidos: list[dict[str, str]] = []

    async def gerar(
        self,
        *,
        papel: str,
        sistema: str,
        conteudo: str,
        esquema: dict[str, Any],
        modelo: str,
        esforco: str = "medium",
        validar: Callable[[dict[str, Any]], None] | None = None,
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> Resultado:
        self.pedidos.append({"papel": papel, "sistema": sistema, "conteudo": conteudo, "temperatura": temperatura,
                             "esquema": esquema, "max_tokens": max_tokens})
        resposta = self._respostas.get(papel)
        if resposta is None:
            raise ErroModelo("provedor_fora_do_ar", f"sem resposta falsa para {papel}")
        if callable(resposta):
            dados = resposta(sistema, conteudo)
            if hasattr(dados, "__await__"):
                dados = await dados  # type: ignore[assignment]
        elif isinstance(resposta, list):
            if not resposta:
                raise ErroModelo("provedor_fora_do_ar", f"respostas falsas de {papel} acabaram")
            dados = resposta.pop(0)
        else:
            dados = resposta
        if validar:
            try:
                validar(dados)  # type: ignore[arg-type]
            except Exception as erro:
                raise ErroModelo("saida_invalida", str(erro)) from erro
        chamada = Chamada(papel=papel, modelo="falso", tokens_entrada=len(conteudo) // 4, tokens_saida=20)
        return Resultado(dados=dados, chamadas=[chamada])  # type: ignore[arg-type]
