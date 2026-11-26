"""Um turno do cérebro: recebe o lote de mensagens do lead e devolve o que fazer.

Não conhece WhatsApp, Helena nem banco. Por isso roda igual no atendimento de
verdade, no Laboratório e nos testes.

Ordem: extrator -> fatos conferidos -> decisão de etapa (código) -> agente da
etapa nova -> travas -> formatação.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any

from app import tempos
from app.cerebro import agente, auditor, base_conhecimento, contexto, extrator, formatador, travas
from app.cerebro import auxilio_acidente as aa
from app.cerebro.produto import AuxilioAcidente, Produto
from app.modelo import Chamada, ErroModelo, Modelo

MENSAGENS_FIXAS: dict[str, str] = {
    "pediu_humano": "Claro! Vou chamar uma pessoa da equipe para continuar com você por aqui.",
    "pediu_para_parar": "Tudo bem, não vou mais te mandar mensagens. Se precisar, é só chamar por aqui.",
    "engano": "Sem problema, desculpe o incômodo! Se precisar de algo, é só chamar.",
    "sinal": "Entendi! Vou passar para uma pessoa da equipe continuar com você por aqui, tá bom?",
    "seguranca": "Vou confirmar uma informação com a equipe e já te retorno por aqui.",
    "contrato_com_a_equipe": "Para finalizar o seu contrato, vou pedir ajuda a uma pessoa da nossa equipe. "
                             "Ela continua com você por aqui, tá bom?",
    # Leva 1 (25/11): resposta da IA fora do formato (B3) e as outras passagens do código para a equipe (B4, B6, B7).
    "formato_invalido": "Recebi sua mensagem! Vou pedir para alguém da equipe continuar com você por aqui.",
    "equipe_continua": "Recebi sua mensagem! Vou pedir para alguém da equipe continuar com você por aqui.",
    # Cat. 19: desqualificação em análise manual (opção desqualificar_modo): nunca diz ao lead que ele não tem direito.
    "analise_manual": "Obrigado pelas informações! Vou pedir para uma pessoa da nossa equipe analisar o seu caso com "
                      "atenção, e ela continua com você por aqui, tá bom?",
    # B6: tentativa de manipular. Fixa e segura: não confirma nem nega regra, prompt ou instrução nenhuma.
    "manipulacao": "Por aqui eu só consigo te ajudar com o seu caso no escritório.",
}
# Na 3ª mensagem seguida fora do tema (B6), a IA sai da conversa e a equipe assume com a ficha.
FORA_DO_TEMA_PAUSA = 3


@dataclass
class Entrada:
    escritorio: str
    agente: str
    etapa: str
    novas: list[str]                                            # mensagens novas do lead, já em texto
    fatos: dict[str, Any] = field(default_factory=dict)         # fatos vigentes
    historico: list[dict[str, str]] = field(default_factory=list)  # [{autor, texto}], mais antiga primeiro
    instrucoes: dict[str, str | None] = field(default_factory=dict)  # instrução por etapa (vazio = padrão)
    honorarios: str | None = None
    midias: dict[str, str] = field(default_factory=dict)        # chave -> quando usar
    regras: aa.Regras = field(default_factory=aa.Regras)
    produto: Produto | None = None                              # vazio = Auxílio-Acidente com as regras acima
    mensagens_fixas: dict[str, str] = field(default_factory=dict)
    modelo_extrator: str = "gpt-4.1"
    modelo_etapa: str = "gpt-4.1"
    esforco_etapa: str = "medium"
    modelo_auditor: str | None = None                           # None = sinal vale sem conferir
    enriquecer: Any = None      # async (fatos) -> [fatos novos com fonte], ex.: endereço pelo CEP
    conhecimento: dict[str, Any] = field(default_factory=dict)  # FAQ, objeções e dados do escritório
    fatos_sistema: dict[str, Any] = field(default_factory=dict) # nome, primeiro contato, contrato (do banco)
    temperatura: float | None = None                            # do assistente (agentes do catálogo)
    agora: datetime | None = None                               # data de hoje no prompt (vazio = agora; os testes fixam)
    comeco_conversa: Any = None                                 # memoria.ComecoDaConversa: ficha e antigas fora da janela
    obrigatorios_contrato: tuple[str, ...] | None = None        # do modelo ZapSign do agente (vazio = padrão do contrato)


@dataclass
class Saida:
    situacao: str = "respondido"                                # respondido | silencio | erro
    motivo: str = ""
    etapa_antes: str = ""
    etapa_depois: str = ""
    estado_lead: str | None = None                              # None = não muda; pausado | encerrado
    motivo_estado: str | None = None
    mensagens: list[dict[str, Any]] = field(default_factory=list)   # prontas para envio
    fatos_novos: list[dict[str, Any]] = field(default_factory=list)
    fatos_rejeitados: list[dict[str, Any]] = field(default_factory=list)
    fatos_depois: dict[str, Any] = field(default_factory=dict)
    sinais: list[str] = field(default_factory=list)
    intencoes: dict[str, bool] = field(default_factory=dict)
    decisoes: list[dict[str, Any]] = field(default_factory=list)
    faltam: list[str] = field(default_factory=list)
    reprovacoes: list[list[dict[str, str]]] = field(default_factory=list)  # uma lista por tentativa
    eventos: list[dict[str, Any]] = field(default_factory=list)
    chamadas: list[Chamada] = field(default_factory=list)
    contexto: dict[str, Any] = field(default_factory=dict)      # o que foi enviado à IA
    ficha: str | None = None                                    # ficha do caso na passagem para humano (pipeline, B2)

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evento(tipo: str, gravidade: str, responsavel: str, descricao: str, **detalhe: Any) -> dict[str, Any]:
    return {"tipo": tipo, "gravidade": gravidade, "responsavel": responsavel,
            "descricao": descricao, "detalhe": detalhe}


async def _auditar_sinais(modelo: Modelo, entrada: Entrada, sinais: list[str], saida: "Saida",
                          partes: dict[str, tuple[str, ...]] | None = None) -> tuple[list[str], str]:
    """Confere cada sinal com o auditor. Devolve os válidos e a mensagem para o lead (do primeiro válido)."""
    if not entrada.modelo_auditor:
        return list(sinais), ""
    validos, mensagem, conferidos = [], "", []
    for sinal in sinais:
        auditoria = await auditor.auditar_sinal(modelo, sinal=sinal, historico=entrada.historico, novas=entrada.novas,
                                                nome_modelo=entrada.modelo_auditor, escritorio=entrada.escritorio,
                                                partes=partes)
        saida.chamadas.extend(auditoria.chamadas)
        conferidos.append({"sinal": sinal, "valido": auditoria.valido, "motivo": auditoria.motivo, "falhou": auditoria.falhou})
        if auditoria.falhou:
            saida.eventos.append(_evento("auditor_falhou", "aviso", "provedor",
                                         f"Não deu para conferir o sinal {sinal}; a equipe foi chamada por segurança.",
                                         motivo=auditoria.motivo))
        if auditoria.valido:
            validos.append(sinal)
            mensagem = mensagem or auditoria.mensagem
        else:
            saida.eventos.append(_evento("sinal_recusado", "info", "lawchat",
                                         f"Sinal {sinal} não confirmado: {auditoria.motivo}", sinal=sinal))
    saida.contexto["auditor"] = conferidos
    return validos, mensagem


def _guardar_tentativa(saida: "Saida", texto: str, reprovacoes: list[str]) -> None:
    """Guarda o texto que a trava barrou e por quê: sem isso, ninguém sabia o que caiu (só a versão refeita ficava).
    Formato lido pelo sistema de teste: contexto["tentativas"] = [{"texto", "reprovacoes": [motivo, ...]}, ...]."""
    saida.contexto.setdefault("tentativas", []).append({"texto": texto, "reprovacoes": list(reprovacoes)})


def _fixa(entrada: Entrada, chave: str) -> list[dict[str, Any]]:
    texto = entrada.mensagens_fixas.get(chave) or MENSAGENS_FIXAS[chave]
    return formatador.formatar([{"tipo": "texto", "texto": texto}])


async def _esperar_base(entrada: Entrada) -> Any:
    """Resultado da busca na base (já rodando junto do extrator); o tempo de espera entra em "tempos"."""
    with tempos.passo("espera_base"):
        return await base_conhecimento.resolver(entrada)


async def processar(modelo: Modelo, entrada: Entrada) -> Saida:
    """Roda o turno. Erro inesperado (fora de ErroModelo) sobe com as chamadas já pagas em `erro.chamadas`, para o
    pipeline gravar o custo antes de fechar o turno como erro."""
    saida = Saida(etapa_antes=entrada.etapa, etapa_depois=entrada.etapa, fatos_depois=dict(entrada.fatos))
    try:
        return await _processar(modelo, entrada, saida)
    except Exception as erro:
        try:
            proprias = [c for c in getattr(erro, "chamadas", None) or [] if c not in saida.chamadas]
            erro.chamadas = list(saida.chamadas) + proprias  # type: ignore[attr-defined]
        except Exception:                      # exceção que não aceita atributo novo
            pass
        raise


# Pedido de pessoa de verdade: atendente, humano, "não é robô", "pessoa real". "Especialista", "advogado" e "pessoalmente"
# sozinhos não contam: são a abertura do anúncio da Meta e quem quer conhecer o escritório (a IA segue atendendo).
_PESSOA_CLARA = re.compile(r"\b(atendentes?|humanos?|humanas?|pessoa\s+(de\s+verdade|real|f[ií]sica)|uma\s+pessoa|"
                           r"de\s+verdade|rob[oô]s?|bot|m[aá]quina|intelig[eê]ncia\s+artificial|"
                           r"me\s+liga|ligar\s+pra\s+mim|ligar\s+para\s+mim)\b", re.I)
_SO_ANUNCIO = re.compile(r"\b(especialista|advogad[oa]s?|doutor[a]?|pessoalmente|presencial|conhecer\s+os?\s+"
                         r"(profissionais|advogados|escrit[oó]rio)|mais\s+informa[cç][oõ]es|saber\s+mais)\b", re.I)


def pedido_de_pessoa_claro(novas: list[str]) -> bool:
    """O lead pediu uma pessoa no lugar da IA. Falso quando o texto só fala de especialista, advogado, informações ou
    atendimento presencial (a mensagem pronta do anúncio). Sem nenhuma das duas pistas, vale o que o extrator marcou."""
    texto = " ".join(novas or [])
    if _PESSOA_CLARA.search(texto):
        return True
    return not _SO_ANUNCIO.search(texto)


async def _processar(modelo: Modelo, entrada: Entrada, saida: Saida) -> Saida:
    produto = entrada.produto or AuxilioAcidente(entrada.regras)
    terminais = {e.codigo for e in produto.etapas if e.tipo == "terminal"}
    agora = contexto.agora_em_brasilia(entrada.agora)    # um relógio só para o turno inteiro
    catalogo = getattr(produto, "codigo", "") == "catalogo"
    if catalogo and hasattr(produto, "para_o_papel"):
        # O extrator do catálogo é do papel do turno: os campos do contrato só entram onde o contrato é coletado.
        papel_do_turno = entrada.etapa if entrada.etapa in produto.papeis else produto.etapa_inicial()
        produto = produto.para_o_papel(papel_do_turno, entrada.instrucoes.get(papel_do_turno))

    # 1. Extrator: o que o lead disse de novo.
    try:
        with tempos.passo("extrator"):
            extracao = await extrator.extrair(
                modelo, nome_modelo=entrada.modelo_extrator, fatos_conhecidos=entrada.fatos,
                historico=entrada.historico, novas=entrada.novas, produto=produto, agora=agora,
                tolerar_falha=catalogo,
            )
    except ErroModelo as erro:
        saida.chamadas.extend(getattr(erro, "chamadas", []))
        return _falha(saida, "extrator", erro)
    saida.chamadas.extend(extracao.chamadas)
    if extracao.falha:
        # Saída do extrator cortada (repetição sem fim) ou fora do formato: o turno segue sem os fatos de IA deste lote,
        # em vez de pausar o lead já na 1ª falha (ver extrator.FALHAS_TOLERADAS).
        saida.eventos.append(_evento("extrator_falhou", "aviso", "provedor",
                                     f"O extrator falhou ({extracao.falha}); o turno seguiu sem os fatos novos deste "
                                     "lote.", motivo=extracao.falha))
    saida.contexto["extrator"] = {
        "conteudo": extrator.montar_conteudo(entrada.fatos, entrada.historico, entrada.novas, agora),
        "resposta": extracao.bruto,
    }
    if catalogo:
        # Catálogo: só os sinais que o papel atual pode disparar; a videochamada tem prioridade (como no n8n).
        from app.cerebro import sinais as sinais_catalogo
        papel = entrada.etapa if entrada.etapa in produto.papeis else produto.etapa_inicial()
        extracao.sinais = sinais_catalogo.ordenar([s for s in extracao.sinais if s in produto.sinais_do_papel(papel)])
    if catalogo:
        _dados_da_crianca_pela_pergunta(entrada, produto, extracao, saida)
    saida.fatos_novos = [asdict(f) for f in extracao.fatos]
    saida.fatos_rejeitados = extracao.rejeitados
    saida.sinais, saida.intencoes = extracao.sinais, extracao.intencoes
    for fato in extracao.fatos:
        saida.fatos_depois[fato.chave] = fato.valor
    if catalogo and getattr(produto, "contrato", False) and not any(f.get("chave") == "cep" for f in saida.fatos_novos):
        _cep_pelo_texto(entrada, saida)
    if entrada.enriquecer is not None:
        await _enriquecer(entrada, saida)
    for rejeitado in extracao.rejeitados:
        saida.eventos.append(_evento(
            "fato_sem_prova", "aviso", "lawchat",
            f"Fato descartado ({rejeitado['motivo']}): {rejeitado.get('chave')}", fato=rejeitado,
        ))
    for resolvido in extracao.resolvidos:
        # Resposta curta ("Não") ligada pelo código à última pergunta da IA (extrator.pela_pergunta).
        saida.eventos.append(_evento(
            "fato_pela_pergunta", "info", "lawchat",
            f"Resposta curta à última pergunta gravada como {resolvido['chave']} = {resolvido['valor']}", fato=resolvido,
        ))

    # 2. Pedidos do lead que encerram ou passam a conversa, sem chamar o agente.
    if extracao.intencoes.get("pediu_humano") and not pedido_de_pessoa_claro(entrada.novas):
        # A mensagem pronta do anúncio ("Quero falar com um especialista em Auxílio-Acidente") e "quero conhecer
        # pessoalmente" não são pedido de humano: a IA atende normalmente.
        extracao.intencoes["pediu_humano"] = False
        saida.eventos.append(_evento("pediu_humano_ignorado", "info", "lawchat",
                                     "Pedido de humano ignorado: abertura do anúncio ou pedido de atendimento presencial.",
                                     texto=" ".join(entrada.novas)[:200]))
    if (catalogo and extracao.intencoes.get("pediu_humano") and not entrada.fatos.get(MARCA_PEDIU_PESSOA)
            and pedir_pessoa_na_segunda(getattr(produto, "config", {}))):
        # 1º pedido de pessoa: a IA tenta resolver (a pessoa só entra em último caso). No 2º pedido, pausa como antes.
        extracao.intencoes["pediu_humano"] = False
        _gravar_controle(saida, MARCA_PEDIU_PESSOA, True)
        saida.contexto.setdefault("orientacoes_sinal", []).append(ORIENTACAO_PRIMEIRO_PEDIDO)
        saida.eventos.append(_evento("pediu_humano_primeira_vez", "info", "lead",
                                     "Lead pediu uma pessoa pela 1ª vez: a IA tentou resolver por aqui.",
                                     texto=" ".join(entrada.novas)[:200]))
    for intencao, estado in (("pediu_para_parar", "encerrado"), ("engano", "encerrado"), ("pediu_humano", "pausado")):
        if extracao.intencoes.get(intencao):
            saida.estado_lead, saida.motivo_estado, saida.motivo = estado, intencao, intencao
            saida.mensagens = _fixa(entrada, intencao)
            saida.eventos.append(_evento(intencao, "aviso", "lead", f"Lead: {intencao}"))
            return saida
    if barreira := _barreiras(entrada, saida, extracao.intencoes):
        return barreira
    if extracao.sinais:
        from app.cerebro.sinais import partes_do_auditor
        with tempos.passo("auditor"):
            validos, mensagem = await _auditar_sinais(modelo, entrada, extracao.sinais, saida,
                                                      partes_do_auditor(getattr(produto, "beneficio", None)) if catalogo else None)
        saida.sinais = validos
        from app.cerebro.sinais import SEM_PAUSA
        # "Quero ir pessoalmente": na 1ª vez a IA quebra a objeção (por aqui é mais rápido); se insistir, a equipe assume.
        sem_pausa = tuple(s for s in SEM_PAUSA if not (s == "atendimento_presencial" and entrada.fatos.get(MARCA_PRESENCIAL)))
        if validos and all(s in sem_pausa for s in validos):
            if "atendimento_presencial" in validos:
                _gravar_controle(saida, MARCA_PRESENCIAL, True)
            # Sinal que só avisa a equipe (deficiência auditiva): a IA segue a conversa, com a orientação do sinal.
            for sinal in validos:
                saida.eventos.append(_evento("sinal_" + sinal, "aviso", "lead", f"Lead sinalizou: {sinal}",
                                             pausa=False))
            if "deficiencia_auditiva" in validos:
                _gravar_controle(saida, MARCA_SO_TEXTO, True)
            from app.cerebro.sinais import ORIENTACAO_SEM_PAUSA
            saida.contexto.setdefault("orientacoes_sinal", []).extend([ORIENTACAO_SEM_PAUSA[s] for s in validos
                                                   if s != "deficiencia_auditiva" and s in ORIENTACAO_SEM_PAUSA])
            validos = []
        if validos:
            saida.estado_lead, saida.motivo_estado = "pausado", "sinal:" + ",".join(validos)
            saida.motivo = saida.motivo_estado
            saida.mensagens = formatador.formatar([{"tipo": "texto", "texto": mensagem}]) if mensagem else _fixa(entrada, "sinal")
            for sinal in validos:
                saida.eventos.append(_evento("sinal_" + sinal, "aviso", "lead", f"Lead sinalizou: {sinal}"))
            return saida

    if catalogo:
        return await _turno_catalogo(modelo, entrada, produto, saida, agora)

    # 3. O código decide a etapa a partir dos fatos. A coleta do contrato confere os obrigatórios do modelo do agente.
    if entrada.obrigatorios_contrato and "obrigatorios_contrato" in getattr(produto, "__dataclass_fields__", {}):
        produto = replace(produto, obrigatorios_contrato=tuple(entrada.obrigatorios_contrato))
    passo = produto.decidir_etapa(entrada.etapa, saida.fatos_depois, extracao.intencoes)
    saida.etapa_depois, saida.motivo = passo.etapa, passo.motivo
    saida.decisoes = [d.como_dict() for d in passo.decisoes]
    saida.faltam = list(passo.faltam)

    # 4. O agente da etapa NOVA escreve a resposta (a troca já vale neste turno).
    sistema = agente.montar_sistema(
        nome=entrada.agente, escritorio=entrada.escritorio, etapa=passo.etapa,
        instrucao=entrada.instrucoes.get(passo.etapa), produto=produto, conhecimento=entrada.conhecimento,
    )
    sistema = _com_comeco_da_conversa(sistema, entrada)
    bloco_base = base_conhecimento.bloco(await _esperar_base(entrada))   # busca já rodou junto do extrator
    correcao: list[str] | None = [LINHA_FORA_DO_TEMA] if saida.contexto.get("barreira") == "fora_do_tema" else None
    mensagens: list[dict[str, str]] = []
    aprovado = False
    resposta = None
    for _tentativa in range(2):
        conteudo = agente.montar_conteudo(
            etapa=passo.etapa, fatos=saida.fatos_depois, faltam=passo.faltam, motivo=passo.motivo,
            sinais=extracao.sinais, honorarios=entrada.honorarios, midias=entrada.midias,
            historico=entrada.historico, novas=entrada.novas, correcao=correcao, produto=produto,
            fatos_sistema=entrada.fatos_sistema, agora=agora, base=bloco_base,
        )
        try:
            with tempos.passo("agente" if _tentativa == 0 else "agente_correcao"):
                resposta = await agente.responder(
                    modelo, nome_modelo=entrada.modelo_etapa, esforco=entrada.esforco_etapa,
                    sistema=sistema, conteudo=conteudo,
                    esquema=base_conhecimento.com_base(agente.ESQUEMA, entrada.conhecimento),
                )
        except ErroModelo as erro:
            saida.chamadas.extend(getattr(erro, "chamadas", []))
            return _falha(saida, "etapa", erro)
        saida.chamadas.extend(resposta.chamadas)
        saida.contexto["etapa"] = {"sistema": sistema, "conteudo": conteudo, "resposta": resposta.mensagens}
        mensagens = resposta.mensagens

        # 5. Travas: nada sai sem passar por aqui.
        reprovacoes = travas.conferir(
            mensagens, etapa=passo.etapa, honorarios=entrada.honorarios,
            midias=entrada.midias, faltam=passo.faltam, produto=produto,
        )
        saida.reprovacoes.append([asdict(r) for r in reprovacoes])
        if not reprovacoes:
            aprovado = True
            break
        _guardar_tentativa(saida, "\n".join(str(m.get("texto") or m.get("chave") or "") for m in mensagens),
                           [r.orientacao for r in reprovacoes])
        for reprovacao in reprovacoes:
            saida.eventos.append(_evento(
                "trava_" + reprovacao.codigo, "aviso", "lawchat", reprovacao.orientacao, etapa=passo.etapa,
            ))
        correcao = [r.orientacao for r in reprovacoes]

    if not aprovado:
        # Reprovou duas vezes: não manda o texto da IA. Mensagem segura e passa para a equipe.
        saida.estado_lead, saida.motivo_estado = "pausado", "trava_persistente"
        saida.mensagens = _fixa(entrada, "seguranca")
        saida.eventos.append(_evento(
            "trava_persistente", "erro", "lawchat",
            "A IA foi reprovada duas vezes nas travas; conversa passada para a equipe.",
        ))
        return saida

    saida.mensagens = formatador.formatar(mensagens)
    base_conhecimento.registrar(saida, entrada, resposta.base if resposta else None, entrada.etapa)

    # 6. Etapas terminais: depois da mensagem de passagem, a IA sai da conversa.
    if passo.etapa in terminais and passo.etapa != "analise_manual":
        saida.estado_lead, saida.motivo_estado = "encerrado", f"{passo.etapa}:{passo.motivo}"
    elif passo.etapa == "analise_manual":
        saida.estado_lead, saida.motivo_estado = "pausado", "analise_manual:" + passo.motivo
        saida.eventos.append(_evento(
            "analise_manual", "aviso", "lawchat", f"Caso para a equipe avaliar: {passo.motivo}",
        ))
    return saida


async def _turno_catalogo(modelo: Modelo, entrada: Entrada, produto: Any, saida: Saida,
                          agora: datetime | None = None) -> Saida:
    """Agente do funil (catálogo): o prompt do papel conduz; a saída diz se transfere ou aciona ferramenta; o código confere."""
    from app.cerebro import catalogo, sinais as sinais_catalogo

    if entrada.etapa and entrada.etapa not in produto.papeis:
        # Etapa fora dos papéis (contrato assinado): não há agente para ela. Cair no papel inicial fazia o SDR recomeçar a
        # qualificação e gravava o lead de volta em SDR (o card voltava junto). O pipeline já barra antes; isto é a defesa.
        saida.situacao, saida.motivo = "silencio", "etapa_terminal"
        saida.etapa_antes = saida.etapa_depois = entrada.etapa
        saida.mensagens = []
        return saida
    etapa = entrada.etapa or produto.etapa_inicial()
    saida.etapa_antes = saida.etapa_antes or etapa
    # Variáveis {{X}} (nome da atendente, do escritório, honorários, config.variables): o motor troca no roteiro, nas
    # regras, no conhecimento e nas mensagens de entrada e boas-vindas. A linha com variável sem valor sai inteira.
    valores = catalogo.valores_das_variaveis(entrada.agente, entrada.escritorio, entrada.honorarios, produto.config)
    papeis = catalogo.papeis_com_variaveis((produto.config.get("catalogo") or {}).get("papeis") or {}, valores)
    bruto = entrada.instrucoes.get(etapa) or ""
    do_prompt, acoes = catalogo.ferramentas_do_prompt(bruto)
    # "@Transferência: X" cru (prompt gravado sem a expansão do painel) vira a frase de entrada de X: o chip nunca vai
    # ao modelo, que o copiava para o lead.
    prompt = catalogo.expandir_transferencias(bruto, papeis)
    destinos = _destinos_permitidos(entrada, produto, saida, etapa,
                                    list(dict.fromkeys((papeis.get(etapa) or {}).get("destinos", []) + do_prompt)),
                                    do_prompt=do_prompt)
    _arrobas_sem_destino(saida, etapa, bruto)
    ferramentas = produto.ferramentas_do_papel(etapa)      # mapa papel -> ferramentas (zapsign, buscar_cep, alertas, contas)
    # As ações tiradas do prompt passam pelo mesmo filtro do mapa: sem a função de contrato, nada de zapsign.
    acoes = [a for a in dict.fromkeys(acoes + ferramentas["acoes"]) if a != "zapsign" or produto.contrato]
    # O chip "→ @Análise da equipe" no roteiro liga o aviso à equipe do papel (a ferramenta é do motor).
    notificacoes = sinais_catalogo.DO_AGENTE if ferramentas["notificacao"] or catalogo.pede_analise_da_equipe(prompt) else ()
    fatos_sistema = dict(entrada.fatos_sistema)
    regras = _regras_do_periodo(entrada, produto)
    if ferramentas["calculadora"]:
        fatos_sistema.update(contexto.fatos_da_calculadora(saida.fatos_depois, agora, regras))
    # Conferências do sistema neste turno (antigas tools BUSCARCPF e BUSCAR CEP do n8n): vão no conteúdo, não no sistema
    # (o sistema fica igual entre turnos e entra no cache do provedor).
    conferencias = _conferir_cpfs(entrada, saida) if produto.contrato else []
    if linha_cep := _linha_da_busca_de_cep(saida):
        conferencias.append(linha_cep)
    if produto.contrato and etapa == "contratos" and (faltam_contrato := _linha_dados_que_faltam(entrada, saida)):
        conferencias.append(faltam_contrato)
    conhecimento_texto = agente.montar_conhecimento(entrada.conhecimento, catalogo.REGRA_OBJECOES)
    regras_escritorio = (produto.config.get("catalogo") or {}).get("regras")
    sistema = catalogo.montar_sistema(
        prompt=prompt, nome_agente=entrada.agente, escritorio=entrada.escritorio,
        conhecimento_texto=conhecimento_texto, regras=regras_escritorio, destinos=destinos, acoes=acoes,
        fatos_sistema=fatos_sistema, notificacoes=notificacoes, papel=etapa, ferramentas=ferramentas, papeis=papeis,
        honorarios=entrada.honorarios, variaveis=valores, familia=catalogo.familia_do_produto(produto.config))
    _variaveis_sem_valor(entrada, saida, etapa, catalogo.variaveis_sem_valor(
        [prompt, regras_escritorio, conhecimento_texto, entrada.honorarios]
        + [str((c or {}).get(k) or "") for c in ((produto.config.get("catalogo") or {}).get("papeis") or {}).values()
           if isinstance(c, dict) for k in ("mensagem_troca", "boas_vindas")], valores))
    sistema = _com_comeco_da_conversa(sistema, entrada)
    primeira = not any(m.get("autor") == "você" for m in entrada.historico)
    # Boas-vindas do papel: na primeira resposta da conversa e na primeira do papel que acabou de receber o lead
    # (marca gravada na troca). Sem a marca, as boas-vindas de Closer, Contratos e Assinatura nunca eram usadas.
    assumiu = str(entrada.fatos.get(MARCA_BOAS_VINDAS) or "") == etapa
    boas_vindas = (papeis.get(etapa) or {}).get("boas_vindas") if (primeira or assumiu) else None
    if assumiu:
        _gravar_controle(saida, MARCA_BOAS_VINDAS, "")
    # A data com a hora vai no conteúdo, não no sistema: o sistema fica igual entre turnos e entra no cache do provedor.
    # E vai DEPOIS da conversa: de um turno para o outro a conversa só cresce no fim, então ela também entra no cache
    # (prefixo idêntico); a hora no começo do conteúdo quebrava o prefixo logo depois do sistema.
    linhas = ["CONVERSA ATÉ AQUI (mais antiga primeiro):"]
    linhas += [f"{m['autor']}: {m['texto']}" for m in entrada.historico[-60:]] or ["(nenhuma)"]
    linhas += ["", contexto.linha_de_hoje(agora)]
    if bloco_base := base_conhecimento.bloco(await _esperar_base(entrada)):   # busca rodou junto do extrator
        linhas.append("\n" + bloco_base)
    # Mídias que este turno pode mandar: só as do roteiro (sistema do papel, regras, objeções, base) e de config.midias.
    permitidas = catalogo.midias_permitidas(sistema, bloco_base, config=produto.config)
    ja_enviadas = _midias_ja_enviadas(entrada)
    linhas.append("\nMENSAGENS NOVAS DO LEAD:")
    linhas += [f"- {t}" for t in entrada.novas]
    if dados := _dados_informados(saida):
        linhas.append("\nDADOS JÁ INFORMADOS PELO LEAD (não pergunte de novo): " + dados)
    if conferencias:
        linhas += [""] + conferencias
    if linha_portao := _linha_do_portao(entrada, produto, papeis):
        linhas.append("\n" + linha_portao)
    if saida.contexto.get("barreira") == "fora_do_tema":
        linhas.append("\n" + LINHA_FORA_DO_TEMA)
    so_texto = bool(saida.fatos_depois.get(MARCA_SO_TEXTO))
    if so_texto:
        linhas.append("\n(sistema) " + sinais_catalogo.ORIENTACAO_SEM_PAUSA["deficiencia_auditiva"])
    if orientacao_closer := _desqualificacao_no_closer(entrada, produto, saida, etapa, destinos):
        saida.contexto.setdefault("orientacoes_sinal", []).append(orientacao_closer)
    for orientacao in saida.contexto.get("orientacoes_sinal") or []:
        linhas.append("\n(sistema) " + orientacao)
    confirmou = _lead_confirmou_dados(entrada, saida) if "zapsign" in acoes and exigir_confirmacao_contrato(
        produto.config) else True
    if (produto.fatos_do_periodo and "zapsign" not in acoes and saida.fatos_depois.get("acidente_ano") in (None, "")
            and not saida.fatos_depois.get("acidente_quando_incerto")):
        # A vaga "[ocorrido em…]" do resumo saía com o ano de hoje (o "Hoje é" do conteúdo).
        linhas.append("\nData do acidente: o lead ainda não informou (nunca use a data de hoje no lugar dela).")
    if boas_vindas:
        # Só a boas-vindas perdia um turno e deixava sem resposta o "tenho direito?" do lead. O texto dela vem logo depois
        # do rótulo, entre aspas e na linha dele: no fim da regra da pergunta genérica, o modelo o tomava pela pergunta.
        rotulo = "É a primeira resposta." if primeira else \
            "Você acabou de assumir esta conversa (um colega da equipe passou o lead para você); é a sua primeira resposta."
        linhas.append(f"\n{rotulo} Mensagem de boas-vindas: \"{boas_vindas}\"\n"
                      "Comece com ela (pode ajustar o texto) e, na mesma resposta, faça a primeira pergunta do roteiro. "
                      "Se a boas-vindas terminar numa pergunta genérica (\"como posso ajudar?\"), troque essa pergunta "
                      "pela primeira do roteiro.")
    correcao: list[str] | None = None
    marcas = [str(m) for m in (entrada.fatos.get(MARCA_PERGUNTOU) or []) if m]
    novas_marcas: list[str] = []
    tentativas: list[_Tentativa] = []
    for _tentativa in range(2):
        conteudo = "\n".join(linhas) + ("\n\nCORRIJA: " + " ".join(correcao) if correcao else "")
        try:
            with tempos.passo("agente" if _tentativa == 0 else "agente_correcao"):
                resultado = await modelo.gerar(papel="etapa", sistema=sistema, conteudo=conteudo,
                                               esquema=base_conhecimento.com_base(catalogo.esquema(destinos, acoes, notificacoes),
                                                                                  entrada.conhecimento),
                                               modelo=entrada.modelo_etapa,
                                               esforco=entrada.esforco_etapa,
                                               **({"temperatura": entrada.temperatura} if entrada.temperatura is not None else {}))
        except ErroModelo as erro:
            saida.chamadas.extend(getattr(erro, "chamadas", []))
            # A 2ª chamada (a da CORRIJA) falhou no provedor: uma 1ª resposta sem erro e só com trava leve (que nunca
            # pausa) ainda serve. Descartá-la deixava o lead sem resposta por uma falha passageira.
            reserva = next((t for t in tentativas if not t.erros and not any(g.dura for g in t.guardas)), None)
            if reserva is None:
                return _falha(saida, "etapa", erro)
            saida.eventos.append(_evento("segunda_tentativa_falhou", "aviso", "provedor",
                                         f"A correção da IA falhou ({erro.motivo}); seguiu com a 1ª resposta.",
                                         detalhe=erro.detalhe))
            break
        saida.chamadas.extend(resultado.chamadas)
        resposta = resultado.dados
        textos = [str(m.get("texto") or "").strip() for m in resposta.get("mensagens", []) if str(m.get("texto") or "").strip()]
        mensagens = catalogo.separar_midias(textos)
        saida.contexto["etapa"] = {"sistema": sistema, "conteudo": conteudo, "resposta": resposta}
        destino = resposta.get("transferir_para") or ""
        pela_frase = False
        if destino not in destinos:
            # Rede de segurança: a IA escreveu a frase de passagem EXATA de um destino e deixou transferir_para vazio.
            # Leva 1 (B1): sem paráfrase e nunca para "desqualificado" (essa troca ninguém decidiu).
            destino = catalogo.transferencia_pela_frase_exata(
                [m.get("texto", "") for m in mensagens if m["tipo"] == "texto"], destinos, papeis) or ""
            pela_frase = bool(destino)
        erros = catalogo.conferir(mensagens, etapa)
        # Travas do motor sobre a resposta (CPF já conferido, laço, endereço inventado, troca de papel): ver _guardas_do_catalogo.
        guardas = _guardas_do_catalogo(entrada, produto, saida, etapa=etapa, destino=destino,
                                       textos=[m["texto"] for m in mensagens if m["tipo"] == "texto"], papeis=papeis,
                                       acoes=acoes, marcas=marcas, regras=regras, calculadora=ferramentas["calculadora"])
        if sem_fonte := base_conhecimento.guarda_de_fonte(entrada, textos, sistema, "\n".join(linhas)):
            guardas.append(_Guarda("fato_sem_fonte", sem_fonte))    # valor/prazo fora de toda fonte: refaz uma vez (leve)
        guardas += _guardas_de_midia(entrada, mensagens, permitidas, ja_enviadas)
        if resposta.get("ferramenta") == "zapsign" and "zapsign" in acoes and not confirmou:
            guardas.append(_Guarda("contrato_sem_confirmacao", ORIENTACAO_SEM_CONFIRMACAO))
        if (ferramentas["calculadora"] and etapa == "periododegraca" and resposta.get("notificacao") == "analise_humana"
                and (cob := contexto.cobertura_na_data_do_acidente(saida.fatos_depois, regras)) and cob[0] == "dentro"):
            # Lead coberto pelas datas e a IA mandou para a equipe ("não lembro do seguro"): o seguro só importa fora do
            # prazo curto, então segue o roteiro de quem está coberto.
            guardas.append(_Guarda("periodo_coberto_analise",
                                   "Pelos FATOS DO SISTEMA a pessoa estava coberta na data do acidente: não peça análise "
                                   "da equipe por causa de seguro-desemprego ou de data (o seguro não muda nada aqui). "
                                   "Deixe notificacao vazia e siga o roteiro de quem está coberto (passe para o Closer)."))
        if esquecida := _desqualificacao_esquecida(entrada, produto, saida, etapa, destino, destinos):
            guardas.append(_Guarda("desqualificacao_esquecida", esquecida))
        novas_marcas += [g.marca for g in guardas if g.marca and g.marca not in novas_marcas]
        saida.reprovacoes.append([{"codigo": "catalogo", "orientacao": e} for e in erros]
                                 + [{"codigo": g.codigo, "orientacao": g.orientacao} for g in guardas])
        tentativas.append(_Tentativa(resposta, mensagens, destino, erros, guardas, dict(saida.contexto["etapa"]), pela_frase))
        if not erros and not guardas:
            break
        motivos = erros + [g.orientacao for g in guardas]
        _guardar_tentativa(saida, "\n".join(textos), motivos)
        correcao = motivos
    _gravar_marca(saida, MARCA_PERGUNTOU, marcas, novas_marcas)

    escolhida = tentativas[-1]
    if escolhida.erros:
        # A 2ª reprovou nas travas, mas a 1ª só tinha uma trava leve do motor (que não pausa): fica com a 1ª.
        escolhida = next((t for t in tentativas if not t.erros and not any(g.dura for g in t.guardas)), None)
        if escolhida is None:
            saida.estado_lead, saida.motivo_estado = "pausado", "trava_persistente"
            saida.mensagens = _fixa(entrada, "seguranca")
            saida.eventos.append(_evento("trava_persistente", "erro", "lawchat",
                                         "A IA foi reprovada duas vezes nas travas; conversa passada para a equipe."))
            return saida
    if any(g.dura for g in escolhida.guardas) and len(tentativas) > 1:
        # Trava dura que só apareceu na 2ª tentativa: a IA nunca recebeu a CORRIJA dela (não "insistiu"). Fica com uma
        # tentativa anterior sem erro e sem trava dura (a leve dela não pausa), se houver.
        anteriores = {g.codigo for g in tentativas[-2].guardas if g.dura}
        if not any(g.dura and g.codigo in anteriores for g in escolhida.guardas):
            segura = next((t for t in tentativas[:-1] if not t.erros and not any(g.dura for g in t.guardas)), None)
            if segura is not None:
                escolhida = segura
            else:
                # A 1ª tinha outra trava dura e a 2ª obedeceu à CORRIJA dela; a trava dura nova a IA nunca recebeu:
                # vale como leve (segue com a 2ª e fica registrada). Só pausa o mesmo código duro nas duas.
                escolhida = replace(escolhida, guardas=[replace(g, dura=False) for g in escolhida.guardas])
    if duras := [g for g in escolhida.guardas if g.dura]:
        # Repetiria ao lead um pedido que ele já respondeu (CPF que o sistema conferiu, mesma frase de novo): a resposta
        # não sai e a equipe assume, como no laço do zapsign (_correcao_repetida). Era um laço de 16 turnos.
        codigos = ", ".join(dict.fromkeys(g.codigo for g in duras))
        saida.estado_lead, saida.motivo_estado = "pausado", "pedido_repetido"
        saida.motivo = saida.motivo_estado
        saida.mensagens = _fixa(entrada, "contrato_com_a_equipe" if "zapsign" in acoes else "seguranca")
        saida.eventos.append(_evento(
            "pedido_repetido", "aviso", "lawchat",
            "A IA repetiria ao lead um pedido que ele já respondeu, mesmo depois da correção; conversa passada para a "
            "equipe. Travas: " + codigos, travas=[g.codigo for g in duras]))
        return saida
    for guarda in escolhida.guardas:
        if guarda.codigo in ("midia_desconhecida", "portao_de_fatos", "contrato_sem_confirmacao",
                             "desqualificacao_esquecida") or (
                guarda.codigo == "midia_repetida" and catalogo.sem_midias_repetidas(escolhida.mensagens, ja_enviadas)):
            continue                                    # tratadas abaixo: a parte sai da resposta, com evento próprio
        # Trava leve que a 2ª tentativa não resolveu: segue com a resposta (nunca pausa por isso) e fica registrado.
        saida.eventos.append(_evento("trava_" + guarda.codigo, "aviso", "lawchat", guarda.orientacao, etapa=etapa))
    resposta, mensagens, destino = escolhida.resposta, escolhida.mensagens, escolhida.destino
    pedido = str(resposta.get("transferir_para") or "")
    if pedido and pedido not in destinos:
        # Destino fora dos permitidos (para trás, assinatura pela IA, papel inexistente): fica registrado como recusado.
        saida.eventos.append(_evento("destino_recusado", "info", "lawchat",
                                     f"A IA pediu para passar o lead de {etapa} para {pedido}, destino não permitido; "
                                     "a troca não foi feita.", destino=pedido, etapa=etapa))
    destino = _troca_precoce(entrada, saida, destino, papeis, etapa)
    pedido_ao_portao = destino
    destino, mensagens = _portao_de_fatos(entrada, produto, saida, destino, mensagens, papeis, etapa, regras,
                                          ferramentas["calculadora"])
    if _portao_prendeu(entrada, saida, pedido_ao_portao, destino, etapa):
        return saida
    if destino != "desqualificado" and any(g.codigo == "desqualificacao_esquecida" for g in escolhida.guardas):
        # Cat. 20: o lead disse algo que desqualifica o caso, a IA recebeu a correção e insistiu em não desqualificar.
        # Sem travar: a resposta segue, a equipe fica sabendo e o mesmo fato não pede a correção de novo.
        _desqualificacao_insistida(produto, saida, etapa)
    if destino == "desqualificado" and desqualificar_modo(getattr(produto, "config", {})) == "analise_manual":
        # Cat. 19: o escritório prefere que uma pessoa analise antes de negar. Nada de mensagem de negativa ao lead.
        return _desqualificado_em_analise(entrada, saida, etapa)
    if destino and escolhida.pela_frase:
        saida.eventos.append(_evento("troca_pela_frase", "info", "lawchat",
                                     f"A IA escreveu a frase de passagem para {destino} sem marcar transferir_para; "
                                     "o sistema fez a troca pela frase exata.", destino=destino, etapa=etapa, exata=True,
                                     trecho=" ".join(m.get("texto", "") for m in mensagens if m["tipo"] == "texto")[:200]))
    if fora := catalogo.midias_fora_do_roteiro(mensagens, permitidas):
        # Link de mídia que não está no roteiro, mesmo depois da CORRIJA: não vai para a Helena (404 calado ou mídia de
        # outro escritório). A parte sai; sem nada além dela, vai a mensagem fixa. Não pausa o lead.
        mensagens = [m for m in mensagens if not (m["tipo"] == "midia" and m.get("url") in fora)]
        saida.eventos.append(_evento("midia_desconhecida", "aviso", "lawchat",
                                     "A IA tentou mandar um link de mídia que não está no roteiro; a parte não foi enviada.",
                                     urls=fora[:5], etapa=etapa))
        if not mensagens:
            mensagens = [{"tipo": "texto", "texto": entrada.mensagens_fixas.get("seguranca") or MENSAGENS_FIXAS["seguranca"]}]
    if any(g.codigo == "midia_repetida" for g in escolhida.guardas) and (
            sem_repetidas := catalogo.sem_midias_repetidas(mensagens, ja_enviadas)):
        # A IA insistiu em mandar de novo uma mídia que já está no histórico (sem o lead pedir): a mídia sai e o texto
        # segue. Só com a mídia na resposta, ela vai (melhor que deixar o lead sem resposta).
        mensagens = sem_repetidas
        saida.eventos.append(_evento("midia_repetida", "info", "lawchat",
                                     "A IA ia reenviar uma mídia que o lead já recebeu; a mídia não foi enviada de novo.",
                                     etapa=etapa))
    mensagens = _sem_pergunta_ja_respondida(entrada, saida, mensagens, destino, etapa)
    mensagens, demais = catalogo.limitar_audios(mensagens)
    if so_texto and (audios := [m for m in mensagens if m["tipo"] == "midia" and catalogo.e_audio(m.get("url"))]):
        # Lead com deficiência auditiva: o áudio do roteiro não vai (o texto segue).
        mensagens = [m for m in mensagens if m not in audios] or [
            {"tipo": "texto", "texto": "Me conta: como posso te ajudar com o seu caso?"}]
        saida.eventos.append(_evento("audio_para_lead_surdo", "info", "lawchat",
                                     "A IA ia mandar áudio a um lead com deficiência auditiva; o áudio não foi enviado.",
                                     urls=[m.get("url") for m in audios][:5], etapa=etapa))
    if demais:
        saida.eventos.append(_evento("audios_demais", "aviso", "lawchat",
                                     f"A IA ia mandar mais de {catalogo.AUDIOS_POR_RESPOSTA} áudios de uma vez; "
                                     "os excedentes não foram enviados.", urls=demais[:5], etapa=etapa))
    saida.contexto["etapa"] = escolhida.contexto
    base_conhecimento.registrar(saida, entrada, resposta.get("base"), etapa)

    saida.mensagens = [m if m["tipo"] == "midia" else p for m in mensagens
                       for p in (formatador.formatar([m]) if m["tipo"] == "texto" else [{**m, "espera_s": 2.0}])]
    if ferramentas["calculadora"]:
        # Só nos papéis de qualificação (os que têm a calculadora): ali a resposta à pergunta em aberto decide o destino.
        # Na passagem do Closer para Contratos a pergunta é a primeira do destino ("seu nome completo?") e não se segura.
        destino = _segurar_transferencia(entrada, saida, destino, mensagens, papeis, etapa)
    if destino:
        saida.mensagens = _com_frase_de_troca(saida, saida.mensagens, destino, papeis, etapa)
    saida.etapa_depois = destino or etapa
    saida.motivo = f"transferencia:{destino}" if destino else "catalogo"
    ferramenta = resposta.get("ferramenta") or ""
    if ferramenta == "zapsign" and "zapsign" in acoes and not confirmou:
        # Cat. 23: a IA recebeu a CORRIJA (mostrar o resumo e perguntar) e mesmo assim acionou o contrato. Uma tentativa
        # só, sem travar o atendimento: o contrato segue como antes e a equipe fica sabendo pelo evento.
        saida.eventos.append(_evento("contrato_sem_confirmacao", "aviso", "lawchat",
                                     "A IA gerou o contrato sem o lead confirmar o resumo dos dados, mesmo depois da "
                                     "correção; vale conferir os dados do contrato.", etapa=etapa))
    repetida = _correcao_repetida(entrada, saida) if ferramenta == "zapsign" and ferramenta in acoes else None
    if ferramenta == "zapsign" and ferramenta in acoes and not repetida:
        saida.motivo = "dados_confirmados"            # o pipeline confere os dados e gera o contrato pela fila
    if saida.intencoes.get("diz_que_assinou") and etapa == "assinatura":
        saida.motivo = "diz_que_assinou"
    notificacao = resposta.get("notificacao") or ""
    saida.contexto["catalogo"] = {"destinos": destinos, "acoes": acoes, "transferir_para": destino, "ferramenta": ferramenta,
                                  "notificacao": notificacao, "ferramentas_do_papel": ferramentas,
                                  "origem_destino": ("frase" if escolhida.pela_frase else "ia") if destino else None}
    if repetida:
        # O zapsign pediria de novo a mesma correção, sem dado novo do lead: não chama outra vez (era um laço com
        # "o link chega em instantes" a cada volta). A resposta da IA não sai; a equipe assume o contrato.
        saida.contexto["catalogo"]["ferramenta_barrada"] = "correcao_repetida"
        saida.etapa_depois = etapa
        saida.estado_lead, saida.motivo_estado = "pausado", "contrato_correcao_repetida"
        saida.motivo = saida.motivo_estado
        saida.mensagens = _fixa(entrada, "contrato_com_a_equipe")
        saida.eventos.append(_evento(
            "contrato_correcao_repetida", "aviso", "lawchat",
            "O contrato pediria de novo a mesma correção ao lead, sem dado novo; conversa passada para a equipe. "
            "Campos: " + ", ".join(repetida), campos=repetida))
        return saida
    if notificacao in notificacoes:
        # O roteiro pediu análise de uma pessoa: mesma saída de um sinal confirmado (pausa e aviso "sinal:x").
        saida.sinais = [notificacao]
        saida.etapa_depois = etapa
        saida.estado_lead, saida.motivo_estado = "pausado", "sinal:" + notificacao
        saida.motivo = saida.motivo_estado
        saida.eventos.append(_evento("sinal_" + notificacao, "aviso", "lead", f"Agente pediu: {notificacao}"))
    if etapa == "desqualificado" and saida.etapa_depois == "sdr":
        _gravar_controle(saida, MARCA_VOLTOU_AO_SDR, True)    # a volta à qualificação vale uma vez por conversa
    if saida.etapa_depois != etapa and (papeis.get(saida.etapa_depois) or {}).get("boas_vindas"):
        # O papel novo só fala na próxima mensagem do lead: a marca faz a primeira resposta dele usar as boas-vindas.
        _gravar_controle(saida, MARCA_BOAS_VINDAS, saida.etapa_depois)
    return saida


_PERGUNTA = re.compile(r"[^?.!\n]*\?")


def _perguntas_respondidas(historico: list[dict[str, str]], novas: list[str]) -> list[str]:
    """Perguntas (normalizadas) que a IA já fez e que o lead respondeu depois (alguma mensagem dele veio em seguida,
    no histórico ou no lote novo)."""
    from app.cerebro.extrator import normalizar

    respondidas: list[str] = []
    lead_depois = bool(novas)
    for mensagem in reversed(historico):
        if mensagem.get("autor") == "lead":
            lead_depois = True
        elif mensagem.get("autor") == "você" and lead_depois:
            respondidas += [p for p in (normalizar(q) for q in _PERGUNTA.findall(str(mensagem.get("texto") or ""))) if p]
    return respondidas


def _sem_pergunta_ja_respondida(entrada: Entrada, saida: Saida, mensagens: list[dict[str, Any]], destino: str,
                                etapa: str) -> list[dict[str, Any]]:
    """Balão da IA cujas perguntas todas repetem (quase igual) uma pergunta que ela já fez e o lead já respondeu sai
    antes do envio ("Você recebeu auxílio-doença na época do acidente? Você comentou que não recebeu."), com evento.
    Só quando sobra outro balão com pergunta (ou a passagem): o lead nunca fica sem o próximo passo. Com o lead pedindo
    para repetir ou explicar, a repetição é o certo e fica."""
    from app.cerebro.extrator import normalizar

    if _PEDE_ESCLARECIMENTO.search(normalizar(" ".join(entrada.novas))):
        return mensagens
    respondidas = _perguntas_respondidas(entrada.historico, entrada.novas)
    if not respondidas:
        return mensagens

    def repete(pergunta: str) -> bool:
        return len(pergunta) >= 15 and any(
            difflib.SequenceMatcher(None, pergunta, antiga).ratio() > 0.85
            or (len(antiga) >= 20 and (antiga in pergunta or pergunta in antiga)) for antiga in respondidas)

    repetidos = []
    for indice, m in enumerate(mensagens):
        perguntas = [normalizar(q) for q in _PERGUNTA.findall(str(m.get("texto") or ""))] if m["tipo"] == "texto" else []
        if perguntas and all(repete(p) for p in perguntas):
            repetidos.append(indice)
    if not repetidos:
        return mensagens
    restantes = [m for i, m in enumerate(mensagens) if i not in repetidos]
    if not any(m["tipo"] == "texto" for m in restantes) or not (
            destino or any(m["tipo"] == "texto" and "?" in str(m.get("texto") or "") for m in restantes)):
        return mensagens
    saida.eventos.append(_evento("pergunta_ja_respondida", "info", "lawchat",
                                 "A IA ia repetir uma pergunta que o lead já respondeu; o balão não foi enviado.",
                                 etapa=etapa, textos=[str(mensagens[i].get("texto") or "")[:200] for i in repetidos]))
    return restantes


def _destinos_permitidos(entrada: Entrada, produto: Any, saida: Saida, etapa: str, brutos: list[str],
                         do_prompt: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Para onde o papel atual pode passar o lead: só para frente no funil (desqualificar vale sempre). Contratos não
    passa para Assinatura: quem põe o lead lá é a geração do contrato (ação gerar_contrato), depois do link existir.
    O que a config antiga traz fora disso (agentes ativados com contratos→assinatura) sai calado; o que o PROMPT pede
    fora disso ('volte para o @Agente SDR') é erro de cadastro e fica registrado uma vez por conversa (marca).
    Exceção: o Desqualificado devolve o lead ao SDR quando ele diz que uma informação mudou, uma vez por conversa
    (marca MARCA_VOLTOU_AO_SDR); na segunda vez o destino é ignorado e registrado."""
    ordem = list(produto.papeis)                       # carregar() já ordena pelo funil
    destinos: list[str] = []
    ignorados: list[tuple[str, str]] = []
    volta_ao_sdr = (etapa == "desqualificado" and permitir_volta_sdr(getattr(produto, "config", {}))
                    and not entrada.fatos.get(MARCA_VOLTOU_AO_SDR))
    for destino in brutos:
        if destino not in produto.papeis or destino == etapa:
            continue
        if etapa == "contratos" and destino == "assinatura":
            ignorados.append((destino, "destino_ignorado"))
        elif volta_ao_sdr and destino == "sdr":
            destinos.append(destino)
        elif destino != "desqualificado" and etapa in ordem and ordem.index(destino) < ordem.index(etapa):
            ignorados.append((destino, "destino_para_tras_ignorado"))
        else:
            destinos.append(destino)
    if ignorados:
        saida.contexto["destinos_ignorados"] = [d for d, _ in ignorados]
        vistos = [str(m) for m in (entrada.fatos.get(MARCA_DESTINOS_IGNORADOS) or []) if m]
        novos = [(d, tipo) for d, tipo in ignorados if d in do_prompt and f"{etapa}>{d}" not in vistos]
        for destino, tipo in novos:
            motivo = ("a etapa Assinatura é da geração do contrato" if tipo == "destino_ignorado"
                      else "o funil só anda para a frente")
            saida.eventos.append(_evento(tipo, "info", "cadastro",
                                         f"O roteiro de {etapa} manda passar o lead para {destino}, mas {motivo}: o "
                                         "destino foi ignorado.", destino=destino, etapa=etapa))
        _gravar_marca(saida, MARCA_DESTINOS_IGNORADOS, vistos, [f"{etapa}>{d}" for d, _ in novos])
    return destinos


