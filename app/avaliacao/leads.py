"""Lead simulado: três tipos com a mesma interface.

  abrir() -> list[Fala]                          o que o lead manda primeiro
  await responder(enviadas, rodada=n) -> list[Fala] | None    None = o lead saiu

  * LeadRoteiro: falas fixas na ordem (testes pontuais e o cenário 06).
  * LeadCartao: o padrão. Determinístico: responde pelo assunto da pergunta da IA, então se adapta à ordem das
    perguntas e o cassete fica estável enquanto o agente não muda. Sem assunto para a pergunta, responde o
    "padrão" ("não sei te dizer"); depois de 3 padrões seguidos a rodada fica INVÁLIDA (o cartão não cobre a
    pergunta: é falha do cenário, não do agente). Pergunta já respondida: repete a resposta ("como eu falei, ...").
    Balão sem pergunta nem pedido que só retoma um assunto já respondido (recapitulação, "vou buscar seu CEP"):
    responde "ok" (origem "ack"), sem contar como repetição nem como padrão.
  * LeadIA: só no modo real. Um modelo faz o papel do lead a partir do cartão da persona, com checagem
    anti-cooperação (fato revelado sem a IA ter perguntado invalida a rodada, sem culpar o agente).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.avaliacao.cenario import Assunto, Fala, Lead
from app.avaliacao.efeitos import URL_CONTRATO
from app.modelo import Chamada, ErroModelo, Modelo


def _com_origem(fala: Fala, origem: str) -> Fala:
    return fala.model_copy(update={"origem": origem}, deep=True)


class LeadRoteiro:
    def __init__(self, cartao: Lead) -> None:
        self.cartao = cartao
        self._proxima = 0
        self.invalido: str | None = None
        self.chamadas: list[Chamada] = []

    def abrir(self) -> list[Fala]:
        self._proxima = 1
        return [_com_origem(self.cartao.falas[0], "roteiro:0")]

    async def responder(self, enviadas: list[str], *, rodada: int = 0) -> list[Fala] | None:
        if self._proxima >= len(self.cartao.falas):
            return None
        fala = _com_origem(self.cartao.falas[self._proxima], f"roteiro:{self._proxima}")
        self._proxima += 1
        return [fala]


def _primeira_posicao(assunto: Assunto, texto: str) -> int | None:
    posicoes = [m.start() for regex in assunto.quando if (m := re.search(regex, texto))]
    return min(posicoes) if posicoes else None


MAX_PADRAO_SEGUIDOS = 3                                      # respostas "padrão" seguidas antes de invalidar a rodada


class LeadCartao:
    """Responde pela pergunta da IA. Se a IA perguntar duas coisas, responde só a primeira que casar."""

    def __init__(self, cartao: Lead) -> None:
        self.cartao = cartao
        self.usados: set[int] = set()
        self.gatilhos_usados: set[int] = set()
        self.link_visto = False
        self.assinou = False
        self._objecoes: list[Fala] = []
        self._silencios = 0
        self._padroes_seguidos = 0
        self.invalido: str | None = None
        self.chamadas: list[Chamada] = []

    def abrir(self) -> list[Fala]:
        return [_com_origem(f, "abertura") for f in self.cartao.abertura]

    @staticmethod
    def perguntas(enviadas: list[str]) -> list[str]:
        """Os balões que o lead "lê" para escolher a resposta: os que têm pergunta; sem pergunta, todos."""
        textos = [t for t in enviadas if (t or "").strip() and not URL_CONTRATO.search(t)]
        com_pergunta = [t for t in textos if "?" in t]
        return com_pergunta or textos

    def escolher(self, enviadas: list[str]) -> tuple[int | None, bool]:
        """(índice do assunto, já usado?) — o primeiro assunto não usado que casa, pela posição no texto.

        Lê primeiro só as FRASES com "?" (o que a IA perguntou de fato): em "você pode conferir a inscrição no site da
        OAB. Podemos seguir com o seu caso?", o lead responde ao "podemos seguir", não ao "conferir". Se nenhuma
        frase de pergunta casar, lê os balões inteiros ("Pode me passar o seu CPF, por favor." sem "?").
        """
        baloes = self.perguntas(enviadas)
        frases = [p.strip() for b in baloes for p in re.findall(r"[^.!?\n]*\?", b) if p.strip()]
        if frases and (achado := self._escolher_em(frases))[0] is not None:
            if achado[1]:
                # A frase com "?" retoma um assunto já respondido, mas o mesmo balão pede uma coisa nova ("Qual foi a
                # última vez que você trabalhou de carteira assinada? Por favor, me informe o mês e o ano da sua
                # demissão."): o lead responde a coisa nova. Sem assunto novo no balão, continua sendo repetição.
                no_balao = self._escolher_em(baloes)
                if no_balao[0] is not None and not no_balao[1]:
                    return no_balao
            return achado
        return self._escolher_em(baloes)

    def _escolher_em(self, textos: list[str]) -> tuple[int | None, bool]:
        melhor: tuple[int, int, int] | None = None
        repetido: int | None = None
        for i_balao, texto in enumerate(textos):
            for i, assunto in enumerate(self.cartao.assuntos):
                posicao = _primeira_posicao(assunto, texto)
                if posicao is None:
                    continue
                if i in self.usados and assunto.uma_vez:
                    repetido = i if repetido is None else repetido
                    continue
                if melhor is None or (i_balao, posicao, i) < melhor:
                    melhor = (i_balao, posicao, i)
        if melhor is not None:
            return melhor[2], False
        return repetido, repetido is not None

    async def responder(self, enviadas: list[str], *, rodada: int = 0) -> list[Fala] | None:
        textos = [t for t in enviadas if (t or "").strip()]
        if not textos:
            self._silencios += 1
            if self._silencios > 1:
                return None                                   # ninguém respondeu duas vezes: o lead desiste
            return [Fala(texto=self.cartao.sem_resposta, origem="sem_resposta")]
        self._silencios = 0
        tudo = "\n".join(textos)

        # 1. Link do contrato: trava (objeções) ou assina.
        if URL_CONTRATO.search(tudo) and not self.link_visto:
            self.link_visto = True
            if self.cartao.ao_receber_link == "trava":
                self._objecoes = [_com_origem(f, "objecao_link") for f in self.cartao.objecoes_link]
        if self.link_visto and not self.assinou and self.cartao.ao_receber_link != "nada":
            if self._objecoes:
                return [self._objecoes.pop(0)]
            self.assinou = True
            return [_com_origem(self.cartao.assinou, "assinou")]

        # 2. Gatilhos: depois de algo que a IA disse, ou numa rodada fixa.
        for i, gatilho in enumerate(self.cartao.gatilhos):
            if i in self.gatilhos_usados:
                continue
            if (gatilho.depois_de and re.search(gatilho.depois_de, tudo)) or (gatilho.turno and gatilho.turno == rodada):
                self.gatilhos_usados.add(i)
                if gatilho.fala is None:
                    continue
                fala = _com_origem(gatilho.fala, f"gatilho:{i}")
                # Um "pode perguntar" (fala sem objeção) não engole a pergunta de verdade do mesmo balão ("Vou te fazer
                # mais algumas perguntas sobre o seu trabalho. Você ficou com sequela?"): o lead responde o assunto.
                # Objeção, recusa ou pergunta do lead ("como vou saber que não é golpe?", "não vou passar meu CPF pelo
                # WhatsApp") vem primeiro, mesmo sem "?": a IA trata e pergunta de novo.
                if (not gatilho.e_objecao() and gatilho.depois_de
                        and (assunto := self._assunto_no_balao(gatilho.depois_de, textos)) is not None):
                    self._padroes_seguidos = 0
                    return [self._responder_assunto(assunto)]
                self._padroes_seguidos = 0
                return [fala]

        # 3. Assunto da pergunta.
        indice, repetido = self.escolher(textos)
        if indice is not None:
            self._padroes_seguidos = 0
        if indice is not None and repetido and not self._pede_algo(textos):
            # Recapitulação ou aviso sem pergunta nem pedido ("Ok, você foi demitido em março de 2023 e não recebeu
            # seguro-desemprego.", "Recebi seu CEP. Vou buscar nos Correios."): a pessoa diz "ok", não repete a resposta.
            return [Fala(texto=self.cartao.reconhece, origem="ack")]
        if indice is not None and repetido:
            return [self._repetir(indice)]
        if indice is not None:
            return [self._responder_assunto(indice)]
        self._padroes_seguidos += 1
        if self._padroes_seguidos > MAX_PADRAO_SEGUIDOS:
            pergunta = " / ".join(self.perguntas(textos))
            self.invalido = f"lead sem assunto para: {pergunta[:300]}"
            return None
        return [Fala(texto=self.cartao.padrao, origem="padrao")]

    def _pede_algo(self, textos: list[str]) -> bool:
        """Algum balão (fora o link do contrato) tem pergunta ou pedido ("informe", "me passa", "preciso")?"""
        from app.avaliacao.checagens import PEDIDO

        lidos = [t for t in textos if (t or "").strip() and not URL_CONTRATO.search(t)]
        return any("?" in t or PEDIDO.search(t) for t in lidos)

    def _assunto_no_balao(self, regex: str, textos: list[str]) -> int | None:
        """Assunto ainda não usado que uma pergunta do mesmo balão do gatilho pede, ou None."""
        for balao in textos:
            if "?" not in balao or not re.search(regex, balao):
                continue
            indice, repetido = self.escolher([balao])
            if indice is not None and not repetido:
                return indice
        return None

    def _responder_assunto(self, indice: int) -> Fala:
        """Resposta de um assunto ainda não usado. Se tudo o que ele revela o lead já contou em outro assunto (a data
        da demissão, dita na pergunta da carteira, pedida de novo pelo Período de Graça), é pergunta repetida: o lead
        responde como repetição (origem repetida:N), e a checagem pergunta_repetida acusa."""
        fatos = set(self.cartao.assuntos[indice].fatos)
        ja_contados = {f for i in self.usados if i != indice for f in self.cartao.assuntos[i].fatos}
        self.usados.add(indice)
        if fatos and fatos <= ja_contados:
            return self._repetir(indice)
        return _com_origem(self.cartao.assuntos[indice].responde, f"assunto:{indice}")

    def _repetir(self, indice: int) -> Fala:
        """A IA perguntou de novo: o lead repete a resposta original, como uma pessoa faria ("como eu falei, ...")."""
        original = self.cartao.assuntos[indice].responde
        prefixo = self.cartao.repetida.strip()
        texto = original.texto_corrido() if original.tipo != "imagem" else (original.texto or "já te mandei")
        if re.match(r"(?i)\s*(j[aá] (te )?(falei|disse|respondi)|como (te |eu )?(falei|disse))", texto):
            prefixo = ""                                      # a resposta já é uma reclamação ("já te falei isso, ...")
        texto = f"{prefixo} {texto}".strip()
        if original.tipo == "imagem":
            return original.model_copy(update={"texto": texto, "origem": f"repetida:{indice}"}, deep=True)
        return Fala(tipo=original.tipo, texto=texto, origem=f"repetida:{indice}")


# ---------------------------------------------------------------------------- lead de IA (só modo real)
ESQUEMA_LEAD = {
    "type": "object",
    "properties": {
        "mensagens": {"type": "array", "items": {
            "type": "object",
            "properties": {"tipo": {"type": "string", "enum": ["texto", "audio"]}, "texto": {"type": "string"}},
            "required": ["tipo", "texto"], "additionalProperties": False}},
        "fatos_usados": {"type": "array", "items": {"type": "string"}},
        "acao": {"type": "string", "enum": ["continuar", "sair"]},
    },
    "required": ["mensagens", "fatos_usados", "acao"],
    "additionalProperties": False,
}

SISTEMA_LEAD = """Você faz o papel de uma pessoa que procurou um escritório de advocacia pelo WhatsApp.
Você NÃO é assistente: é o lead. Responda como essa pessoa escreveria no celular.

