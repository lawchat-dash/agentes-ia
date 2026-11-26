"""Nota do lead de 0 a 10, com a faixa (frio, morno, quente) e o motivo de cada ponto (ANALISE_5_PROJETOS, B8).

Calculada em código, sem IA, a partir do que já está no banco (fatos, etapa, mensagens, contrato e intenções dos
turnos). Serve só para organizar a fila da equipe: nunca muda o que a IA diz ao lead, nunca desqualifica e nunca
entra no follow-up como pressão. Os motivos ficam visíveis (LGPD, art. 20: direito de explicação).

Pesos padrão (previdenciário). Somam 10:

    condição       +2  tem sequela ou condição (sequela = sim; ou fato de doença/deficiência/laudo do catálogo)
    segurado       +2  qualidade de segurado provável (carteira assinada na data, MEI/autônomo, rural com documentos,
                       período de graça com seguro-desemprego ou saída há até 12 meses, contribuiu por conta própria,
                       recebeu auxílio-doença)
    rápido         +1  respondeu rápido (mediana das últimas respostas à IA em até 30 min)
    aceitou        +2  aceitou a proposta (intenção aceitou_honorarios ou já passou para contrato/assinatura)
    link           +1  pediu o link do contrato
    contrato       +1  contrato gerado  (+2 se assinado)

Desqualificadores ZERAM a nota (faixa frio): etapa desqualificado, aposentado, já tem advogado no caso, sem sequela,
servidor estatutário ou nunca trabalhou, disse que foi engano ou pediu para parar.

Faixas: 0 a 3 frio, 4 a 6 morno, 7 a 10 quente. A primeira vez que chega a quente sai o evento "lead_quente" e o aviso à
equipe ("Avisos à equipe", evento lead_quente) com nome, benefício, nota e motivos. Nunca com CPF.

Onde fica: agentesia_lead_fatos, chave "_temperatura" (fonte 'sistema'; chaves com "_" são de controle e não vão para o
prompt). Valor: {"nota", "faixa", "motivos", "avisou_quente", "calculada_em"}. Sem migração.

Quem chama: `atualizar(pool, id_lead)` depois de cada turno, pelo gancho `automacoes.depois_do_turno`, que hoje roda
dentro de `app/followup/servico.agendar` (o pipeline já chama o agendar depois de cada resposta da IA).
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

log = logging.getLogger("agentesia.temperatura")

PESOS: dict[str, int] = {"condicao": 2, "segurado": 2, "rapido": 1, "aceitou": 2, "link": 1,
                         "contrato_gerado": 1, "contrato_assinado": 2}
QUENTE = 7
MORNO = 4
RAPIDO_MIN = 30
CHAVE = "_temperatura"

SIM = {"sim", "s", "yes", "true", "1"}
NAO = {"nao", "não", "n", "no", "false", "0"}
# Fatos de condição de saúde que os produtos do catálogo costumam extrair (além da "sequela" do Auxílio-Acidente).
CHAVES_CONDICAO_SIM_NAO = ("sequela", "tem_sequela", "tem_condicao", "condicao", "tem_doenca", "doenca", "tem_deficiencia",
                           "deficiencia", "incapacidade", "tem_incapacidade", "tem_laudo", "laudo")
CHAVES_CONDICAO_TEXTO = ("sequela_descricao", "condicao_descricao", "doenca_descricao", "deficiencia_descricao", "cid")
ETAPAS_DEPOIS_DO_ACEITE = {"contratos", "coleta_dados", "assinatura", "contrato_assinado"}

NOMES_BENEFICIO = {"auxilio_acidente": "Auxílio-Acidente"}
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")


def _txt(valor: Any) -> str:
    if isinstance(valor, bool):
        return "sim" if valor else "nao"
    return str(valor if valor is not None else "").strip().lower()


def _sim(fatos: Mapping[str, Any], chave: str) -> bool:
    return _txt(fatos.get(chave)) in SIM


def _desqualificadores(fatos: Mapping[str, Any], etapa: str | None, intencoes: set[str],
                       ultima_do_lead: str | None) -> list[str]:
    from app.followup import regras

    motivos = []
    if etapa == "desqualificado":
        motivos.append("lead desqualificado")
    if _sim(fatos, "aposentado"):
        motivos.append("já é aposentado")
    if _sim(fatos, "tem_advogado_no_caso"):
        motivos.append("já tem advogado no caso")
    if _txt(fatos.get("sequela")) in NAO:
        motivos.append("disse que não ficou com sequela")
    if _txt(fatos.get("vinculo_na_data")) in ("servidor_estatutario", "nunca_trabalhou"):
        motivos.append("servidor estatutário" if _txt(fatos.get("vinculo_na_data")) == "servidor_estatutario"
                       else "nunca trabalhou")
    if "engano" in intencoes:
        motivos.append("disse que foi engano")
    if "pediu_para_parar" in intencoes or regras.pediu_para_parar(ultima_do_lead):
        motivos.append("pediu para não receber mais mensagens")
    return motivos


def _condicao(fatos: Mapping[str, Any]) -> str | None:
    if _sim(fatos, "sequela"):
        return "ficou com sequela"
    for chave in CHAVES_CONDICAO_SIM_NAO[1:]:
        if _sim(fatos, chave):
            return "tem a condição de saúde do benefício"
    for chave in CHAVES_CONDICAO_TEXTO:
        if _txt(fatos.get(chave)) not in ("", *NAO, "nao_sabe"):
            return "descreveu a sequela ou condição"
    return None


def _segurado(fatos: Mapping[str, Any]) -> str | None:
    vinculo = _txt(fatos.get("vinculo_na_data"))
    if vinculo == "clt":
        return "tinha carteira assinada na época"
    if vinculo == "mei_autonomo_ci":
        return "contribuía como MEI ou autônomo"
    if vinculo == "rural" and _sim(fatos, "documentos_rurais"):
        return "trabalhador rural com documentos"
    if _sim(fatos, "qualidade_de_segurado") or _sim(fatos, "qualidade_segurado"):
        return "qualidade de segurado provável"
    if _sim(fatos, "contribuiu_por_conta_propria"):
        return "contribuiu ao INSS por conta própria"
    if vinculo == "desempregado":
        try:
            meses = int(fatos.get("demissao_meses_antes_do_acidente"))
        except (TypeError, ValueError):
            meses = None
        if _sim(fatos, "seguro_desemprego") or (meses is not None and meses <= 12):
            return "estava no período de graça"
    if _sim(fatos, "auxilio_doenca"):
        return "recebeu auxílio-doença"
    return None


def _quando(m: Mapping[str, Any]) -> datetime | None:
    valor = m.get("enviada_em")
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor)
        except ValueError:
            return None
    return valor if isinstance(valor, datetime) else None


def _minutos_para_responder(mensagens: list[Mapping[str, Any]]) -> float | None:
    """Mediana (das últimas 5) do tempo entre uma mensagem da IA e a resposta do lead logo depois."""
    datadas = sorted((m for m in mensagens if _quando(m)), key=lambda m: _quando(m))  # type: ignore[arg-type,return-value]
    tempos = []
    for anterior, atual in zip(datadas, datadas[1:]):
        if atual.get("autor") == "lead" and anterior.get("autor") in ("ia", "você"):
            tempos.append((_quando(atual) - _quando(anterior)).total_seconds() / 60)  # type: ignore[operator]
    return statistics.median(tempos[-5:]) if tempos else None


def _situacao_do_contrato(contrato: Any) -> str | None:
    if isinstance(contrato, Mapping):
        contrato = contrato.get("situacao")
    return _txt(contrato) or None


def faixa_da_nota(nota: int) -> str:
    return "quente" if nota >= QUENTE else "morno" if nota >= MORNO else "frio"


def nota_do_lead(fatos: Mapping[str, Any] | None, etapa: str | None, mensagens_recentes: Iterable[Mapping[str, Any]] | None,
                 contrato: Any = None, *, intencoes: Iterable[str] = ()) -> dict[str, Any]:
    """Nota de 0 a 10, faixa e motivos legíveis ("+2 ficou com sequela"). Função pura.

    fatos: os fatos vigentes do lead ({chave: valor}); etapa: o código da etapa atual; mensagens_recentes:
    [{"autor": "lead"|"ia"|"humano", "enviada_em": datetime, "texto": ...}] em qualquer ordem; contrato: o último
    contrato ({"situacao": "gerado"|"assinado"...}) ou só a situação; intencoes: as marcadas nos turnos
    (aceitou_honorarios, pediu_link, pediu_para_parar, engano...)."""
    fatos = {k: v for k, v in (fatos or {}).items() if not str(k).startswith("_")}
    mensagens = [m for m in mensagens_recentes or [] if isinstance(m, Mapping)]
    marcadas = {str(i) for i in intencoes or ()}
    do_lead = [m for m in mensagens if m.get("autor") == "lead" and str(m.get("texto") or "").strip()]
    ultima_do_lead = str(max(do_lead, key=lambda m: _quando(m) or datetime.min.replace(tzinfo=timezone.utc))["texto"]) if do_lead else None

    zeram = _desqualificadores(fatos, etapa, marcadas, ultima_do_lead)
    if zeram:
        return {"nota": 0, "faixa": "frio", "motivos": [f"zerada: {m}" for m in zeram]}

    pontos: list[tuple[int, str]] = []
    if motivo := _condicao(fatos):
        pontos.append((PESOS["condicao"], motivo))
    if motivo := _segurado(fatos):
        pontos.append((PESOS["segurado"], motivo))
    minutos = _minutos_para_responder(mensagens)
    if minutos is not None and minutos <= RAPIDO_MIN:
        pontos.append((PESOS["rapido"], "responde rápido"))
    if "aceitou_honorarios" in marcadas:
        pontos.append((PESOS["aceitou"], "aceitou a proposta"))
    elif etapa in ETAPAS_DEPOIS_DO_ACEITE:
        pontos.append((PESOS["aceitou"], "aceitou a proposta e passou para o contrato"))
    if "pediu_link" in marcadas or any(re.search(r"\blink\b", str(m.get("texto") or "").lower()) for m in do_lead):
        pontos.append((PESOS["link"], "pediu o link do contrato"))
    situacao = _situacao_do_contrato(contrato)
    if situacao == "assinado" or etapa == "contrato_assinado":
        pontos.append((PESOS["contrato_assinado"], "assinou o contrato"))
    elif situacao == "gerado":
        pontos.append((PESOS["contrato_gerado"], "contrato gerado"))

    nota = max(0, min(10, sum(p for p, _ in pontos)))
    return {"nota": nota, "faixa": faixa_da_nota(nota), "motivos": [f"+{p} {m}" for p, m in pontos]}


def sem_cpf(texto: str) -> str:
    """Tira qualquer coisa com formato de CPF (o aviso nunca leva CPF)."""
    return _CPF.sub("[CPF omitido]", texto or "")


def motivos_em_texto(motivos: Iterable[str]) -> str:
    return sem_cpf("; ".join(str(m) for m in motivos))


# ------------------------------------------------------------------ banco
def _json(valor: Any) -> Any:
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except json.JSONDecodeError:
            return valor
    return valor


async def _dados_do_lead(pool: Any, id_lead: str) -> dict[str, Any] | None:
    lead = await pool.fetchrow(
        """select l.id, l.id_escritorio, l.id_agente, l.id_sessao_helena, ct.nome, ct.telefone_normalizado,
                  ca.numero_normalizado as numero_canal, ca.tipo as tipo_canal, ag.produto, ag.config as config_agente,
                  et.codigo as etapa, es.config as config_escritorio,
                  coalesce(b.nome, p.nome) as beneficio
           from agentesia_leads l join agentesia_contatos ct on ct.id = l.id_contato
           join agentesia_canais ca on ca.id = l.id_canal
           join agentesia_escritorios es on es.id = l.id_escritorio
           left join agentesia_agentes ag on ag.id = l.id_agente
           left join agentesia_agente_etapas et on et.id = l.id_etapa
           left join lateral (select p.nome, p.id_produto_biblioteca from agentesia_produtos_ativados p
                              where p.id_agente = l.id_agente and p.excluido_em is null limit 1) p on true
           left join agentesia_biblioteca_produtos b on b.id = p.id_produto_biblioteca
           where l.id = $1::uuid""", id_lead)
    if not lead:
        return None
    dados = dict(lead)
    for chave in ("config_agente", "config_escritorio"):
        dados[chave] = _json(dados.get(chave)) or {}
    dados["fatos"] = {r["chave"]: _json(r["valor"]) for r in await pool.fetch(
        "select chave, valor from agentesia_lead_fatos where id_lead = $1::uuid and substituido_em is null", id_lead)}
    dados["mensagens"] = [dict(r) for r in await pool.fetch(
        """select autor, enviada_em, coalesce(texto, texto_extraido) as texto from agentesia_mensagens
           where id_lead = $1::uuid order by enviada_em desc limit 40""", id_lead)]
    dados["contrato"] = await pool.fetchval(
        "select situacao from agentesia_contratos where id_lead = $1::uuid order by versao desc limit 1", id_lead)
    intencoes: set[str] = set()
    for r in await pool.fetch(
            """select resposta->'intencoes' as intencoes from agentesia_turnos
               where id_lead = $1::uuid and resposta ? 'intencoes' order by iniciado_em desc limit 50""", id_lead):
        marcadas = _json(r["intencoes"])
        if isinstance(marcadas, dict):
            intencoes |= {k for k, v in marcadas.items() if v}
    dados["intencoes"] = intencoes
    return dados


def _beneficio(dados: Mapping[str, Any]) -> str:
    return str(dados.get("beneficio") or NOMES_BENEFICIO.get(str(dados.get("produto") or ""), "")
               or str(dados.get("produto") or "").replace("_", " "))


async def atualizar(pool: Any, id_lead: str) -> dict[str, Any] | None:
    """Recalcula a nota do lead a partir do banco, grava em "_temperatura" (só se mudou) e, na primeira vez que chega a
    quente, registra o evento lead_quente, as automações do gatilho e o aviso à equipe. Devolve a nota (ou None)."""
    dados = await _dados_do_lead(pool, id_lead)
    if not dados:
        return None
    anterior = dados["fatos"].get(CHAVE) if isinstance(dados["fatos"].get(CHAVE), dict) else {}
    resultado = nota_do_lead(dados["fatos"], dados["etapa"], dados["mensagens"], dados["contrato"], intencoes=dados["intencoes"])
    avisou = bool(anterior.get("avisou_quente"))
    cruzou = resultado["nota"] >= QUENTE and not avisou
    novo = {**resultado, "avisou_quente": avisou or cruzou, "calculada_em": datetime.now(timezone.utc).isoformat()}
    mudou = any(anterior.get(k) != novo[k] for k in ("nota", "faixa", "motivos", "avisou_quente"))
    if not mudou:
        return resultado
    async with pool.acquire() as conexao, conexao.transaction():
        # Um lead por vez (dois servidores no mesmo lead): a trava some no fim da transação.
        await conexao.execute("select pg_advisory_xact_lock(hashtext($1))", f"temperatura:{id_lead}")
        if cruzou and await conexao.fetchval(
                "select exists(select 1 from agentesia_eventos where id_lead = $1::uuid and tipo = 'lead_quente')", id_lead):
            cruzou = False                                   # outro servidor já avisou
        await conexao.execute(
            """update agentesia_lead_fatos set substituido_em = now()
               where id_lead = $1::uuid and chave = $2 and substituido_em is null""", id_lead, CHAVE)
        await conexao.execute(
            """insert into agentesia_lead_fatos (id_escritorio, id_lead, chave, valor, fonte)
               values ($1, $2, $3, $4::jsonb, 'sistema')""",
            dados["id_escritorio"], dados["id"], CHAVE, json.dumps(novo, ensure_ascii=False))
        if cruzou:
            await _lead_quente(conexao, dados, resultado)
    return resultado


async def _lead_quente(conexao: Any, dados: dict[str, Any], resultado: dict[str, Any]) -> None:
    from app import automacoes, notificacoes
    from app.cerebro import sinais

    beneficio = _beneficio(dados)
    motivos = motivos_em_texto(resultado["motivos"])
    await conexao.execute(
        """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
           values ($1, $2, 'lead_quente', 'info', 'lead', $3, $4::jsonb)""",
        dados["id_escritorio"], dados["id"],
        sem_cpf(f"Lead quente: nota {resultado['nota']}/10 ({motivos})."),
        json.dumps({"nota": resultado["nota"], "faixa": resultado["faixa"], "motivos": resultado["motivos"],
                    "beneficio": beneficio}, ensure_ascii=False))
    config_agente = dados["config_agente"]
    acoes: list[dict[str, Any]] = []
    crm = _json(await conexao.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1 and tipo = 'crm'", dados["id_escritorio"])) or {}
    # Etiqueta, coluna do CRM e nota configuradas na automação "lead_quente" (o aviso sai abaixo, com nota e motivos).
    acoes += automacoes.montar_acoes(config_agente, crm if isinstance(crm, dict) else {}, ["lead_quente"],
                                     id_lead=str(dados["id"]), id_turno="temperatura", contexto=f"Nota {resultado['nota']}/10: {motivos}")
    aviso = await conexao.fetchrow(
        "select * from agentesia_notificacoes where id_escritorio = $1 and tipo_evento = 'lead_quente' and habilitada",
        dados["id_escritorio"])
    if aviso and (config_agente.get("funcoes") or {}).get("avisos"):
        destinatarios = notificacoes.filtrar_destinatarios(_json(aviso["destinatarios"]) or [], dados["numero_canal"])
        valores = notificacoes.valores_do_aviso(
            evento="lead_quente", nome=dados["nome"], telefone=dados["telefone_normalizado"], produto=beneficio,
            etapa=notificacoes.NOMES_DE_EVENTO.get(f"etapa:{dados['etapa']}", dados["etapa"]),
            link_conversa=sinais.link_da_conversa(dados["config_escritorio"], dados["id_sessao_helena"]))
        texto = notificacoes.texto_lead_quente(aviso["modelo_mensagem"], valores, nota=resultado["nota"],
                                               faixa=resultado["faixa"], motivos=motivos, beneficio=beneficio)
        for d in destinatarios:
            acoes.append({"tipo": "notificar", "chave_unica": f"{dados['id']}:lead_quente:{d.numero}",
                          "dados": {"de": dados["numero_canal"], "para": d.numero, "rotulo": d.rotulo, "texto": texto,
                                    "tipo_canal": dados["tipo_canal"], "evento": "lead_quente"}})
    for a in acoes:
        await conexao.execute(
            """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
               values ($1, $2, $3, $4, $5::jsonb) on conflict (chave_unica) do nothing""",
            dados["id_escritorio"], dados["id"], a["tipo"], a["chave_unica"], json.dumps(a["dados"], ensure_ascii=False))