def _arrobas_sem_destino(saida: Saida, etapa: str, prompt: str) -> None:
    """"@Agente Financeiro" no roteiro (papel que não existe): o destino não vai para a IA; a equipe fica sabendo uma
    vez por conversa (evento de cadastro), como no n8n o 'destino_inexistente' da troca."""
    from app.cerebro import catalogo

    soltos = catalogo.arrobas_sem_destino(prompt)
    if not soltos:
        return
    # fatos_depois já tem as marcas que _destinos_permitidos gravou neste turno (a mesma chave).
    vistos = [str(m) for m in (saida.fatos_depois.get(MARCA_DESTINOS_IGNORADOS) or []) if m]
    novos = [t for t in soltos if f"{etapa}>{t}" not in vistos]
    for trecho in novos:
        saida.eventos.append(_evento("arroba_sem_destino", "aviso", "cadastro",
                                     f"O roteiro de {etapa} cita {trecho}, que não é um agente deste produto: a troca "
                                     "não é oferecida à IA. Corrija o chip no prompt.", trecho=trecho, etapa=etapa))
    _gravar_marca(saida, MARCA_DESTINOS_IGNORADOS, vistos, [f"{etapa}>{t}" for t in novos])


def _troca_precoce(entrada: Entrada, saida: Saida, destino: str, papeis: dict[str, Any], etapa: str) -> str:
    """Troca de papel na primeira resposta da IA (ou antes do mínimo de mensagens do lead do papel) é recusada: o lead
    que só mandou "oi, vi o anúncio" não pode sair desqualificado nem passado adiante ('tool fantasma'). O papel pode
    liberar com transferir_na_primeira_resposta; min_mensagens_lead_para_transferir (padrão 0) exige mais conversa."""
    if not destino:
        return destino
    cfg = papeis.get(etapa) if isinstance(papeis.get(etapa), dict) else {}
    primeira = not any(m.get("autor") == "você" for m in entrada.historico)
    try:
        minimo = int(cfg.get("min_mensagens_lead_para_transferir") or 0)
    except (TypeError, ValueError):
        minimo = 0
    do_lead = sum(1 for m in entrada.historico if m.get("autor") == "lead") + len(entrada.novas)
    if (primeira and not cfg.get("transferir_na_primeira_resposta")) or do_lead < minimo:
        saida.eventos.append(_evento("troca_precoce_recusada", "info", "lawchat",
                                     f"A IA quis passar o lead para {destino} cedo demais (primeira resposta ou pouca "
                                     "conversa); a troca não foi feita.", destino=destino, etapa=etapa,
                                     mensagens_do_lead=do_lead))
        return ""
    return destino