Quem você é: {persona}

O que é verdade sobre você (o cartão; chaves entre colchetes):
{verdade}

Regras:
1. Só revele um fato do cartão quando a atendente perguntar sobre ele. Não adiante informação.
2. O que não está no cartão você não sabe: diga "não lembro" ou "não sei".
3. Mensagens curtas, no estilo da pessoa. Uma ou duas mensagens por vez.
4. Em "fatos_usados", liste as chaves do cartão que você revelou NESTA resposta (vazio se nenhuma).
5. Em "acao", use "sair" só se a conversa terminou (despedida) ou se a atendente parou de responder.
{objecoes}"""


class LeadIA:
    """Lead feito por um modelo (gpt-4.1-mini, temperatura 0,9), que vê só o que a IA enviou."""

    def __init__(self, cartao: Lead, modelo: Modelo, *, nome_modelo: str = "gpt-4.1-mini", temperatura: float = 0.9) -> None:
        self.cartao = cartao
        self.modelo = modelo
        self.nome_modelo = nome_modelo
        self.temperatura = temperatura
        self.conversa: list[tuple[str, str]] = []              # (quem, texto): "atendente" | "voce"
        self.perguntado: set[str] = set()                      # fatos que a IA já perguntou (pelos regex dos assuntos)
        self.chamadas: list[Chamada] = []
        self.invalido: str | None = None

    def abrir(self) -> list[Fala]:
        falas = [_com_origem(f, "abertura") for f in self.cartao.abertura]
        self.conversa += [("voce", f.texto_corrido()) for f in falas]
        return falas

    def _sistema(self) -> str:
        verdade = "\n".join(f"- [{k}] {v}" for k, v in self.cartao.verdade.items())
        objecoes = ""
        if self.cartao.gatilhos:
            objecoes = "\nObjeções que você faz, uma vez cada, quando fizer sentido:\n" + "\n".join(
                f"- {g.fala.texto_corrido()}" for g in self.cartao.gatilhos if g.fala)
        return SISTEMA_LEAD.format(persona=self.cartao.persona or "pessoa comum, escreve de forma simples",
                                   verdade=verdade, objecoes=objecoes)

    def _marcar_perguntas(self, textos: list[str]) -> None:
        for assunto in self.cartao.assuntos:
            if any(re.search(regex, t) for regex in assunto.quando for t in textos):
                self.perguntado.update(assunto.fatos)

    def conferir(self, fatos_usados: list[str]) -> str | None:
        """Anti-cooperação: o fato tem de existir no cartão e só aparece depois que a IA perguntou."""
        chaves = set(self.cartao.verdade)
        mapeados = {f for a in self.cartao.assuntos for f in a.fatos}
        for fato in fatos_usados:
            if fato not in chaves:
                return f"o lead de IA usou um fato fora do cartão: {fato}"
            if fato in mapeados and fato not in self.perguntado:
                return f"o lead de IA revelou '{fato}' antes de a IA perguntar"
        return None

    async def responder(self, enviadas: list[str], *, rodada: int = 0) -> list[Fala] | None:
        textos = [t for t in enviadas if (t or "").strip()]
        self.conversa += [("atendente", t) for t in textos]
        self._marcar_perguntas(textos)
        historico = "\n".join(f"[{'atendente' if quem == 'atendente' else 'você'}] {t}" for quem, t in self.conversa[-40:])
        conteudo = f"CONVERSA ATÉ AGORA:\n{historico}\n\nEscreva a sua próxima resposta." if textos else \
            f"CONVERSA ATÉ AGORA:\n{historico}\n\nA atendente não respondeu nada desde a sua última mensagem."
        try:
            resultado = await self.modelo.gerar(papel="lead_simulado", sistema=self._sistema(), conteudo=conteudo,
                                                esquema=ESQUEMA_LEAD, modelo=self.nome_modelo, esforco="low",
                                                temperatura=self.temperatura)
        except ErroModelo as erro:
            self.chamadas.extend(getattr(erro, "chamadas", []))
            self.invalido = f"o lead de IA falhou: {erro.motivo}"
            return None
        self.chamadas.extend(resultado.chamadas)
        dados = resultado.dados
        if motivo := self.conferir([str(f) for f in dados.get("fatos_usados") or []]):
            self.invalido = motivo
            return None
        if dados.get("acao") == "sair":
            return None
        falas = [Fala(tipo="audio" if m.get("tipo") == "audio" else "texto", texto=str(m.get("texto") or "").strip(),
                      origem="ia") for m in dados.get("mensagens") or [] if str(m.get("texto") or "").strip()]
        if not falas:
            return None
        self.conversa += [("voce", f.texto_corrido()) for f in falas]
        return falas

    def descrever(self) -> str:
        return json.dumps({"persona": self.cartao.persona, "verdade": self.cartao.verdade}, ensure_ascii=False)


def criar(cartao: Lead, *, tipo: str | None = None, modelo: Modelo | None = None) -> Any:
    tipo = tipo or cartao.tipo
    if cartao.tipo == "roteiro":
        return LeadRoteiro(cartao)                           # roteiro fixo não vira cartão nem IA
    if tipo == "ia":
        if modelo is None:
            raise ValueError("o lead de IA precisa de um modelo (só no modo real)")
        return LeadIA(cartao, modelo)
    return LeadCartao(cartao)
