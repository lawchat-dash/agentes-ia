"""Indexação e busca da base de conhecimento (o "processar_conhecimento" do sistema de referência, refeito).

Indexação (`indexar_pendentes`): documentos em 'processando' (arquivos, textos colados e os documentos virtuais de FAQ e
objeções, gerados da config do agente) viram trechos de ~1.000 caracteres com título, escopo de papel, hash e vetor.
O vetor de um trecho cujo hash (modelo + texto) já existe no agente é reaproveitado: editar 1 FAQ vetoriza 1 trecho.

Busca (`preparar` + `buscar`): o que é pequeno fica fixo no sistema; o resto vira candidato. A consulta é a fala nova
do lead; a nota é cosseno + reforço por palavra; cortes absoluto, relativo, por documento e teto de caracteres.
Sem vetor (modo falso, falha do provedor, dimensão diferente): busca por palavras com o mesmo escopo e os mesmos limites.
Desenho: docs/BASE_DE_CONHECIMENTO.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app import conhecimento as base
from app import vetores
from app.modelo import Chamada

log = logging.getLogger("agentesia")

NOMES_VIRTUAIS = {"faq": "Perguntas frequentes", "objecoes": "Objeções"}
FONTE_DO_TIPO = {"faq": "faq", "objecoes": "objecao"}
TEMPO_CONSULTA_S = 5.0          # embedding da consulta: passou disto, a busca usa palavras (o extrator leva ~1-3 s)
# FAQ/objeções fixas no sistema: além dos caracteres, o prompt antigo mostra no máximo 40 FAQ e 30 objeções
# (app/cerebro/agente.montar_conhecimento); acima disso vão para a busca em vez de sumirem em silêncio.
FIXO_MAX_FAQ, FIXO_MAX_OBJECOES = 40, 30


# ============================================================================ busca (sem IO)
@dataclass
class Preparo:
    """O que fica fixo no SISTEMA e o que vai para a busca, para um papel."""
    fixo: dict[str, Any] = field(default_factory=dict)     # dados_escritorio, faq, objecoes, documentos (Trecho)
    candidatos: list[dict[str, Any]] = field(default_factory=list)
    faq_fixa: bool = True
    documentos_fixos: bool = True


@dataclass
class Busca:
    consultou: bool = False
    consulta: str = ""
    modo: str = "sem_base"           # sem_base | pulou | vetor | palavras
    trechos: list[base.Trecho] = field(default_factory=list)
    chamada: Chamada | None = None
    dimensao_diferente: bool = False
    erro: str | None = None
    papel: str | None = None
    candidatos: int = 0

    def para_contexto(self, usados: list[int] | None = None) -> dict[str, Any]:
        """O que fica em agentesia_turnos.contexto.conhecimento (auditoria e avaliação)."""
        return {"consultou": self.consultou, "modo": self.modo, "consulta": self.consulta, "papel": self.papel,
                "candidatos": self.candidatos, "erro": self.erro, "dimensao_diferente": self.dimensao_diferente,
                "trechos": [{"n": n, "id": t.id, "fonte": t.fonte, "titulo": t.titulo or t.documento, "nota": t.nota,
                             "caracteres": len(t.texto)} for n, t in enumerate(self.trechos, 1)],
                "usados": list(usados or []),
                "custo_usd": self.chamada.custo_usd if self.chamada else 0.0}


def _tamanho_util(t: dict[str, Any]) -> int:
    texto = t.get("conteudo") or ""
    return len(texto.split("\n", 1)[1]) if texto.startswith("Documento: ") and "\n" in texto else len(texto)


def preparar(conhecimento: dict[str, Any] | None, papel: str | None, *, indexados: list[dict[str, Any]] | None = None,
             sem_indice: list[tuple[str, str]] | None = None, modelo_vetor: str | None = None) -> Preparo:
    """Decide fixo × buscado para o papel e monta os candidatos da busca.

    - DADOS DO ESCRITÓRIO: fixos até 1.500 caracteres; o excedente vira candidato.
    - FAQ + objeções do papel: fixas se somarem até 3.000 caracteres; senão, todas vão para a busca.
    - Documentos do papel: fixos se somarem até 2.000 caracteres; senão, buscados.
    `indexados`: trechos com vetor (do banco). `sem_indice`: documentos ainda sem vetor [(nome, texto)].
    Itens de FAQ/objeção vêm sempre da config (a fonte da verdade); o índice só empresta o vetor pelo hash."""
    conhecimento = conhecimento or {}
    indexados = indexados or []
    preparo = Preparo()
    dados_fixos, dados_resto = base.separar_dados(str(conhecimento.get("dados_escritorio") or ""))
    if dados_fixos:
        preparo.fixo["dados_escritorio"] = dados_fixos
    if dados_resto:
        preparo.candidatos += [{"documento": "Dados do escritório", "fonte": "documento", "titulo": titulo, "conteudo": texto,
                                "papeis": []} for titulo, texto in base.dividir_com_titulo("Dados do escritório", dados_resto)]

    # FAQ e objeções do papel.
    itens = [i for i in base.itens_da_config(conhecimento) if base.serve_para(i["papeis"], papel)]
    cabe = (sum(len(i["conteudo"]) for i in itens) <= base.FIXO_FAQ_OBJECOES
            and sum(1 for i in itens if i["fonte"] == "faq") <= FIXO_MAX_FAQ
            and sum(1 for i in itens if i["fonte"] == "objecao") <= FIXO_MAX_OBJECOES)
    if cabe:
        preparo.fixo["faq"] = [f for f in conhecimento.get("faq") or [] if isinstance(f, dict)
                               and base.serve_para(base.papeis_validos(f.get("papeis")), papel)]
        preparo.fixo["objecoes"] = [o for o in conhecimento.get("objecoes") or [] if isinstance(o, dict)
                                    and base.serve_para(base.papeis_validos(o.get("papeis")), papel)]
    else:
        preparo.faq_fixa = False
        por_hash = {t.get("hash"): t for t in indexados if t.get("fonte") in ("faq", "objecao") and t.get("hash")}
        for item in itens:
            achado = por_hash.get(vetores.hash_do_texto(modelo_vetor, item["conteudo"])) if modelo_vetor else None
            preparo.candidatos.append({**item, **({"vetor": achado["vetor"], "vetor_n": achado.get("vetor_n"), "id": achado.get("id")}
                                                  if achado else {})})

    # Documentos do papel (indexados + ainda sem índice).
    docs = [t for t in indexados if (t.get("fonte") or "documento") == "documento" and base.serve_para(t.get("papeis"), papel)]
    pendentes = [(n, t) for n, t in (sem_indice or []) if (t or "").strip()]
    if sum(_tamanho_util(t) for t in docs) + sum(len(t) for _, t in pendentes) <= base.FIXO_DOCUMENTOS:
        inteiros: dict[str, list[str]] = {}
        for t in docs:
            texto = t["conteudo"]
            texto = texto.split("\n", 1)[1] if texto.startswith("Documento: ") and "\n" in texto else texto
            inteiros.setdefault(t.get("documento") or "", []).append(texto.strip())
        fixos = [base.Trecho(nome, "\n".join(partes)) for nome, partes in inteiros.items()]
        fixos += [base.Trecho(n, t.strip()) for n, t in pendentes]
        if fixos:
            preparo.fixo["documentos"] = fixos
    else:
        preparo.documentos_fixos = False
        preparo.candidatos += [{**t, "fonte": "documento"} for t in docs]
        preparo.candidatos += [{"documento": n, "fonte": "documento", "titulo": titulo, "conteudo": texto, "papeis": []}
                               for n, t in pendentes for titulo, texto in base.dividir_com_titulo(n, t)]
    return preparo


def _vetor_n(t: dict[str, Any]) -> list[float]:
    if t.get("vetor_n") is None:
        t["vetor_n"] = vetores.normalizar(list(t.get("vetor") or []))
    return t["vetor_n"]


def escolher_por_vetor(trechos: list[dict[str, Any]], vetor: list[float], consulta: str = "", papel: str | None = None,
                       minimo: float = vetores.LIMIAR_MINIMO, relativo: float = base.CORTE_RELATIVO,
                       quantos: int = base.TRECHOS_POR_TURNO, por_documento: int = base.POR_DOCUMENTO,
                       teto: int = base.TETO_PADRAO) -> list[base.Trecho]:
    """Trechos mais parecidos com a consulta: nota = cosseno + 0,08 × reforço por palavra; cortes absoluto (`minimo`),
    relativo (80% da melhor), até `quantos` (no máximo `por_documento` do mesmo documento) e `teto` caracteres.
    Cada Trecho volta com a nota e o id; o melhor primeiro."""
    consulta_n = vetores.normalizar(vetor)
    candidatos = [t for t in trechos if base.serve_para(t.get("papeis"), papel) and t.get("vetor")]
    pontos = []
    for i, t in enumerate(candidatos):
        nota = vetores.produto(_vetor_n(t), consulta_n)
        if consulta:
            nota += base.PESO_LEXICO * base.reforco_lexico(consulta, t["conteudo"])
        pontos.append((nota, i))
    return base._cortar(candidatos, pontos, minimo=minimo, relativo=relativo, quantos=quantos,
                        por_documento=por_documento, teto=teto)


def dimensao_diferente(trechos: list[dict[str, Any]], dimensoes: int) -> bool:
    """Vetores guardados com outra dimensão (ex.: indexados no modo falso, ou outro modelo)."""
    com_vetor = [t for t in trechos if t.get("vetor")]
    return bool(com_vetor) and sum(1 for t in com_vetor if len(t["vetor"]) != dimensoes) * 2 >= len(com_vetor)


def limites(conhecimento: dict[str, Any] | None) -> dict[str, Any]:
    """Limites configuráveis por agente (config.conhecimento): teto_documentos, trechos_por_turno, nota_minima."""
    conhecimento = conhecimento or {}

    def numero(chave: str, padrao: float, menor: float, maior: float) -> float:
        try:
            valor = float(conhecimento.get(chave) if conhecimento.get(chave) not in (None, "") else padrao)
        except (TypeError, ValueError):
            valor = padrao
        return max(menor, min(valor, maior))

    return {"teto": int(numero("teto_documentos", base.TETO_PADRAO, base.TETO_MINIMO, base.TETO_MAXIMO)),
            "quantos": int(numero("trechos_por_turno", base.TRECHOS_POR_TURNO, 1, 8)),
            "minimo": numero("nota_minima", vetores.LIMIAR_MINIMO, 0.0, 0.95)}


async def buscar(candidatos: list[dict[str, Any]], novas: list[str], *, papel: str | None = None,
                 ultima_pergunta_ia: str | None = None, vetorizador: Any = None,
                 cache: vetores.CacheDeConsultas | None = None, minimo: float = vetores.LIMIAR_MINIMO,
                 teto: int = base.TETO_PADRAO, quantos: int = base.TRECHOS_POR_TURNO,
                 por_documento: int = base.POR_DOCUMENTO, tempo_maximo_s: float = TEMPO_CONSULTA_S) -> Busca:
    """A consulta do turno. Roda em paralelo com o extrator (o pipeline cria a tarefa antes do cérebro).
    Embedding que falha ou passa de `tempo_maximo_s`: a busca cai para palavras e o turno segue."""
    no_papel = [c for c in candidatos if base.serve_para(c.get("papeis"), papel)]
    busca = Busca(papel=papel, candidatos=len(no_papel))
    if not no_papel:
        return busca                                            # nada a buscar: sem bloco no prompt
    if not base.precisa_consultar(novas):
        busca.modo = "pulou"
        return busca
    busca.consultou, busca.consulta = True, base.montar_consulta(novas, ultima_pergunta_ia)
    com_vetor = [c for c in no_papel if c.get("vetor")]
    sem_vetor = [c for c in no_papel if not c.get("vetor")]
    real = vetorizador is not None and not getattr(vetorizador, "falso", False)
    escolhidos: list[base.Trecho] = []
    if real and com_vetor and dimensao_diferente(com_vetor, getattr(vetorizador, "dimensoes", vetores.DIMENSOES)):
        busca.dimensao_diferente = True
        real = False
    if real and com_vetor:
        modelo = getattr(vetorizador, "modelo", vetores.MODELO)
        try:
            vetor = cache.pegar(modelo, busca.consulta) if cache is not None else None
            if vetor is None:
                # Teto de tempo: o cliente da OpenAI espera até 10 min (com 2 novas tentativas) e o turno esperaria junto.
                resultado = await asyncio.wait_for(vetorizador.vetorizar([busca.consulta]), timeout=tempo_maximo_s)
                vetor = resultado.vetores[0]
                busca.chamada = Chamada(papel="conhecimento_consulta", modelo=modelo, tokens_entrada=resultado.tokens,
                                        custo_usd=resultado.custo_usd)
                if cache is not None:
                    cache.guardar(modelo, busca.consulta, vetor)
            busca.modo = "vetor"
            escolhidos = escolher_por_vetor(com_vetor, vetor, busca.consulta, papel, minimo=minimo, quantos=quantos,
                                            por_documento=por_documento, teto=teto)
        except Exception as erro:                               # sem vetor da consulta: cai na busca por palavras
            motivo = (f"embedding passou de {tempo_maximo_s:g} s" if isinstance(erro, asyncio.TimeoutError)
                      else str(erro))[:300]
            log.warning("vetor da consulta falhou; usando busca por palavras: %s", motivo)
            busca.erro = motivo
            busca.chamada = Chamada(papel="conhecimento_consulta", modelo=modelo, sucesso=False, erro=motivo)
            busca.modo, sem_vetor = "palavras", no_papel
    else:
        busca.modo, sem_vetor = "palavras", no_papel
    resta = teto - sum(len(t.texto) for t in escolhidos)
    if sem_vetor and resta >= 500 and len(escolhidos) < quantos:
        ja = {(t.documento, t.texto) for t in escolhidos}
        extras = base.escolher_por_palavras(sem_vetor, busca.consulta, papel=papel, teto=resta,
                                            quantos=quantos - len(escolhidos), por_documento=por_documento)
        escolhidos += [t for t in extras if (t.documento, t.texto) not in ja]
    busca.trechos = escolhidos
    return busca


# ============================================================================ banco
_CACHE_TRECHOS: dict[str, tuple[Any, list[dict[str, Any]]]] = {}


def _vetor_do_banco(valor: Any) -> list[float]:
    if isinstance(valor, str):
        return json.loads(valor.replace("{", "[").replace("}", "]"))
    return list(valor or [])


def texto_virtual(tipo: str, conhecimento: dict[str, Any] | None) -> str:
    """Texto do documento virtual (FAQ ou objeções): o que se vê no painel e o que muda quando a config muda."""
    fonte = FONTE_DO_TIPO[tipo]
    itens = [i for i in base.itens_da_config(conhecimento) if i["fonte"] == fonte]
    return "\n\n".join(i["conteudo"] + (f"\nPapéis: {', '.join(i['papeis'])}" if i["papeis"] else "") for i in itens)


async def sincronizar_virtuais(pool: Any, id_escritorio: str, id_agente: str, conhecimento: dict[str, Any] | None) -> int:
    """Mantém os documentos virtuais de FAQ e objeções do agente. Texto mudou (inclusive só os papéis) = 'processando'
    (a reindexação reaproveita o vetor de quem não mudou). Devolve quantos voltaram para 'processando'."""
    mudaram = 0
    for tipo, nome in NOMES_VIRTUAIS.items():
        texto = texto_virtual(tipo, conhecimento)
        voltou = await pool.fetchval(
            """insert into agentesia_documentos (id_escritorio, id_agente, tipo, nome, formato, tamanho_bytes, texto, caracteres)
               values ($1::uuid, $2::uuid, $3, $4, 'texto', $5, $6, $7)
               on conflict (id_agente, tipo) where tipo in ('faq', 'objecoes') do update
                 set texto = excluded.texto, caracteres = excluded.caracteres, tamanho_bytes = excluded.tamanho_bytes,
                     situacao = case when agentesia_documentos.texto is distinct from excluded.texto
                                     then 'processando' else agentesia_documentos.situacao end,
                     erro = case when agentesia_documentos.texto is distinct from excluded.texto
                                 then null else agentesia_documentos.erro end
               returning situacao = 'processando'""",
            id_escritorio, id_agente, tipo, nome, len(texto.encode()), texto, len(texto))
        mudaram += 1 if voltou else 0
    return mudaram


async def _trechos_do_documento(pool: Any, doc: Any) -> list[dict[str, Any]]:
    """Trechos a gravar: [{titulo, conteudo, fonte, papeis}]."""
    if doc["tipo"] in FONTE_DO_TIPO:
        bruto = await pool.fetchval("select config from agentesia_agentes where id = $1", doc["id_agente"])
        config = json.loads(bruto) if isinstance(bruto, str) else (bruto or {})
        fonte = FONTE_DO_TIPO[doc["tipo"]]
        return [{"titulo": i["titulo"], "conteudo": i["conteudo"], "fonte": fonte, "papeis": i["papeis"]}
                for i in base.itens_da_config(config.get("conhecimento")) if i["fonte"] == fonte]
    papeis = list(doc["papeis"] or [])
    return [{"titulo": titulo, "conteudo": texto, "fonte": "documento", "papeis": papeis}
            for titulo, texto in base.dividir_com_titulo(doc["nome"], doc["texto"] or "")]


async def indexar_pendentes(pool: Any, vetorizador: vetores.Vetorizador, limite: int = 20) -> int:
    """Documentos em 'processando' viram trechos com vetor. Vetor de hash já conhecido no agente é reaproveitado."""
    modelo = getattr(vetorizador, "modelo", vetores.MODELO)
    dimensoes = getattr(vetorizador, "dimensoes", vetores.DIMENSOES)
    documentos = await pool.fetch(
        """select id, id_escritorio, id_agente, tipo, nome, texto, papeis from agentesia_documentos
           where situacao = 'processando' and ativo and id_agente is not null order by criado_em limit $1""", limite)
    feitos = 0
    from app import cobranca
    for doc in documentos:
        if await cobranca.bloqueado(pool, str(doc["id_escritorio"])):
            continue                                   # saldo da IA acabou: o documento espera em 'processando'
        try:
            trechos = await _trechos_do_documento(pool, doc)
            if not trechos and doc["tipo"] not in FONTE_DO_TIPO:
                raise ValueError("documento sem texto")
            for t in trechos:
                t["hash"] = vetores.hash_do_texto(modelo, t["conteudo"])
            conhecidos = {l["hash"]: _vetor_do_banco(l["vetor"]) for l in await pool.fetch(
                """select distinct on (hash) hash, vetor from agentesia_documento_trechos
                   where id_agente = $1 and modelo = $2 and dimensoes = $3 and hash = any($4::text[])""",
                doc["id_agente"], modelo, dimensoes, [t["hash"] for t in trechos])}
            novos = [t for t in trechos if t["hash"] not in conhecidos]
            resultado = await vetorizador.vetorizar([t["conteudo"] for t in novos]) if novos else vetores.Vetorizado([], 0, 0.0)
            for t, v in zip(novos, resultado.vetores):
                conhecidos[t["hash"]] = v
            async with pool.acquire() as conexao, conexao.transaction():
                ainda = await conexao.fetchval(
                    "select situacao from agentesia_documentos where id = $1 for update", doc["id"])
                if ainda != "processando":              # apagado ou mexido no meio do caminho
                    continue
                await conexao.execute("delete from agentesia_documento_trechos where id_documento = $1", doc["id"])
                await conexao.executemany(
                    """insert into agentesia_documento_trechos (id_documento, id_agente, id_escritorio, ordem, conteudo, vetor,
                                                                papeis, titulo, fonte, hash, modelo, dimensoes)
                       values ($1, $2, $3, $4, $5, $6::real[], $7::text[], $8, $9, $10, $11, $12)""",
                    [(doc["id"], doc["id_agente"], doc["id_escritorio"], i, t["conteudo"], conhecidos[t["hash"]],
                      t["papeis"], t["titulo"], t["fonte"], t["hash"], modelo, len(conhecidos[t["hash"]]))
                     for i, t in enumerate(trechos)])
                await conexao.execute(
                    "update agentesia_documentos set situacao = 'pronto', tokens = $2, erro = null where id = $1",
                    doc["id"], resultado.tokens or sum(len(t["conteudo"]) // 4 for t in trechos))
                if resultado.custo_usd:
                    from app.modelo import Chamada
                    await cobranca.gravar_chamadas(
                        conexao, id_escritorio=str(doc["id_escritorio"]), id_agente=str(doc["id_agente"]),
                        chamadas=[Chamada(papel="conhecimento", modelo=modelo, tokens_entrada=resultado.tokens or 0,
                                          custo_usd=resultado.custo_usd)])
            feitos += 1
        except Exception as erro:
            log.warning("falha ao indexar o documento %s: %s", doc["id"], erro)
            await pool.execute("update agentesia_documentos set situacao = 'erro', erro = $2 where id = $1",
                               doc["id"], str(erro)[:500])
    return feitos


async def trechos_do_agente(pool: Any, id_agente: str, id_escritorio: str | None = None) -> list[dict[str, Any]]:
    """Trechos prontos do agente (filtro por agente e, quando dado, por escritório), com o vetor já normalizado.
    Cache em memória pela versão da base (max atualizado_em + quantidade): edição no painel vale no turno seguinte."""
    versao = await pool.fetchrow(
        """select max(atualizado_em) as quando, count(*) as quantos,
                  count(*) filter (where situacao = 'pronto') as prontos
           from agentesia_documentos where id_agente = $1::uuid and ativo""", id_agente)
    chave = f"{id_agente}:{id_escritorio or ''}"
    marca = (versao["quando"], versao["quantos"], versao["prontos"]) if versao else None
    guardado = _CACHE_TRECHOS.get(chave)
    if guardado and guardado[0] == marca:
        return guardado[1]
    linhas = await pool.fetch(
        """select t.id, t.id_documento, d.nome, t.conteudo, t.vetor, t.papeis, t.titulo, t.fonte, t.hash, t.modelo, t.dimensoes
           from agentesia_documento_trechos t
           join agentesia_documentos d on d.id = t.id_documento
           join agentesia_agentes a on a.id = t.id_agente
           where t.id_agente = $1::uuid and d.id_agente = t.id_agente
             and t.id_escritorio = a.id_escritorio and d.id_escritorio = a.id_escritorio   -- defesa: nunca de outro escritório
             and ($2::uuid is null or a.id_escritorio = $2::uuid)
             and d.ativo and d.situacao = 'pronto'
           order by d.ordem, d.criado_em, t.ordem""", id_agente, id_escritorio)
    trechos = []
    for l in linhas:
        vetor = _vetor_do_banco(l["vetor"])
        trechos.append({"id": str(l["id"]), "id_documento": str(l["id_documento"]), "documento": l["nome"],
                        "conteudo": l["conteudo"], "vetor": vetor, "vetor_n": vetores.normalizar(vetor),
                        "papeis": list(l["papeis"] or []), "titulo": l["titulo"] or l["nome"], "fonte": l["fonte"] or "documento",
                        "hash": l["hash"], "modelo": l["modelo"], "dimensoes": l["dimensoes"]})
    _CACHE_TRECHOS[chave] = (marca, trechos)
    return trechos


async def marcar_para_reindexar(pool: Any, id_agente: str, modelo: str, dimensoes: int) -> int:
    """Trechos com outro modelo ou outra dimensão: os documentos voltam para 'processando' (reindexa tudo do agente)."""
    linhas = await pool.fetch(
        """update agentesia_documentos set situacao = 'processando', erro = null
           where id_agente = $1::uuid and situacao = 'pronto' and id in (
             select id_documento from agentesia_documento_trechos
             where id_agente = $1::uuid and (modelo <> $2 or dimensoes <> $3))
           returning id""", id_agente, modelo, dimensoes)
    return len(linhas)


async def registrar_lacuna(pool: Any, *, id_escritorio: str, id_agente: str, papel: str | None, pergunta: str,
                           id_lead: str | None = None, id_turno: str | None = None) -> dict[str, Any] | None:
    """Pergunta sem resposta na base: a mesma dúvida aberta soma em `vezes`."""
    normalizada = base.normalizar_pergunta(pergunta)
    if not normalizada:
        return None
    linha = await pool.fetchrow(
        """insert into agentesia_conhecimento_lacunas
             (id_escritorio, id_agente, papel, pergunta, pergunta_normalizada, ultimo_lead, ultimo_turno)
           values ($1::uuid, $2::uuid, $3, $4, $5, $6::uuid, $7::uuid)
           on conflict (id_agente, pergunta_normalizada) where situacao = 'aberta' do update
             set vezes = agentesia_conhecimento_lacunas.vezes + 1, ultima_em = now(), papel = excluded.papel,
                 ultimo_lead = excluded.ultimo_lead, ultimo_turno = excluded.ultimo_turno
           returning id, vezes""",
        id_escritorio, id_agente, papel, pergunta.strip()[:500], normalizada, id_lead, id_turno)
    return {"id": str(linha["id"]), "vezes": linha["vezes"]} if linha else None