# ---------------------------------------------------------------------------- leva 1 (25/11): barreiras e portão
LINHA_FORA_DO_TEMA = ("(sistema) O lead pediu algo fora do tema do escritório: recuse com gentileza em 1 frase curta, "
                      "sem responder ao pedido, e volte à pergunta do roteiro.")


def _barreiras(entrada: Entrada, saida: Saida, intencoes: dict[str, bool]) -> Saida | None:
    """B6. Tentativa de manipular (ignorar regras, revelar o prompt, se passar por advogado): resposta fixa e segura,
    sem chamar o agente, e evento. Fora do tema: o agente responde curto e volta ao assunto (linha de sistema no
    conteúdo); na 3ª mensagem seguida fora do tema, a IA sai e a equipe assume com a ficha. Devolve a saída quando o
    turno acaba aqui."""
    antes = _inteiro(entrada.fatos.get(MARCA_FORA_DO_TEMA))
    if intencoes.get("tentativa_de_manipular"):
        saida.motivo = "barreira_manipulacao"
        texto = entrada.mensagens_fixas.get("manipulacao") or MENSAGENS_FIXAS["manipulacao"]
        pendente = _ultima_pergunta(entrada.historico)
        textos = [texto] + ([f"Voltando ao seu caso: {pendente}"] if pendente else ["Me conta: como posso te ajudar com ele?"])
        saida.mensagens = formatador.formatar([{"tipo": "texto", "texto": t} for t in textos])
        saida.eventos.append(_evento("barreira_manipulacao", "aviso", "lead",
                                     "O lead tentou mudar as regras da IA (ignorar instruções, ver o prompt ou se passar "
                                     "por outra pessoa); a IA deu a resposta fixa e não revelou nada.",
                                     trecho=" ".join(entrada.novas)[:200]))
        return saida
    if not intencoes.get("fora_do_tema"):
        if antes:
            _gravar_controle(saida, MARCA_FORA_DO_TEMA, 0)
        return None
    seguidas = antes + 1
    _gravar_controle(saida, MARCA_FORA_DO_TEMA, seguidas)
    saida.eventos.append(_evento("barreira_fora_do_tema", "info", "lead",
                                 f"O lead pediu algo fora do tema ({seguidas}ª seguida).", seguidas=seguidas,
                                 trecho=" ".join(entrada.novas)[:200]))
    if seguidas < FORA_DO_TEMA_PAUSA:
        saida.contexto["barreira"] = "fora_do_tema"
        return None
    saida.estado_lead, saida.motivo_estado = "pausado", "fora_do_tema_repetido"
    saida.motivo = saida.motivo_estado
    saida.mensagens = _fixa(entrada, "equipe_continua")
    saida.eventos.append(_evento("fora_do_tema_repetido", "aviso", "lead",
                                 f"O lead insistiu {seguidas} vezes seguidas em assunto fora do tema; a conversa foi "
                                 "para a equipe.", seguidas=seguidas))
    return saida


def _inteiro(valor: Any) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _ultima_pergunta(historico: list[dict[str, str]]) -> str | None:
    """Última pergunta que a IA fez ao lead (fim do bloco mais recente da IA terminando em "?")."""
    bloco = _ultima_resposta_da_ia(historico)
    for texto in reversed(bloco):
        texto = str(texto or "").strip()
        if texto.endswith("?"):
            return texto[-200:]
    return None


def _faltam_no_portao(produto: Any, destino: str, fatos: dict[str, Any], regras: aa.Regras, calculadora: bool,
                      etapa: str) -> list[str]:
    """B4. O que falta para o lead entrar no destino. Desqualificar exige um motivo comprovado por fato do lead (ou a
    conta do período de graça dizendo que não estava coberto)."""
    from app.cerebro import catalogo

    config = getattr(produto, "config", {}) or {}
    if not destino or not catalogo.portao_ligado(config):
        return []
    if destino == "desqualificado":
        if catalogo.motivo_de_desqualificar(config, fatos):
            return []
        if getattr(produto, "fatos_do_periodo", ()) and (cobertura := contexto.cobertura_na_data_do_acidente(fatos, regras)) \
                and cobertura[0] == "fora":
            return []
        return ["motivo_de_desqualificacao"]
    return catalogo.faltam_para_entrar(config, destino, fatos)


def _orientacao_do_portao(destino: str, faltam: list[str]) -> str:
    from app.cerebro import catalogo

    if faltam == ["motivo_de_desqualificacao"]:
        return ("Você marcou transferir_para = \"desqualificado\", mas o lead ainda não disse nada que desqualifique o "
                "caso (aposentadoria, advogado neste caso, sem sequela, nunca trabalhou). Deixe transferir_para vazio, "
                "não use a frase de passagem e siga o roteiro com a próxima pergunta.")
    perguntas = " ".join(catalogo.PERGUNTA_DO_PORTAO.get(f, catalogo.ROTULO_DO_PORTAO.get(f, f.replace("_", " ")))
                         for f in faltam)
    return (f"Ainda falta perguntar antes de passar o lead para \"{destino}\": {perguntas} Deixe transferir_para vazio "
            "nesta resposta, não use a frase de passagem e faça a pergunta.")


def _linha_do_portao(entrada: Entrada, produto: Any, papeis: dict[str, Any]) -> str | None:
    """Turno seguinte a uma troca segurada pelo portão: a IA lembra o que ainda falta perguntar (linha de sistema)."""
    from app.cerebro import catalogo

    barrado = entrada.fatos.get(MARCA_PORTAO)
    if not isinstance(barrado, dict) or not barrado.get("destino"):
        return None
    destino, faltam = str(barrado["destino"]), [str(f) for f in barrado.get("faltam") or []]
    faltam = [f for f in faltam if f == "motivo_de_desqualificacao" or f in
              catalogo.faltam_para_entrar(getattr(produto, "config", {}), destino, entrada.fatos)]
    if not faltam:
        return None
    rotulos = "; ".join(catalogo.ROTULO_DO_PORTAO.get(f, f.replace("_", " ")) for f in faltam)
    return (f"PARA PASSAR O LEAD (sistema): a passagem para {catalogo.NOMES.get(destino, destino)} foi segurada porque "
            f"falta saber {rotulos}. Pergunte isso antes de passar.")


def _portao_de_fatos(entrada: Entrada, produto: Any, saida: Saida, destino: str, mensagens: list[dict[str, Any]],
                     papeis: dict[str, Any], etapa: str, regras: aa.Regras,
                     calculadora: bool) -> tuple[str, list[dict[str, Any]]]:
    """B4. A troca para a frente é decidida aqui, pelos fatos. Sem os fatos do destino, a troca é segurada: a frase de
    passagem sai da resposta (o lead não pode ouvir "vou te passar" e não passar) e, se nada sobrar, vai a pergunta do
    que falta. Com o motivo de desqualificação comprovado, ele fica no contexto (fato, valor e trecho do lead)."""
    from app.cerebro import catalogo

    if not destino:
        return destino, mensagens
    fatos = saida.fatos_depois
    faltam = _faltam_no_portao(produto, destino, fatos, regras, calculadora, etapa)
    if not faltam:
        if destino == "desqualificado" and catalogo.portao_ligado(getattr(produto, "config", {})):
            motivo = catalogo.motivo_de_desqualificar(getattr(produto, "config", {}), fatos)
            chave = motivo[0] if motivo else "periodo_de_graca"
            trecho = next((f.get("trecho") for f in saida.fatos_novos if f.get("chave") == chave), None)
            saida.contexto["motivo_desqualificacao"] = {"fato": chave, "valor": motivo[1] if motivo else "fora",
                                                        "trecho": trecho}
        return destino, mensagens
    saida.faltam = list(faltam)
    saida.contexto["portao_barrou"] = {"destino": destino, "faltam": faltam}
    saida.eventos.append(_evento("troca_barrada_faltam_fatos", "info", "lawchat",
                                 f"A IA quis passar o lead de {etapa} para {destino}, mas faltam: {', '.join(faltam)}. "
                                 "A troca foi segurada.", destino=destino, etapa=etapa, faltam=faltam))
    frase = (papeis.get(destino) or {}).get("mensagem_troca") if isinstance(papeis.get(destino), dict) else None
    sem_frase = [m for m in mensagens if not (m["tipo"] == "texto" and frase
                                               and (catalogo.tem_frase_exata([m.get("texto", "")], frase)
                                                    or catalogo.tem_frase([m.get("texto", "")], frase)))]
    if not any(m["tipo"] == "texto" and "?" in str(m.get("texto") or "") for m in sem_frase):
        perguntas = [catalogo.PERGUNTA_DO_PORTAO[f] for f in faltam if f in catalogo.PERGUNTA_DO_PORTAO]
        if perguntas:
            sem_frase = [m for m in sem_frase if m["tipo"] == "texto"] + [{"tipo": "texto", "texto": perguntas[0]}]
    if not any(m["tipo"] == "texto" for m in sem_frase):
        sem_frase = [{"tipo": "texto", "texto": "Me conta mais um pouco sobre o seu caso?"}]
    return "", sem_frase


def _portao_prendeu(entrada: Entrada, saida: Saida, pedido: str, destino: str, etapa: str) -> bool:
    """Nunca prender o lead: a mesma troca segurada pela mesma falta dois turnos seguidos vai para a equipe com a ficha
    (analise_manual:faltam_fatos). "Segurada" vale também quando a IA obedeceu à CORRIJA do portão e fez a pergunta:
    se no turno seguinte a mesma falta continua (o extrator não achou a resposta), a IA não pergunta pela 3ª vez.
    Troca que passou, falta que mudou (o lead respondeu algo) ou turno sem pedido de troca limpam ou trocam a marca."""
    barrado = saida.contexto.get("portao_barrou") or (None if destino else saida.contexto.get("portao_pediu"))
    anterior = entrada.fatos.get(MARCA_PORTAO)
    if not barrado:
        if isinstance(anterior, dict) and anterior.get("destino"):
            _gravar_controle(saida, MARCA_PORTAO, {})
        return False
    if isinstance(anterior, dict) and anterior.get("destino") == barrado["destino"] \
            and list(anterior.get("faltam") or []) == list(barrado["faltam"]):
        _gravar_controle(saida, MARCA_PORTAO, {})
        saida.etapa_depois = etapa
        saida.estado_lead, saida.motivo_estado = "pausado", "analise_manual:faltam_fatos"
        saida.motivo = saida.motivo_estado
        saida.mensagens = _fixa(entrada, "equipe_continua")
        saida.eventos.append(_evento("analise_manual", "aviso", "lawchat",
                                     f"A passagem para {barrado['destino']} foi segurada dois turnos seguidos (faltam: "
                                     f"{', '.join(barrado['faltam'])}); a conversa foi para a equipe.",
                                     destino=barrado["destino"], faltam=barrado["faltam"]))
        return True
    _gravar_controle(saida, MARCA_PORTAO, dict(barrado))
    return False


# ---------------------------------------------------------------------------- catálogo: conferências e travas do motor
# Fatos de controle do motor (fonte "sistema"; começam com "_" e não aparecem para a IA): memória entre turnos das travas
# que só podem agir uma vez, para nenhuma delas prender o lead num laço.
MARCA_PERGUNTOU = "_perguntou_antes_de_transferir"     # ["sdr>closer", ...]: a trava já pediu a pergunta uma vez
MARCA_ADIADA = "_transferencia_adiada"                  # destino segurado no turno anterior (pergunta em aberto)
MARCA_CEP_CONSULTADO = "_cep_consultado"                # último CEP buscado: o mesmo CEP não é buscado de novo a cada turno
MARCA_ENDERECO_DO_CEP = "_endereco_pelo_cep"            # {campo: valor} do endereço que a busca do CEP preencheu
MARCA_BOAS_VINDAS = "_boas_vindas_pendente"             # papel que recebeu o lead e ainda não deu as boas-vindas
MARCA_DESTINOS_IGNORADOS = "_destinos_ignorados"        # ["assinatura>contratos", ...]: já registrados nesta conversa
MARCA_VOLTOU_AO_SDR = "_voltou_ao_sdr"                  # o Desqualificado já devolveu o lead ao SDR uma vez
MARCA_VARIAVEIS_SEM_VALOR = "_variaveis_sem_valor"      # ["LINK AVALIACAO GOOGLE", ...]: evento já registrado
MARCA_FORA_DO_TEMA = "_fora_do_tema_seguidas"           # quantas mensagens seguidas fora do tema (B6)
MARCA_PRESENCIAL = "_pediu_presencial"                # já pediu atendimento presencial uma vez (na 2ª, pausa)
MARCA_PEDIU_PESSOA = "_pediu_pessoa"                   # o lead já pediu uma pessoa uma vez (no 2º pedido, pausa)
ORIENTACAO_PRIMEIRO_PEDIDO = ("O lead pediu para falar com uma pessoa. Diga em 1 frase, com simpatia, que você mesma "
                              "consegue ajudar por aqui e responda a dúvida dele (ou pergunte qual é); não prometa "
                              "chamar ninguém e siga a etapa.")
MARCA_SO_TEXTO = "_so_texto"                           # lead com deficiência auditiva: nada de áudio na conversa
MARCA_DADOS_CONFIRMADOS = "_dados_confirmados"          # hash dos dados do contrato que o lead confirmou (resumo + "sim")
MARCA_DESQ_ESQUECIDA = "_desqualificacao_esquecida"     # a correção "o lead se desqualificou" já foi mandada uma vez
MARCA_PORTAO = "_portao_barrou"                         # {"destino", "faltam"}: troca segurada no turno anterior (B4)
# Nome curto de cada campo do contrato na linha "DADOS DO CONTRATO QUE FALTAM (sistema)".
ROTULO_DO_CAMPO = {"nome": "nome completo", "cpf": "CPF", "endereco": "rua", "numero": "número", "bairro": "bairro",
                   "cidade": "cidade", "estado": "estado", "cep": "CEP", "email": "e-mail", "estado_civil": "estado civil",
                   "profissao": "profissão", "rg": "RG", "telefone": "telefone", "cpfdomenor": "CPF do(a) menor",
                   "nomecompletomenor": "nome do(a) menor", "nacionalidade": "nacionalidade",
                   "naturalidade": "naturalidade", "filiacao": "filiação",
                   "nacionalidadedomenor": "nacionalidade do(a) menor", "naturalidadedomenor": "naturalidade do(a) menor",
                   "filiacaodomenor": "filiação do(a) menor"}
# O endereço que veio do CEP neste turno é marcado na linha dos dados; o resto do endereço deste turno veio do lead.
CAMPOS_DO_ENDERECO = ("endereco", "bairro", "cidade", "uf")
# As travas de repetição (cpf_ja_conferido, resposta_repetida) pausam o lead quando a IA insiste? Desligado: elas só
# mandam refazer a resposta e registram o evento. Ligar só depois de medir falsos positivos em conversas reais.
PAUSAR_EM_REPETICAO = False


@dataclass
class _Guarda:
    codigo: str
    orientacao: str
    dura: bool = False          # True: se a 2ª tentativa repetir, a resposta não sai e a equipe assume
    marca: str | None = None    # memória para agir uma vez só na conversa


@dataclass
class _Tentativa:
    resposta: dict[str, Any]
    mensagens: list[dict[str, Any]]
    destino: str
    erros: list[str]
    guardas: list[_Guarda]
    contexto: dict[str, Any]
    pela_frase: bool = False        # o destino veio da frase de passagem (transferir_para vazio)


def _regras_do_periodo(entrada: Entrada, produto: Any) -> aa.Regras:
    """Prazos do escritório para a conta do período de graça: config.regras_periodo do agente, ou as da Entrada."""
    proprias = (getattr(produto, "config", {}) or {}).get("regras_periodo")
    if isinstance(proprias, dict):
        try:
            return aa.Regras(**{k: v for k, v in proprias.items() if k in aa.Regras.__dataclass_fields__})
        except TypeError:
            pass
    return entrada.regras


def _so_digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


async def _enriquecer(entrada: Entrada, saida: Saida) -> None:
    """Busca de apoio (endereço pelo CEP). Roda quando o CEP é novo neste turno ou ainda não foi buscado: o mesmo CEP não
    encontrado era consultado na rede a cada turno, com a linha "BUSCA DE CEP ... peça ao lead o que faltar" repetida.
    CEP trocado: o endereço que veio do CEP anterior não fica junto do CEP novo (a busca refaz; o que não vier fica vazio)."""
    cep_agora = _so_digitos(saida.fatos_depois.get("cep"))
    cep_antes = _so_digitos(entrada.fatos.get("cep"))
    cep_no_turno = any(f.get("chave") == "cep" for f in saida.fatos_novos)
    consultado = _so_digitos(entrada.fatos.get(MARCA_CEP_CONSULTADO))
    if cep_agora and not cep_no_turno and consultado == cep_agora:
        return                                          # este CEP já foi buscado num turno anterior
    # Só o que a busca do CEP anterior preencheu (e continua com o mesmo valor) é "do CEP": o endereço que o próprio lead
    # digitou fica, mesmo com o CEP corrigido. Lead antigo, sem a marca: nada é apagado (no pior caso o endereço velho
    # aparece na conferência dos dados).
    marca = entrada.fatos.get(MARCA_ENDERECO_DO_CEP)
    do_cep = {k: v for k, v in marca.items() if k in CAMPOS_DO_ENDERECO} if isinstance(marca, dict) else {}
    do_lead = {f.get("chave") for f in saida.fatos_novos if f.get("fonte") != "sistema"}
    herdados: list[str] = []
    if cep_antes and cep_agora and cep_antes != cep_agora:
        herdados = [k for k in CAMPOS_DO_ENDERECO if k not in do_lead and saida.fatos_depois.get(k)
                    and do_cep.get(k) == saida.fatos_depois.get(k)]
    fatos = {k: v for k, v in saida.fatos_depois.items() if k not in herdados}
    trocados: set[str] = set()
    try:
        for fato in await entrada.enriquecer(fatos):
            if str(fato.get("chave", "")).startswith("_busca"):
                saida.contexto["busca_cep"] = fato.get("valor")   # situação da busca: vai para o turno, não vira fato
                continue
            saida.fatos_novos.append(fato)
            saida.fatos_depois[fato["chave"]] = fato["valor"]
            trocados.add(fato["chave"])
    except Exception as erro:                          # ferramenta de apoio nunca derruba o turno
        saida.eventos.append(_evento("ferramenta_falhou", "aviso", "provedor", f"Busca de apoio falhou: {erro}"))
        return
    for chave in herdados:
        if chave not in trocados:                       # do CEP anterior e sem valor do CEP novo: a IA pede de novo
            saida.fatos_novos.append({"chave": chave, "valor": "", "trecho": "(CEP trocado)", "fonte": "sistema"})
            saida.fatos_depois[chave] = ""
    # Marca do endereço que veio do CEP: o que a busca preencheu agora, mais o que já era do CEP e não mudou.
    nova_marca = {k: v for k, v in do_cep.items() if k not in herdados and k not in do_lead and saida.fatos_depois.get(k) == v}
    nova_marca.update({k: saida.fatos_depois[k] for k in trocados if k in CAMPOS_DO_ENDERECO and saida.fatos_depois.get(k)})
    if nova_marca != do_cep and (nova_marca or isinstance(marca, dict)):
        _gravar_controle(saida, MARCA_ENDERECO_DO_CEP, nova_marca)
    busca = saida.contexto.get("busca_cep")
    falhou = isinstance(busca, dict) and bool(busca.get("falhou"))
    # Serviço de CEP fora do ar: não marca como buscado, para o turno seguinte tentar de novo (não é "CEP não encontrado").
    if cep_agora and consultado != cep_agora and not falhou:
        _gravar_controle(saida, MARCA_CEP_CONSULTADO, saida.fatos_depois.get("cep"))


_CEP_NO_TEXTO = re.compile(r"(?<!\d)(\d{2})\.?(\d{3})-?(\d{3})(?!\d)")       # o mesmo formato de ferramentas.cep.achar_cep
# Rótulo de outro dado antes do número ("meu rg é 12345678", "data de nascimento 15031980"): não é o CEP.
_ROTULO_DE_OUTRO_DADO = re.compile(r"\b(?:rg|identidade|cpf|nis|pis|cnh|nasc\w*|data|telefone|tel|celular|cel|whats\w*|zap|"
                                   r"numero|n|casa|apto|apartamento)\b")


def _cep_pelo_texto(entrada: Entrada, saida: Saida) -> None:
    """CEP sem rótulo que o extrator não gravou ("39999-412" respondendo ao pedido do CEP): o código acha e grava.
    Sem o fato cep a busca do endereço nunca rodava (o campo "ferramenta: buscar_cep" da IA não faz nada sozinho).
    Não pega o número de outro dado (RG, data de nascimento: rótulo antes do número, letra colada, os mesmos dígitos em
    outro fato). Com um CEP já gravado, só troca quando a IA pediu o CEP e o número é outro."""
    from app.cerebro.extrator import normalizar

    ultima_da_ia = " ".join(_ultima_resposta_da_ia(entrada.historico))
    pediu = bool(re.search(r"\bcep\b", normalizar(ultima_da_ia)))
    ja_tem = _so_digitos(saida.fatos_depois.get("cep"))
    if ja_tem and not pediu:
        return
    outros = [_so_digitos(v) for k, v in saida.fatos_depois.items()
              if k not in ("cep", "telefone_contrato", "numero_casa") and not str(k).startswith("_") and isinstance(v, (str, int))]
    for texto in entrada.novas:
        if not (pediu or re.search(r"\bcep\b", normalizar(texto))):
            continue
        for achado in _CEP_NO_TEXTO.finditer(texto):
            cep = "".join(achado.groups())
            antes = texto[:achado.start()]
            if antes[-1:].isalpha():
                continue                                # "MG12345678": parte de um documento
            prefixo = normalizar(antes)
            rotulo = max((m.end() for m in _ROTULO_DE_OUTRO_DADO.finditer(prefixo)), default=-1)
            if rotulo > max((m.end() for m in re.finditer(r"\bcep\b", prefixo)), default=-1):
                continue                                # o número é de outro dado rotulado ("meu rg é ...")
            if any(d and cep in d for d in outros):
                continue                                # os mesmos dígitos já são outro fato (RG, data de nascimento)
            if cep == ja_tem:
                return                                  # o mesmo CEP: não é dado novo
            break
        else:
            continue
        if cep:
            valor = f"{cep[:5]}-{cep[5:]}"
            # O mesmo número gravado como telefone ou número da casa era o CEP: sai de lá.
            for fato in [f for f in saida.fatos_novos if f.get("chave") in ("telefone_contrato", "numero_casa")
                         and re.sub(r"\D", "", str(f.get("valor"))) == cep]:
                saida.fatos_novos.remove(fato)
                saida.fatos_depois.pop(fato["chave"], None)
                if fato["chave"] in entrada.fatos:
                    saida.fatos_depois[fato["chave"]] = entrada.fatos[fato["chave"]]
            saida.fatos_novos.append({"chave": "cep", "valor": valor, "trecho": texto, "fonte": "sistema"})
            saida.fatos_depois["cep"] = valor
            return


def _conferir_cpfs(entrada: Entrada, saida: Saida) -> list[str]:
    """Confere os CPFs assim que o lead os informa (a antiga tool BUSCARCPF do n8n devolvia "valido true/false"):
    válido = regravado formatado e dito ao modelo que não peça de novo; inválido = pode pedir de novo uma vez.
    Sem isso o modelo lia "057.830.862.23" (ponto no lugar do traço), inventava um aviso do sistema e repetia o pedido."""
    from app.contrato import dados as cdados

    linhas = []
    for chave, rotulo in (("cpf", "CPF"), ("cpf_menor", "CPF do(a) menor")):
        valor = saida.fatos_depois.get(chave)
        if not valor:
            continue
        formatado = cdados.formatar_cpf(valor)
        chegou_agora = any(f.get("chave") == chave and f.get("fonte") != "sistema" for f in saida.fatos_novos)
        if not formatado:
            if chegou_agora:
                linhas.append(f"CONFERÊNCIA DO {rotulo} (sistema): {valor} é INVÁLIDO (os dígitos verificadores não "
                              f"conferem). Peça o {rotulo} de novo uma única vez, explicando que os números não conferem.")
            else:
                # Inválido gravado num turno anterior: o pedido de correção já foi feito. Repetir "peça de novo" a cada
                # turno levava o modelo a pedir o CPF em toda mensagem.
                linhas.append(f"CONFERÊNCIA DO {rotulo} (sistema): o {rotulo} informado ({valor}) não confere e segue "
                              "pendente; o pedido de correção já foi feito. Não insista a cada mensagem: siga com os "
                              f"outros dados e só volte ao {rotulo} quando o lead o reenviar ou antes de gerar o contrato.")
            continue
        if chave == "cpf_menor" and _so_digitos(formatado) == _so_digitos(saida.fatos_depois.get("cpf")):
            # A mãe mandou de novo o próprio CPF como o da criança: não é o CPF do(a) menor e não vai como VÁLIDO.
            saida.fatos_novos[:] = [f for f in saida.fatos_novos if f.get("chave") != "cpf_menor"]
            anterior = entrada.fatos.get("cpf_menor")
            if anterior and _so_digitos(anterior) != _so_digitos(formatado):
                saida.fatos_depois["cpf_menor"] = anterior
            else:
                saida.fatos_depois.pop("cpf_menor", None)
                if anterior:                            # já estava gravado igual ao do titular: limpa
                    saida.fatos_novos.append({"chave": "cpf_menor", "valor": "", "trecho": "(igual ao CPF do titular)",
                                              "fonte": "sistema"})
            linhas.append(f"CONFERÊNCIA DO {rotulo} (sistema): {formatado} é IGUAL ao CPF do titular; peça o CPF da "
                          "criança (o do documento dela), uma única vez.")
            continue
        saida.fatos_depois[chave] = formatado
        for fato in [f for f in saida.fatos_novos if f.get("chave") == chave]:
            if entrada.fatos.get(chave) == formatado:
                saida.fatos_novos.remove(fato)          # o mesmo CPF em outro formato não é dado novo
            else:
                fato["valor"] = formatado
        linhas.append(f"CONFERÊNCIA DO {rotulo} (sistema): {formatado} é VÁLIDO (os dígitos conferem). "
                      "Não peça de novo nem diga que está errado; siga para o próximo dado.")
    return linhas


def _linha_da_busca_de_cep(saida: Saida) -> str | None:
    """Resultado da busca do CEP deste turno, para o modelo não supor uma busca que não houve (nem a fazer de cabeça)."""
    busca = saida.contexto.get("busca_cep")
    if not isinstance(busca, dict):
        return None
    cep = busca.get("cep") or saida.fatos_depois.get("cep") or ""
    if busca.get("falhou"):
        # Nenhuma fonte respondeu (rede fora, timeout): o CEP pode existir. A busca é refeita no turno seguinte.
        return (f"BUSCA DE CEP (sistema): a busca do CEP {cep} não pôde ser feita agora (serviço fora do ar). Não diga "
                "que o CEP não existe nem que buscou; siga com os outros dados ou peça ao lead rua, bairro e cidade se "
                "precisar.")
    if busca.get("tipo") == "geral" and busca.get("cidade"):
        # CEP geral da cidade (existe, mas não tem rua): a cidade e a UF valem; falta a rua.
        cidade = "/".join(str(busca.get(k)) for k in ("cidade", "uf") if busca.get(k))
        return (f"BUSCA DE CEP (sistema): CEP {cep} é o CEP geral de {cidade} (sem rua). Não diga que não foi "
                "encontrado; peça a rua, o número e o bairro (ou o CEP da rua).")
    if busca.get("encontrado"):
        f = saida.fatos_depois
        endereco = ", ".join(str(f.get(k)) for k in ("endereco", "bairro") if f.get(k))
        cidade = "/".join(str(f.get(k)) for k in ("cidade", "uf") if f.get(k))
        return (f"BUSCA DE CEP (sistema): CEP {cep} encontrado: {', '.join(p for p in (endereco, cidade) if p)}. "
                "Use só estes dados do endereço.")
    return (f"BUSCA DE CEP (sistema): CEP {cep} não encontrado. Nenhum endereço foi achado pelo sistema: não diga que "
            "buscou nem cite rua, bairro ou cidade que o lead não escreveu; peça ao lead o que faltar.")


def _dados_informados(saida: Saida) -> str:
    """Linha dos dados já informados: sem os fatos de controle do motor e com a fonte do endereço deste turno."""
    pelo_cep = {f.get("chave") for f in saida.fatos_novos if f.get("fonte") == "sistema" and f.get("chave") in CAMPOS_DO_ENDERECO}
    do_lead = {f.get("chave") for f in saida.fatos_novos if f.get("fonte") != "sistema" and f.get("chave") in CAMPOS_DO_ENDERECO}
    partes = []
    for chave, valor in saida.fatos_depois.items():
        if str(chave).startswith("_") or valor in (None, "", []):
            continue
        fonte = " (pelo CEP)" if chave in pelo_cep else " (dito pelo lead)" if chave in do_lead else ""
        partes.append(f"{chave}={valor}{fonte}")
    return "; ".join(partes)


def _gravar_marca(saida: Saida, chave: str, antigas: list[str], novas: list[str]) -> None:
    if novas and not set(novas) <= set(antigas):
        valor = list(dict.fromkeys(antigas + novas))
        saida.fatos_novos.append({"chave": chave, "valor": valor, "trecho": "(trava do motor)", "fonte": "sistema"})
        saida.fatos_depois[chave] = valor


def _ultima_resposta_da_ia(historico: list[dict[str, str]]) -> list[str]:
    """Balões da última resposta da IA (a sequência de "você" mais recente)."""
    bloco: list[str] = []
    for mensagem in reversed(historico):
        if mensagem.get("autor") == "você":
            bloco.insert(0, str(mensagem.get("texto") or ""))
        elif bloco:
            break
    return bloco


_REPETICAO_DO_LEAD = re.compile(r"\b(?:como (?:eu )?(?:te )?(?:falei|disse|mandei|passei)|ja (?:te )?(?:falei|disse|mandei|"
                                r"passei|enviei|informei|respondi))\b")
# Fala só de conversa (cumprimento, cortesia, "ok"): repetida, não é um dado repetido.
_SO_CONVERSA = re.compile(r"\b(?:oi+|ola|alo|bom dia|boa tarde|boa noite|tudo bem|tudo bom|td bem|ok|okay|certo|sim|nao|"
                          r"entendi|blz|beleza|obrigad\w*|brigad\w*|valeu|e|ai|que|o|a|eu|ta|tá|bem|isso)\b")
_PEDE_ESCLARECIMENTO = re.compile(r"\b(?:nao entendi|nao entendo|nao compreendi|como assim|pode repetir|repete|"
                                  r"explica\w*|o que (?:e|significa|quer dizer))\b")
# A resposta pede alguma coisa (pergunta ou pedido no imperativo). Sem pedido (fecho do desqualificado, "por nada!"),
# repetir não é o laço de pedir de novo um dado já respondido.
_PEDIDO_NA_RESPOSTA = re.compile(r"\b(?:envie|mande|informe|digite|passe|reenvie|repita|confirme|preciso d[oae]s?|"
                                 r"preciso que|me diga|me conte|me fala)\b")
# O lead pede o reenvio ("manda de novo", "não chegou", "envia outra vez"): reenviar o mesmo texto é o que ele pediu, não
# é laço (o mesmo tratamento de "pode repetir"). Sobre o texto normalizado.
_PEDE_REENVIO = re.compile(r"\b(?:(?:manda|mande|envia|envie|reenvia|reenvie|repassa|passa)\w*\s+(?:\w+\s+){0,3}?"
                           r"(?:de novo|novamente|outra vez|denovo)|nao (?:chegou|apareceu|carregou|abriu|veio|recebi)"
                           r"|reenvia\w*)\b")
# Marca de mídia que o sistema escreve no lugar da mídia ("[O lead enviou uma imagem que não foi possível ver...]",
# "[O lead enviou uma figurinha...]"): é igual a cada envio e não é conteúdo do lead. Sai até o primeiro ":" ou "]",
# e o que vier depois (a descrição da imagem, a transcrição, a legenda, o texto do documento) continua contando.
_MARCA_DE_MIDIA = re.compile(r"\[O lead enviou[^\]:]*[:\]]")
# Rótulos de um campo, para saber se a resposta pede esse campo: as partes da chave e os apelidos (texto normalizado).
_APELIDOS_DO_CAMPO = {"email": ("email", "e mail"), "numero_casa": ("numero",), "endereco": ("endereco", "rua"),
                      "data_nascimento": ("nascimento",)}


def _sem_marca_de_midia(texto: str | None) -> str:
    return _MARCA_DE_MIDIA.sub(" ", texto or "")


def _rotulos_do_campo(chave: str) -> tuple[str, ...]:
    partes = [p for p in str(chave).split("_") if p and p not in ("contrato", "menor")]
    return tuple(dict.fromkeys(partes + list(_APELIDOS_DO_CAMPO.get(str(chave), ()))))


def _lead_repetiu(entrada: Entrada, resposta: str = "") -> str | None:
    """O que o lead repetiu neste turno (a mesma mensagem, ou um dado já registrado que a resposta não acolheu).
    None = trouxe coisa nova. Um dado repetido que a resposta cita (o resumo corrigido, por exemplo) não é laço: no laço
    a IA pede de novo o dado sem nem citá-lo ("o CPF informado está incorreto, me envie o correto")."""
    from app.cerebro.extrator import normalizar

    # A marca de mídia do sistema não é fala do lead: a mídia sem conteúdo (foto ilegível, figurinha) vira texto vazio.
    textos_novos = [_sem_marca_de_midia(t) for t in entrada.novas]
    novas = normalizar(" ".join(textos_novos))
    if not novas or _PEDE_ESCLARECIMENTO.search(novas) or _PEDE_REENVIO.search(novas):
        return None                     # "não entendi" / "manda de novo" de novo: explicar ou reenviar é o certo
    # Só a mesma mensagem COM conteúdo: "bom dia" ou "ok" de novo não responde nada (a IA retoma a pergunta pendente).
    tem_conteudo = bool(re.search(r"\d", novas)) or len(_SO_CONVERSA.sub(" ", novas).split()) >= 2
    anteriores = [normalizar(_sem_marca_de_midia(m.get("texto"))) for m in entrada.historico if m.get("autor") == "lead"][-6:]
    if tem_conteudo and any(len(a) >= 4 and difflib.SequenceMatcher(None, novas, a).ratio() > 0.9 for a in anteriores):
        return "a mesma mensagem"
    digitos = re.sub(r"\D", "", " ".join(textos_novos))
    digitos_resposta, resposta_normal = re.sub(r"\D", "", resposta), f" {normalizar(resposta)} "
    outro_campo = False
    for chave, valor in entrada.fatos.items():
        if str(chave).startswith("_") or not isinstance(valor, (str, int)):
            continue
        so_digitos = re.sub(r"\D", "", str(valor))
        normal = normalizar(str(valor))
        if not ((len(so_digitos) >= 5 and so_digitos in digitos and so_digitos not in digitos_resposta)
                or (len(normal) >= 6 and not normal.isdigit() and f" {normal} " in f" {novas} "
                    and f" {normal} " not in resposta_normal)):
            continue
        # Só é laço se a resposta pede esse mesmo campo. O lead mandou de novo o CPF e a IA retoma o RG, que segue
        # pendente: é a pergunta pendente retomada (o que o próprio prompt manda), não o pedido de um dado já recebido.
        if any(f" {r} " in resposta_normal for r in _rotulos_do_campo(chave)):
            return chave
        outro_campo = True
    if outro_campo:
        return None
    return "disse que já informou" if _REPETICAO_DO_LEAD.search(novas) else None


def _resposta_repetida(entrada: Entrada, saida: Saida, textos: list[str]) -> _Guarda | None:
    """Anti-laço: a resposta é quase igual à última da IA (> 0,9) E o lead repetiu o que já tinha dito, sem dado novo.
    Só as duas juntas: repetir uma frase do roteiro (ou o resumo corrigido) para um lead que trouxe coisa nova é legítimo."""
    from app.cerebro.extrator import normalizar

    # Um fato do lead que só repete o valor já gravado em outro formato ("(31) 99999-1234" para "31999991234") não é
    # dado novo: contá-lo como novo desligava a trava justo no laço que ela existe para cortar.
    if any(f.get("fonte", "extrator") != "sistema"
           and not _mesmo_valor(str(f.get("chave")), f.get("valor"), entrada.fatos.get(str(f.get("chave"))))
           for f in saida.fatos_novos):
        return None                                     # o lead trouxe um dado novo (ou corrigiu um): não é laço
    anterior = normalizar(" ".join(_ultima_resposta_da_ia(entrada.historico)))
    atual = normalizar(" ".join(textos))
    if len(atual) < 15 or not anterior or difflib.SequenceMatcher(None, atual, anterior).ratio() <= 0.9:
        return None
    if "?" not in " ".join(textos) and not _PEDIDO_NA_RESPOSTA.search(atual):
        return None                                     # não pede nada: não é o laço de pedir de novo
    if not (repetido := _lead_repetiu(entrada, " ".join(textos))):
        return None
    if repetido == "a mesma mensagem":
        # Não afirma que um dado foi recebido: o lead pode ter repetido uma pergunta ou uma resposta que não fecha o pedido.
        orientacao = ("Sua resposta repete a sua última mensagem, e o lead repetiu a mensagem dele. Não mande o mesmo texto "
                      "de novo: responda ao que ele escreveu agora; se ele já respondeu ao seu pedido (veja DADOS JÁ "
                      "INFORMADOS), siga para o próximo passo do roteiro.")
    elif repetido == "disse que já informou":
        # O código não sabe qual dado ele diz ter mandado: não afirma que o dado pedido já foi recebido.
        orientacao = ("Sua resposta repete a sua última mensagem, e o lead disse que já informou. Confira nos DADOS JÁ "
                      "INFORMADOS e na CONVERSA ATÉ AQUI: se o que você pede já está lá, não peça de novo e siga para o "
                      "próximo passo do roteiro; se não está, peça com outras palavras, dizendo o que ainda falta.")
    else:
        orientacao = (f"Sua resposta repete a sua última mensagem, e o lead repetiu o que já tinha dito ({repetido}). Esse "
                      "dado já foi recebido (veja DADOS JÁ INFORMADOS e as linhas do sistema): não peça de novo; responda "
                      "ao lead e siga para o próximo passo do roteiro.")
    # Leve de propósito: a revisão achou muitos falsos positivos (cortesia, retomada de pergunta, reenvio do resumo,
    # mídia repetida) e pausar um lead à toa custa caro ao escritório. Fica a CORRIJA + o evento, sem pausar.
    return _Guarda("resposta_repetida", orientacao, dura=PAUSAR_EM_REPETICAO)


def _mesmo_valor(chave: str, novo: Any, antigo: Any) -> bool:
    """O valor novo é o mesmo já gravado, só em outro formato (dígitos para documento/telefone/CEP; caixa e acento no resto)."""
    from app.cerebro.extrator import normalizar

    if antigo in (None, "", []) or novo in (None, "", []):
        return False
    if chave in ("telefone_contrato", "cep", "cpf", "cpf_menor", "rg", "numero_casa"):
        return re.sub(r"\D", "", str(novo)) == re.sub(r"\D", "", str(antigo)) != ""
    return normalizar(str(novo)) == normalizar(str(antigo))


# Pedido do CPF com o CPF como OBJETO do verbo, e o verbo na forma de pedido ("me envie o CPF", "qual é o seu CPF",
# "preciso do seu CPF"). Particípios e passados ("o CPF informado", "o CPF que você enviou", "CPF confirmado") e um
# verbo de outro dado na mesma frase ("CPF anotado, agora me passe o RG", "confirmar se o nome e o CPF estão corretos")
# não são pedido: barrá-los pausava o lead que só via o recebimento acusado. Entre o verbo e "cpf" só cabem palavras curtas.
_ENTRE_VERBO_E_CPF = r"(?:(?:me|nos|o|a|seu|sua|teu|tua|de|novo|novamente|numero|do|da|por|favor|aqui|so|mais|uma|vez)\s+){0,5}"
_PEDE_CPF = re.compile(
    r"\b(?:envi(?:e|em|a|ar)|reenvi(?:e|em|a|ar)|mand(?:e|em|a|ar)|inform(?:e|em|a|ar)|digit(?:e|em|a|ar)"
    r"|pass(?:e|em|a|ar)|repit(?:a|am)|repet(?:e|ir)|escrev(?:a|am|er)|confirm(?:e|em|a|ar))\s+" + _ENTRE_VERBO_E_CPF + r"cpf\b"
    r"|\bqual\s+(?:e\s+|seria\s+)?(?:o\s+)?(?:seu\s+)?(?:numero\s+do\s+(?:seu\s+)?)?cpf\b"
    # "Precisamos do seu CPF só para preencher o contrato" explica o motivo (o lead perguntou "pra que?"): não é pedido.
    r"|\bprecis\w*\s+(?:de\s+novo\s+)?(?:do|de|o)\s+(?:seu\s+)?(?:numero\s+do\s+(?:seu\s+)?)?cpf\b"
    r"(?!\s+(?:so\s+|apenas\s+|somente\s+)?(?:para|pra|porque|pois|por\s+causa)\b)")
# A própria IA contando o que vai fazer com o CPF ("vou enviar o seu CPF para a equipe", "vou confirmar o seu CPF no
# sistema"): o sujeito é ela, não é pedido ao lead.
_ACAO_DA_IA = re.compile(r"\b(?:vou|vamos|irei|iremos|estou|estamos)\s+(?:(?!me\b|nos\b)\w+\s+)?$")
_DADO_ERRADO = re.compile(r"\b(?:incorret\w*|invalid\w*|errad\w*|erro|nao (?:passou|passa|confere|conferem|bate|batem|e valido|"
                          r"esta valido|parece valido)|digitos? verificador\w*|ultimo grupo|faltando digitos?|faltam digitos)\b")
# Erro negado ("não tem nenhum erro", "sem erro") sai da frase antes de procurar o erro; o erro assumido pela IA
# ("anotei o CPF errado no resumo") não é dizer que o CPF do lead está errado.
_NEGA_ERRO = re.compile(r"\b(?:nao|sem|nenhum)\s+(?:\w+\s+){0,2}?(?:erro|errad\w*|incorret\w*|invalid\w*)\b")
_ERRO_DA_IA = re.compile(r"\b(?:anotei|digitei|coloquei|escrevi|registrei|me enganei|erro meu|corrigi|corrigido|corrigida)\b")
_CONDICIONAL = re.compile(r"\b(?:se|caso)\s+(?:\w+\s+){0,4}?(?:estiver|esteja|tiver|houver|for)\b")
# De quem é o CPF de que a frase fala: o que vem logo depois de "cpf" ("o CPF da criança", "o CPF do Pedro", "o CPF dele")
# ou "seu CPF" / "do titular" / "do responsável" / "de quem vai assinar".
_CPF_DE_TITULAR = re.compile(r"cpf\s+(?:d[oa]\s+)?(?:seu|sua|voce|titular|responsavel|de\s+quem\s+(?:vai\s+)?assina\w*)\b")
_CPF_DE_OUTRO = re.compile(r"cpf\s+(?:dele|dela|deles|delas|d[oa]s?\s+(?:a\s+)?(?:seu\s+|sua\s+)?(?!seu\b|sua\b|voce\b|titular\b|"
                           r"responsavel\b|contrato\b|lead\b|cliente\b|que\b|quem\b)[a-z]{2,})")
# Fim de frase: ponto só quando não está entre dígitos (o CPF "057.830.862-23" fica inteiro).
_FIM_DE_FRASE = re.compile(r"(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+")


def _de_quem_e_o_cpf(normal: str) -> str | None:
    """De quem é o primeiro CPF citado no trecho normalizado: 'cpf_menor' (de outra pessoa: "o CPF da criança",
    "o CPF do Pedro", "o CPF dele"), 'cpf' ("o seu CPF", "o CPF do titular / do responsável") ou None (não diz)."""
    achado = re.search(r"\bcpf\b", normal)
    if not achado:
        return None
    if re.search(r"\b(?:seu|teu)\s+$", normal[:achado.start()]):
        return "cpf"
    depois = normal[achado.start():]
    if _CPF_DE_OUTRO.match(depois):
        return "cpf_menor"
    if _CPF_DE_TITULAR.match(depois):
        return "cpf"
    return None


def _cpf_valido_pedido_de_novo(entrada: Entrada, fatos: dict[str, Any], textos: list[str]) -> _Guarda | None:
    """A resposta diz que um CPF válido está errado, ou pede de novo o CPF que o lead acabou de mandar.
    Cada frase é lida pelo CPF de que ela fala: pedir o CPF da criança logo depois do CPF do titular (ou o inverso) é o
    próximo dado do roteiro, não um pedido repetido. Citar o CPF na resposta (o resumo, "só confirmando: é 057...") também
    não é pedir de novo."""
    from app.cerebro.extrator import normalizar
    from app.contrato import dados as cdados

    cpfs = {k: str(fatos[k]) for k in ("cpf", "cpf_menor") if fatos.get(k)}
    if "cpf" in cpfs and "cpf_menor" in cpfs and _so_digitos(cpfs["cpf"]) == _so_digitos(cpfs["cpf_menor"]):
        del cpfs["cpf_menor"]                           # o "CPF do(a) menor" é o do titular: pedir o da criança é o certo
    if not cpfs or not all(cdados.cpf_valido(c) for c in cpfs.values()):
        return None                                     # com um CPF inválido, pedir de novo é o certo
    digitos = {k: re.sub(r"\D", "", c) for k, c in cpfs.items()}
    digitos_novas = re.sub(r"\D", "", " ".join(entrada.novas))
    digitos_resposta = re.sub(r"\D", "", " ".join(textos))
    padrao = "cpf" if "cpf" in cpfs else "cpf_menor"   # a frase não diz de quem é: o CPF que existe (o do titular antes)

    def guarda(alvo: str) -> _Guarda:
        return _Guarda("cpf_ja_conferido",
                       f"O sistema já conferiu o CPF ({cdados.formatar_cpf(cpfs[alvo])}): é VÁLIDO. Não diga que está "
                       "errado e não peça de novo; siga para o próximo dado do roteiro.", dura=PAUSAR_EM_REPETICAO)

    for frase in _FIM_DE_FRASE.split("\n".join(textos)):
        normal = normalizar(frase)
        if not re.search(r"\bcpf\b", normal) or _CONDICIONAL.search(normal):
            continue
        sem_negacao = _NEGA_ERRO.sub(" ", normal)
        if _DADO_ERRADO.search(sem_negacao) and not _ERRO_DA_IA.search(normal):
            alvo = _de_quem_e_o_cpf(normal) or padrao
            if alvo in cpfs:                            # o CPF de que a frase fala está conferido e é válido
                return guarda(alvo)
        for pedido in _PEDE_CPF.finditer(normal):
            if _ACAO_DA_IA.search(normal[:pedido.start()]):
                continue                                # "vou enviar o seu CPF ...": ação da IA, não pedido
            # De quem é o CPF pedido: o próprio trecho do pedido e o que vem logo depois ("envie o CPF da criança").
            alvo = _de_quem_e_o_cpf(normal[pedido.start():pedido.end() + 60]) or padrao
            if alvo not in cpfs:
                continue                                # pede o CPF que ainda falta: é o próximo dado
            if digitos[alvo] in digitos_novas and digitos[alvo] not in digitos_resposta:
                return guarda(alvo)
    return None


_MIDIA_ENVIADA = re.compile(r"\[m[íi]dia enviada:\s*(https?://[^\]\s]+)\s*\]", re.IGNORECASE)


def _midias_ja_enviadas(entrada: Entrada) -> set[str]:
    """URLs das mídias que a IA já mandou nesta conversa (o pipeline grava "[mídia enviada: URL]"), normalizadas."""
    from app.cerebro import catalogo

    return {catalogo.normalizar_url(achado.group(1)) for m in entrada.historico if m.get("autor") == "você"
            for achado in _MIDIA_ENVIADA.finditer(str(m.get("texto") or ""))}


def _guardas_de_midia(entrada: Entrada, mensagens: list[dict[str, Any]], permitidas: set[str],
                      ja_enviadas: set[str]) -> list[_Guarda]:
    """Mídia fora do roteiro (link inventado, trocado ou de outro escritório) e mídia já enviada na conversa. Leves:
    pedem uma correção; a mídia fora do roteiro que sobrar sai da resposta (ver _turno_catalogo)."""
    from app.cerebro import catalogo
    from app.cerebro.extrator import normalizar

    guardas: list[_Guarda] = []
    if catalogo.midias_fora_do_roteiro(mensagens, permitidas):
        guardas.append(_Guarda("midia_desconhecida", "Use só os links de mídia do roteiro, copiados exatamente (sem "
                                                     "trocar nem inventar nada no link), sozinhos no balão."))
    repetidas = [m["url"] for m in mensagens if m["tipo"] == "midia" and catalogo.normalizar_url(m["url"]) in ja_enviadas]
    if repetidas and not _PEDE_REENVIO.search(normalizar(" ".join(entrada.novas))):
        guardas.append(_Guarda("midia_repetida", "Essa mídia já foi enviada nesta conversa (está no histórico): não envie "
                                                 "de novo; responda por texto, com suas palavras."))
    return guardas


def _guardas_do_catalogo(entrada: Entrada, produto: Any, saida: Saida, *, etapa: str, destino: str, textos: list[str],
                         papeis: dict[str, Any], acoes: list[str], marcas: list[str], regras: aa.Regras,
                         calculadora: bool) -> list[_Guarda]:
    """Travas do motor sobre a resposta do agente do catálogo. Cada uma vale para qualquer escritório e age por uma
    CORRIJA; as "duras" (repetir um pedido já respondido) passam a conversa para a equipe se a IA insistir, as outras
    deixam a 2ª resposta seguir (nenhuma pausa o lead por paráfrase ou por um fato que o extrator não pegou)."""
    from app.cerebro import catalogo

    fatos = saida.fatos_depois
    guardas: list[_Guarda] = []
    if produto.contrato and (cpf := _cpf_valido_pedido_de_novo(entrada, fatos, textos)):
        guardas.append(cpf)
    if repetida := _resposta_repetida(entrada, saida, textos):
        guardas.append(repetida)
    if {"buscar_cep", "zapsign"} & set(acoes):
        do_lead = list(entrada.novas) + [m.get("texto") or "" for m in entrada.historico if m.get("autor") == "lead"]
        # O que o motor deu ao modelo como fonte (DADOS DO ESCRITÓRIO, FAQ, documentos, roteiro, fatos do sistema): o
        # endereço do escritório vindo dali não é inventado.
        fontes = [agente.montar_conhecimento(entrada.conhecimento), str(entrada.instrucoes.get(etapa) or "")]
        fontes += [str(v) for v in (entrada.fatos_sistema or {}).values() if isinstance(v, (str, int))]
        fontes += base_conhecimento.textos_da_base(entrada)      # trechos da base enviados neste turno
        if inventado := catalogo.endereco_sem_fonte(textos, {k: v for k, v in fatos.items() if not str(k).startswith("_")},
                                                    do_lead, fontes):
            guardas.append(_Guarda("endereco_sem_fonte",
                                   f"Não invente o endereço ('{inventado}'): use só o que está em DADOS JÁ INFORMADOS ou o "
                                   "que o lead escreveu. Se o sistema não achou o CEP, peça o endereço ao lead."))
    if not destino:
        return guardas
    cfg_etapa = papeis.get(etapa) or {}
    cfg_destino = papeis.get(destino) or {}
    if faltam_portao := _faltam_no_portao(produto, destino, fatos, regras, calculadora, etapa):
        # Portão de fatos (B4): a troca é do código. A IA recebe o que falta perguntar e refaz sem a passagem.
        guardas.append(_Guarda("portao_de_fatos", _orientacao_do_portao(destino, faltam_portao)))
        saida.contexto.setdefault("portao_pediu", {"destino": destino, "faltam": list(faltam_portao)})
    # Pergunta do roteiro que o escritório exige antes de passar (config perguntar_antes_de_transferir): uma vez na conversa.
    marca = f"{etapa}>{destino}"
    faltam = [grupo for grupo in catalogo.perguntar_antes_de_transferir(cfg_etapa).get(destino, [])
              if not any(fatos.get(f) not in (None, "") for f in grupo)]
    if faltam and marca not in marcas:
        rotulos = "; ".join(aa.O_QUE_PERGUNTAR.get(g[0], g[0].replace("_", " ")) for g in faltam)
        guardas.append(_Guarda("perguntar_antes_de_transferir",
                               f"Antes de passar o lead adiante, faça a pergunta do roteiro sobre: {rotulos}. Deixe "
                               "transferir_para vazio nesta resposta e não use a frase de passagem. Se o lead já disse que "
                               "não sabe ou não lembra, aceite a resposta aproximada.", marca=marca))
    if outro := catalogo.frase_de_outro_destino(textos, destino, etapa, papeis):
        frase = cfg_destino.get("mensagem_troca")
        guardas.append(_Guarda("frase_de_outro_destino",
                               f"Você marcou transferir_para = \"{destino}\", mas escreveu a frase de passagem de \"{outro}\" "
                               f"(\"{papeis[outro]['mensagem_troca']}\"). "
                               + (f"Use a frase de \"{destino}\": \"{frase}\"" if frase else f"Tire a frase de \"{outro}\"")
                               + ", ou corrija transferir_para."))
    elif cfg_destino.get("exigir_frase_de_troca") and (frase := cfg_destino.get("mensagem_troca")) \
            and not catalogo.tem_frase(textos, frase):
        # Só com a opção ligada no destino: em alguns papéis quem diz a frase é o próprio agente de destino.
        guardas.append(_Guarda("frase_de_troca",
                               f"Ao passar o lead para \"{destino}\", envie exatamente esta frase: \"{frase}\". Se ainda "
                               "precisa confirmar alguma coisa com o lead, não transfira agora (deixe transferir_para vazio)."))
    if calculadora and etapa == "periododegraca" and destino == "desqualificado":
        cobertura = contexto.cobertura_na_data_do_acidente(fatos, regras)
        if cobertura and cobertura[0] == "dentro":
            # Texto neutro: o extrator do catálogo não tem aposentadoria nem advogado para o código conferir.
            guardas.append(_Guarda("periodo_coberto",
                                   "Pelos FATOS DO SISTEMA a pessoa estava coberta na data do acidente: só desqualifique "
                                   "por outro motivo do roteiro (aposentadoria, advogado no caso, sem sequela)."))
    return guardas


def _com_frase_de_troca(saida: Saida, mensagens: list[dict[str, Any]], destino: str, papeis: dict[str, Any],
                        etapa: str) -> list[dict[str, Any]]:
    """Passagem sem a frase de troca do destino: o motor põe a frase exata como ÚLTIMO balão (depois do texto de saída do
    roteiro, como "Pelas datas que você me passou..."; é a regra de passagem do motor: a mensagem de entrada fecha a
    resposta). O modelo omitia a frase em 4 de 10 passagens (rodada real de 25/11/2026), e o lead entrava na etapa nova
    sem o aviso que o roteiro manda. Vale por padrão para todo destino com `mensagem_troca`; `inserir_frase_de_troca:
    false` no papel de destino desliga (quando quem diz a frase é o próprio agente de destino)."""
    from app.cerebro import catalogo

    cfg = papeis.get(destino) or {}
    frase = str(cfg.get("mensagem_troca") or "").strip() if isinstance(cfg, dict) else ""
    if not frase or cfg.get("inserir_frase_de_troca") is False:
        return mensagens
    if catalogo.tem_frase([m.get("texto", "") for m in mensagens if m.get("tipo") == "texto"], frase):
        return mensagens
    saida.eventos.append(_evento("frase_de_troca_inserida", "info", "lawchat",
                                 f"A IA passou para {destino} sem a frase de troca; o sistema incluiu a frase.",
                                 destino=destino, etapa=etapa))
    return list(mensagens) + formatador.formatar([{"tipo": "texto", "texto": frase}])


def _linha_dados_que_faltam(entrada: Entrada, saida: Saida) -> str | None:
    """Linha do conteúdo no papel Contratos: os obrigatórios do contrato (do modelo ZapSign do agente, ou o padrão) que
    ainda faltam ou estão inválidos, pela mesma conferência da geração do contrato."""
    from app.contrato import dados as cdados

    _, erros = cdados.validar_dados(cdados.dados_dos_fatos(saida.fatos_depois), entrada.fatos_sistema.get("telefone"),
                                    entrada.obrigatorios_contrato or cdados.OBRIGATORIOS_PADRAO)
    if not erros:
        return ("DADOS DO CONTRATO QUE FALTAM (sistema): nenhum obrigatório; siga o roteiro (os opcionais que faltarem e "
                "o resumo final).")
    return ("DADOS DO CONTRATO QUE FALTAM (sistema): "
            + ", ".join(dict.fromkeys(ROTULO_DO_CAMPO.get(e.campo, e.campo) for e in erros)) + ".")


def _variaveis_sem_valor(entrada: Entrada, saida: Saida, etapa: str, faltam: list[str]) -> None:
    """Variável {{X}} sem valor no cadastro: a linha dela saiu do texto e fica um evento de cadastro, uma vez por
    variável na conversa (marca)."""
    if not faltam:
        return
    vistos = [str(v) for v in (entrada.fatos.get(MARCA_VARIAVEIS_SEM_VALOR) or []) if v]
    novos = [v for v in faltam if v not in vistos]
    for nome in novos:
        saida.eventos.append(_evento("variavel_sem_valor", "aviso", "cadastro",
                                     f"Campo {{{{{nome}}}}} sem valor: a linha que o usa saiu do texto enviado à IA. "
                                     "Preencha em Dados do seu escritório.", variavel=nome, etapa=etapa))
    _gravar_marca(saida, MARCA_VARIAVEIS_SEM_VALOR, vistos, novos)


def _segurar_transferencia(entrada: Entrada, saida: Saida, destino: str, mensagens: list[dict[str, Any]],
                           papeis: dict[str, Any], etapa: str) -> str:
    """Passagem sem a frase de troca do destino e com uma pergunta do papel atual em aberto: a troca espera um turno
    (a resposta à pergunta é do papel atual: "nunca trabalhei de carteira" caía no período de graça e não no
    desqualificado). Uma vez seguida por destino; na seguinte passa. A frase não é acrescentada: o roteiro de origem
    pode não mandar dizê-la."""
    from app.cerebro import catalogo

    adiada = str(entrada.fatos.get(MARCA_ADIADA) or "")
    textos = [m.get("texto", "") for m in mensagens if m["tipo"] == "texto"]
    frase = (papeis.get(destino) or {}).get("mensagem_troca") if destino else None
    if destino and frase and not catalogo.tem_frase(textos, frase) and any("?" in t for t in textos):
        if adiada != destino:
            _gravar_controle(saida, MARCA_ADIADA, destino)
            saida.eventos.append(_evento("transferencia_adiada_pergunta_aberta", "info", "lawchat",
                                         f"Passagem para {destino} adiada: a resposta tem pergunta em aberto e não tem a "
                                         "frase de troca.", destino=destino, etapa=etapa))
            return ""
        saida.eventos.append(_evento("transferencia_sem_frase", "info", "lawchat",
                                     f"Passagem para {destino} sem a frase de troca (já adiada uma vez).", destino=destino))
    if adiada:
        _gravar_controle(saida, MARCA_ADIADA, "")
    return destino


def _gravar_controle(saida: Saida, chave: str, valor: Any) -> None:
    saida.fatos_novos.append({"chave": chave, "valor": valor, "trecho": "(trava do motor)", "fonte": "sistema"})
    saida.fatos_depois[chave] = valor


def _correcao_repetida(entrada: Entrada, saida: Saida) -> list[str] | None:
    """Campos da correção que o zapsign pediria de novo, se ela já foi pedida na conversa e o lead não trouxe nenhum
    dado do contrato neste turno. None = pode chamar (dados certos, correção nova ou dado novo para conferir)."""
    from app.cerebro.extrator import normalizar
    from app.contrato import dados as cdados

    # Os obrigatórios do modelo do agente, como na ação gerar_contrato: com o padrão, um modelo que exige e-mail não
    # achava erro, o laço do lead sem e-mail seguia mudo ("vou gerar seu contrato" a cada turno, sem link nem equipe).
    _, erros = cdados.validar_dados(cdados.dados_dos_fatos(saida.fatos_depois), entrada.fatos_sistema.get("telefone"),
                                    entrada.obrigatorios_contrato or cdados.OBRIGATORIOS_PADRAO)
    if not erros:
        return None
    pedido = normalizar(cdados.pedir_correcao(erros))
    ja_pedido = any(pedido in normalizar(m.get("texto") or "") for m in entrada.historico if m.get("autor") != "lead")
    do_contrato = set(cdados.CAMPOS.values()) | {"nome"}
    dado_novo = any(f.get("chave") in do_contrato for f in saida.fatos_novos)
    return [e.campo for e in erros] if ja_pedido and not dado_novo else None


def _com_comeco_da_conversa(sistema: str, entrada: Entrada) -> str:
    """Fim do sistema, como no n8n: a ficha do começo da conversa e as antigas que ainda não entraram nela."""
    from app import memoria

    bloco = memoria.bloco_comeco_da_conversa(entrada.comeco_conversa)
    return f"{sistema}\n\n---\n\n{bloco}" if bloco else sistema


def _falha(saida: Saida, onde: str, erro: ErroModelo) -> Saida:
    """A IA falhou: não inventa resposta. Fica em silêncio e avisa a equipe."""
    responsavel = "cliente" if erro.motivo in ("chave_recusada", "sem_credito", "sem_permissao") else "provedor"
    saida.situacao, saida.motivo = "erro", f"{onde}:{erro.motivo}"
    saida.mensagens = []
    saida.eventos.append(_evento(
        "ia_nao_respondeu", "critico", responsavel,
        f"Falha no {onde}: {erro.motivo}. O lead ficou sem resposta.", detalhe=erro.detalhe,
    ))
    return saida


# ---------------------------------------------------------------------------- auditoria dos tickets (cat. 19, 20, 23)
MODOS_DE_DESQUALIFICAR = ("desqualificar", "analise_manual")


def _opcao_do_agente(config: dict[str, Any] | None, chave: str) -> Any:
    """Opção do agente: no topo da config (sobrevive à sincronização do produto, que troca o bloco "catalogo" inteiro)
    ou, como reserva, em config.catalogo."""
    config = config or {}
    if chave in config:
        return config.get(chave)
    return (config.get("catalogo") or {}).get(chave)


def desqualificar_modo(config: dict[str, Any] | None) -> str:
    """"desqualificar" (padrão: o papel Desqualificado encerra com a negativa) ou "analise_manual" (a IA não nega: passa
    para a equipe analisar, desliga neste lead e avisa)."""
    modo = str(_opcao_do_agente(config, "desqualificar_modo") or "").strip().lower()
    return modo if modo in MODOS_DE_DESQUALIFICAR else "desqualificar"


def pedir_pessoa_na_segunda(config: dict[str, Any] | None) -> bool:
    """O 1º pedido de pessoa fica com a IA (ela tenta resolver); só o 2º pausa. Padrão: ligado."""
    return _opcao_do_agente(config, "pedir_pessoa_na_segunda") is not False


def permitir_volta_sdr(config: dict[str, Any] | None) -> bool:
    """O Desqualificado pode devolver o lead ao SDR (uma vez) quando uma informação muda. Padrão: pode."""
    return _opcao_do_agente(config, "permitir_volta_sdr") is not False


def _desqualificado_em_analise(entrada: Entrada, saida: Saida, etapa: str) -> Saida:
    saida.etapa_depois = etapa
    saida.estado_lead, saida.motivo_estado = "pausado", "analise_manual:desqualificacao"
    saida.motivo = saida.motivo_estado
    saida.mensagens = _fixa(entrada, "analise_manual")
    motivo = saida.contexto.get("motivo_desqualificacao")
    saida.eventos.append(_evento("analise_manual", "aviso", "lawchat",
                                 "A IA ia desqualificar o lead; pela opção do escritório o caso foi para a equipe "
                                 "analisar, sem negativa ao lead.", causa="desqualificacao", etapa=etapa,
                                 motivo_desqualificacao=motivo))
    return saida


def _desqualificacao_esquecida(entrada: Entrada, produto: Any, saida: Saida, etapa: str, destino: str,
                               destinos: list[str]) -> str | None:
    """Cat. 20. Orientação (CORRIJA) quando os fatos já desqualificam o caso e a IA não escolheu desqualificar. Uma vez
    passado à equipe por esse motivo, o mesmo fato não volta a disparar (a equipe já decidiu)."""
    from app.cerebro import catalogo

    if etapa == "desqualificado" or destino == "desqualificado" or "desqualificado" not in destinos \
            or not corrigir_desqualificacao_esquecida(getattr(produto, "config", {})):
        return None
    if saida.contexto.get("desqualificacao_no_closer") == "confirmar":
        return None          # neste turno o Closer foi orientado a confirmar o dado antes (não a desqualificar já)
    motivo = catalogo.motivo_de_desqualificar(getattr(produto, "config", {}), saida.fatos_depois)
    if not motivo or entrada.fatos.get(MARCA_DESQ_ESQUECIDA) == motivo[0]:
        return None
    return (f"Pelo que o lead disse ({motivo[0]} = {motivo[1]}), o caso se encaixa na desqualificação do roteiro. "
            "Marque transferir_para = \"desqualificado\" e siga a regra de desqualificação. Se o lead corrigiu essa "
            "informação na conversa, siga o roteiro e confirme com ele o dado certo.")


def _desqualificacao_insistida(produto: Any, saida: Saida, etapa: str) -> None:
    from app.cerebro import catalogo

    motivo = catalogo.motivo_de_desqualificar(getattr(produto, "config", {}), saida.fatos_depois) or ("?", None)
    _gravar_controle(saida, MARCA_DESQ_ESQUECIDA, motivo[0])
    saida.eventos.append(_evento("desqualificacao_esquecida", "aviso", "lawchat",
                                 f"O lead disse algo que desqualifica o caso ({motivo[0]} = {motivo[1]}), mas a IA não "
                                 "desqualificou nem depois da correção. A conversa seguiu; vale a equipe conferir.",
                                 fato=motivo[0], valor=motivo[1], etapa=etapa))


# Closer que ouve um motivo de desqualificação novo (com o portão de fatos desligado, nada no código desqualifica e a
# IA do Closer seguia vendendo para quem disse "sou aposentado" ou "já tenho advogado nesse caso"). Dois turnos:
#   1. o extrator gravou neste turno um fato que desqualifica: a IA confirma uma vez, com uma pergunta curta;
#   2. no turno seguinte, com o fato ainda valendo: se o lead confirmou, desqualifica; se corrigiu, segue o roteiro.
MARCA_DESQ_A_CONFIRMAR = "_desqualificacao_a_confirmar"   # fato que desqualifica dito no Closer, à espera da confirmação
ROTULO_DO_MOTIVO = {"aposentado": "que já é aposentado(a)", "tem_advogado_no_caso": "que já tem advogado cuidando deste caso",
                    "sequela": "que não ficou com sequela", "vinculo_na_data": "a situação de trabalho na data do acidente",
                    "documentos_rurais": "que não tem documento do trabalho rural",
                    "recebe_beneficio": "que quem vai receber já recebe um benefício (BPC, aposentadoria ou pensão)"}
ORIENTACAO_CONFIRMAR_NO_CLOSER = (
    "O lead acabou de dizer {rotulo} (\"{trecho}\"), o que desqualifica o caso pelo roteiro. Nesta etapa, confirme uma "
    "vez, numa pergunta curta e nova (ex.: \"Só pra eu não errar: {pergunta}\"), sem explicar o motivo e sem seguir com "
    "a venda. Advogado de antes, que já saiu, ou de outro caso NÃO desqualifica. Se ele já tinha confirmado isso com "
    "clareza antes na conversa, marque transferir_para = \"desqualificado\" agora.")
ORIENTACAO_CONFIRMOU_NO_CLOSER = (
    "Você pediu para o lead confirmar {rotulo}. Se ele confirmou, marque transferir_para = \"desqualificado\" nesta "
    "resposta e siga a regra de desqualificação. Se ele corrigiu (ou é advogado de antes ou de outro caso), siga o "
    "roteiro normalmente.")
PERGUNTA_DO_MOTIVO = {"aposentado": "você já é aposentado(a) hoje?",
                      "tem_advogado_no_caso": "você já tem um advogado cuidando deste mesmo caso?",
                      "sequela": "você não ficou com nenhuma sequela ou limitação depois do acidente?",
                      "recebe_beneficio": "hoje já é pago algum benefício do INSS para quem vai receber?"}


def confirmar_desqualificacao_no_closer(config: dict[str, Any] | None) -> bool:
    """Orientar o Closer a confirmar e desqualificar quando o lead diz algo novo que desqualifica. Padrão: ligado (só no
    papel closer; nos outros vale corrigir_desqualificacao_esquecida, desligada); "confirmar_desqualificacao_no_closer":
    false desliga."""
    return _opcao_do_agente(config, "confirmar_desqualificacao_no_closer") is not False


def _desqualificacao_no_closer(entrada: Entrada, produto: Any, saida: Saida, etapa: str,
                               destinos: list[str]) -> str | None:
    """Orientação (linha "(sistema)" do conteúdo) do Closer para um motivo de desqualificação novo. Ver acima."""
    from app.cerebro import catalogo

    config = getattr(produto, "config", {}) or {}
    pendente = str(entrada.fatos.get(MARCA_DESQ_A_CONFIRMAR) or "")
    ligado = etapa == "closer" and "desqualificado" in destinos and confirmar_desqualificacao_no_closer(config)
    motivos = catalogo.motivos_de_desqualificar(config)
    novo = next((f for f in saida.fatos_novos if ligado and str(f.get("chave") or "") in motivos
                 and str(f.get("valor") or "").strip().lower() in motivos[str(f.get("chave"))]), None)
    if novo is not None:
        chave = str(novo["chave"])
        _gravar_controle(saida, MARCA_DESQ_A_CONFIRMAR, chave)
        saida.contexto["desqualificacao_no_closer"] = "confirmar"
        return ORIENTACAO_CONFIRMAR_NO_CLOSER.format(
            rotulo=ROTULO_DO_MOTIVO.get(chave, chave.replace("_", " ")), trecho=str(novo.get("trecho") or "")[:120],
            pergunta=PERGUNTA_DO_MOTIVO.get(chave, "é isso mesmo?"))
    if not pendente:
        return None
    _gravar_controle(saida, MARCA_DESQ_A_CONFIRMAR, "")          # a marca vale só para o turno seguinte
    if not ligado:
        return None
    if str(saida.fatos_depois.get(pendente) or "").strip().lower() not in motivos.get(pendente, ()):
        return None                                      # o lead corrigiu o dado: nada a confirmar
    saida.contexto["desqualificacao_no_closer"] = "confirmou"
    return ORIENTACAO_CONFIRMOU_NO_CLOSER.format(rotulo=ROTULO_DO_MOTIVO.get(pendente, pendente.replace("_", " ")))


def exigir_confirmacao_contrato(config: dict[str, Any] | None) -> bool:
    """Pedir ao modelo o resumo confirmado antes do zapsign (uma CORRIJA). Padrão: sim; "confirmar_dados_contrato":
    false desliga."""
    return _opcao_do_agente(config, "confirmar_dados_contrato") is not False


def corrigir_desqualificacao_esquecida(config: dict[str, Any] | None) -> bool:
    """Lembrar a IA de desqualificar quando os fatos já desqualificam (uma CORRIJA). Padrão: desligado (a IA pode estar
    confirmando o dado com o lead, ex.: "sou aposentado" -> "você tem advogado?"); "corrigir_desqualificacao_esquecida":
    true liga."""
    return _opcao_do_agente(config, "corrigir_desqualificacao_esquecida") is True


ORIENTACAO_SEM_CONFIRMACAO = ("O lead ainda não confirmou os dados do contrato. Deixe ferramenta vazia nesta resposta: "
                              "mostre o resumo dos dados (nome completo, CPF, endereço com número, bairro, cidade, "
                              "estado e CEP) e pergunte se está tudo certo para gerar o contrato.")
# Resposta curta que confirma ("sim", "isso mesmo", "tá certo, pode gerar"). Negação ou correção no texto: não confirma.
_PALAVRAS_DO_SIM = {"sim", "s", "isso", "mesmo", "exato", "exatamente", "correto", "corretos", "certo", "certos",
                    "certinho", "ta", "to", "esta", "estao", "tudo", "confirmo", "confirmado", "confirmados", "pode",
                    "gerar", "mandar", "seguir", "fazer", "ok", "okay", "perfeito", "beleza", "blz", "positivo", "obrigado",
                    "obrigada", "e", "ai", "os", "dados", "todos", "sao", "esses", "estes", "favor", "por", "agora",
                    "entao", "ja", "pronto", "manda", "gera", "bora", "vamos", "ss", "sss", "simm", "obg", "tudinho",
                    "contrato", "o", "certinho"}
_SIM_FORTE = {"sim", "s", "isso", "exato", "exatamente", "correto", "corretos", "certo", "certos", "certinho", "confirmo",
              "confirmado", "confirmados", "pode", "ok", "okay", "perfeito", "positivo", "ss", "sss", "simm", "gera",
              "manda"}


def _e_um_sim(normal: str) -> bool:
    """Resposta curta que confirma ("sim", "isso mesmo", "tá tudo certo, pode gerar"), sobre o texto normalizado."""
    palavras = normal.split()
    return bool(palavras) and len(palavras) <= 10 and set(palavras) <= _PALAVRAS_DO_SIM and bool(set(palavras) & _SIM_FORTE)


_NAO_CONFIRMA = re.compile(r"\b(?:nao|errad\w*|corrig\w*|mud\w*|troc\w*|falta\w*)\b")


def _dados_validos(entrada: Entrada, saida: Saida) -> dict[str, str]:
    from app.contrato import dados as cdados

    dados, _ = cdados.validar_dados(cdados.dados_dos_fatos(saida.fatos_depois), entrada.fatos_sistema.get("telefone"),
                                    entrada.obrigatorios_contrato or cdados.OBRIGATORIOS_PADRAO)
    return dados


def _parece_resumo(textos: list[str], dados: dict[str, str]) -> bool:
    """O bloco da IA mostra os dados do contrato: dois ou mais valores dos dados (nome, CPF, rua, cidade, CEP)."""
    from app.cerebro.extrator import normalizar

    tudo = normalizar(" ".join(textos))
    digitos = _so_digitos(" ".join(textos))
    achados = 0
    for campo in ("nome", "endereco", "cidade", "bairro"):
        if dados.get(campo) and normalizar(dados[campo]) in tudo:
            achados += 1
    for campo in ("cpf", "cep"):
        if dados.get(campo) and _so_digitos(dados[campo]) in digitos:
            achados += 1
    return achados >= 2


def _lead_confirmou_dados(entrada: Entrada, saida: Saida) -> bool:
    """Cat. 23. O lead confirmou o resumo dos dados do contrato: pela intenção do extrator, por um "sim" respondendo à
    última mensagem de resumo da IA, ou já confirmou estes mesmos dados antes (marca com o hash). Depois de uma
    correção pedida pelo sistema (o contrato já tinha sido pedido com os dados confirmados), vale o dado corrigido."""
    from app.cerebro.extrator import normalizar
    from app.contrato import dados as cdados

    dados = _dados_validos(entrada, saida)
    assinatura = cdados.hash_dados(dados)
    pedido_de_correcao = normalizar("Para finalizar seu contrato, preciso confirmar")
    resposta = normalizar(" ".join(entrada.novas))
    confirmou = bool(
        saida.intencoes.get("confirmou_dados")
        or entrada.fatos.get(MARCA_DADOS_CONFIRMADOS) == assinatura
        or any(pedido_de_correcao in normalizar(m.get("texto") or "") for m in entrada.historico if m.get("autor") != "lead")
        or (_e_um_sim(resposta) and not _NAO_CONFIRMA.search(resposta)
            and _parece_resumo(_ultima_resposta_da_ia(entrada.historico), dados)))
    if confirmou and dados and entrada.fatos.get(MARCA_DADOS_CONFIRMADOS) != assinatura:
        _gravar_controle(saida, MARCA_DADOS_CONFIRMADOS, assinatura)
    return confirmou


# ---------------------------------------------------------------------------- contrato do BPC infantil
# Rodada real (26/11): a mãe respondeu "Qual o nome completo do seu filho?" e o extrator gravou o nome da criança em
# nome_completo (de quem ASSINA); a filiação da mãe não foi gravada e o contrato entrou em laço de correção. No fluxo
# da Karina (n8n) quem assina é sempre quem conversa e a criança vai em campos próprios ("Qual o nome completo do(a)
# menor?", "filiação do(a) menor", "filiação da mae"). Aqui o código usa a ÚLTIMA PERGUNTA DA IA para decidir de quem é o
# dado: pergunta sobre o filho/a criança -> campos _menor; pergunta sobre "seus pais"/"sua filiação" -> campos sem _menor.
_SOBRE_A_CRIANCA = re.compile(r"\b(filh[oa]s?|crian[çc]a|menor|beb[eê]|dele|dela|do\(a\)|da\(o\))\b", re.I)
_SOBRE_QUEM_FALA = re.compile(r"\b(seu|sua|voc[eê]|seus pais|sua m[aã]e|seu pai)\b", re.I)
_TROCA_PARA_O_MENOR = {"nome_completo": "nome_menor", "cpf": "cpf_menor", "nacionalidade": "nacionalidade_menor",
                       "naturalidade": "naturalidade_menor", "filiacao": "filiacao_menor"}
_TROCA_PARA_QUEM_ASSINA = {v: k for k, v in _TROCA_PARA_O_MENOR.items() if k != "nome_completo"}


def _ultima_pergunta_da_ia(entrada: Entrada) -> str:
    for mensagem in reversed(entrada.historico or []):
        if mensagem.get("autor") != "lead" and "?" in str(mensagem.get("texto") or ""):
            return str(mensagem.get("texto") or "")
    return ""


def _dados_da_crianca_pela_pergunta(entrada: Entrada, produto: Any, extracao: Any, saida: Saida) -> None:
    from app.cerebro import catalogo

    if catalogo.familia_do_produto(getattr(produto, "config", {})) != "bpc_infantil":
        return
    pergunta = _ultima_pergunta_da_ia(entrada)
    trecho_da_pergunta = pergunta.split("?")[-2] if pergunta.count("?") >= 1 else pergunta
    sobre_crianca = bool(_SOBRE_A_CRIANCA.search(trecho_da_pergunta))
    # "seus pais" com "do seu filho" na mesma pergunta é sobre a criança: a criança ganha.
    sobre_quem_fala = bool(_SOBRE_QUEM_FALA.search(trecho_da_pergunta)) and not sobre_crianca
    nome_menor = str(entrada.fatos.get("nome_menor") or "").strip().lower()
    for fato in extracao.fatos:
        destino = None
        if sobre_crianca and fato.chave in _TROCA_PARA_O_MENOR:
            destino = _TROCA_PARA_O_MENOR[fato.chave]
        elif sobre_quem_fala and fato.chave in _TROCA_PARA_QUEM_ASSINA:
            destino = _TROCA_PARA_QUEM_ASSINA[fato.chave]
        elif fato.chave == "nome_completo" and nome_menor and str(fato.valor or "").strip().lower() == nome_menor:
            # O nome da criança (já gravado) não pode virar o nome de quem assina.
            destino = "descartar"
        if not destino:
            continue
        saida.eventos.append(_evento("dado_do_contrato_realocado", "info", "lawchat",
                                     f"{fato.chave} → {destino} pela última pergunta da IA (contrato do BPC infantil).",
                                     pergunta=trecho_da_pergunta[-160:]))
        fato.chave = destino
    extracao.fatos = [f for f in extracao.fatos if f.chave != "descartar"]
