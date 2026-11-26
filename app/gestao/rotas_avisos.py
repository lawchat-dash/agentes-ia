"""Tela "Avisos no WhatsApp" (painel/src/telas/Avisos.tsx): a configuração da CONTA (número que envia e quem recebe) e
a lista fechada dos avisos que o sistema dispara de verdade, cada um com liga/desliga e o modelo da mensagem.

Onde fica guardado (o envio em app/acoes.py lê daqui, sem mudança no formato):
  - número de envio: agentesia_escritorios.config["avisos_numero_envio"] = id do canal (app/notificacoes.CONFIG_NUMERO_ENVIO);
  - quem recebe: agentesia_escritorios.config["avisos_destinatarios"] = [{"rotulo", "numero"}] e a MESMA lista copiada em
    agentesia_notificacoes.destinatarios de todos os avisos da conta (o envio continua lendo a lista de cada aviso);
  - cada aviso: uma linha em agentesia_notificacoes (tipo_evento = gatilho), com habilitada, nome e modelo_mensagem.
Aviso guardado com um tipo que não está no catálogo abaixo aparece como "antigo" (para apagar).
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import notificacoes
from app.gestao.rotas import GESTAO, Contexto, _repo

api = APIRouter(prefix="/api")

CONFIG_DESTINATARIOS = "avisos_destinatarios"
MAX_DESTINATARIOS = 30

_CAB = "👤 *Cliente:* {{nome}}\n📞 *WhatsApp:* {{telefone}}\n🛒 *Produto:* {{produto}}"
_RODAPE = "\n💬 *Conversa:* {{link_conversa}}\n🕒 {{data_hora}}"


def _modelo(titulo: str, meio: str = "🎯 *Etapa:* {{etapa}}", extra: str = "") -> str:
    return f"> `{titulo}`\n\n{_CAB}\n{meio}{extra}\n{_RODAPE}"


_MSG = "\n\n🗨️ *O que o lead disse:*\n{{mensagem_lead}}"

# Catálogo dos avisos REAIS (gatilhos que app/automacoes.py, app/acoes.py, app/cerebro/temperatura.py e o follow-up
# disparam). "chaves": os tipo_evento que valem para o aviso (o primeiro é o padrão; os outros, a mesma coisa em outro
# produto). "so_se_existir": só aparece se algum agente da conta tiver o gatilho.
CATALOGO: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- etapas do funil
    {"chave": "lead_novo", "grupo": "funil", "icone": "user-plus", "nome": "Novo lead recebido",
     "descricao": "Um lead novo chegou e a IA respondeu a primeira mensagem.", "chaves": ["lead_novo"],
     "modelo": _modelo("🔵 NOVO LEAD", "📍 *Origem:* {{origem}}")},
    {"chave": "lead_qualificado", "grupo": "funil", "icone": "badge-check", "nome": "Lead qualificado",
     "descricao": "O lead passou na qualificação e foi para o Closer (proposta e honorários).", "chaves": ["etapa:closer"],
     "modelo": _modelo("🟢 LEAD QUALIFICADO", "🎯 *Etapa CRM:* {{etapa}}")},
    {"chave": "aceitou_honorarios", "grupo": "funil", "icone": "handshake", "nome": "Lead aceitou os honorários",
     "descricao": "O lead disse que aceita os honorários.", "chaves": ["intencao:aceitou_honorarios"], "so_se_existir": True,
     "modelo": _modelo("🤝 ACEITOU OS HONORÁRIOS")},
    {"chave": "coleta_dados", "grupo": "funil", "icone": "clipboard-list", "nome": "Lead iniciou a coleta de dados",
     "descricao": "O lead começou a passar os dados do contrato.", "chaves": ["etapa:contratos", "etapa:coleta_dados"],
     "modelo": _modelo("📝 INICIOU A COLETA DE DADOS")},
    {"chave": "aguardando_assinatura", "grupo": "funil", "icone": "file-signature", "nome": "Aguardando assinatura",
     "descricao": "O contrato foi gerado e o link de assinatura foi enviado ao lead.", "chaves": ["etapa:assinatura"],
     "modelo": _modelo("🟡 AGUARDANDO ASSINATURA", "✍️ *Link de assinatura:* {{link_assinatura}}", "\n💰 *Honorários:* {{valor}}")},
    {"chave": "contrato_assinado", "grupo": "funil", "icone": "file-check", "nome": "Contrato assinado",
     "descricao": "O lead assinou o contrato. Leva o resumo do caso.", "chaves": ["contrato_assinado"],
     "modelo": "> `✅ CONTRATO ASSINADO`\n\n" + _CAB + "\n💬 *Conversa:* {{link_conversa}}\n\n📋 *Resumo:*\n{{resumo}}\n\n*🚀 Vamos pra cima!*"},
    {"chave": "desqualificado", "grupo": "funil", "icone": "user-x", "nome": "Lead desqualificado",
     "descricao": "A IA concluiu que o lead não tem o perfil do benefício.", "chaves": ["etapa:desqualificado"],
     "modelo": _modelo("⚪ LEAD DESQUALIFICADO")},
    # ---------------------------------------------------------------- pedidos de atenção
    {"chave": "pediu_humano", "grupo": "atencao", "icone": "user-round", "nome": "Pediu para falar com uma pessoa",
     "descricao": "O lead pediu atendimento humano; a IA sai da conversa.", "chaves": ["pediu_humano"],
     "modelo": _modelo("🙋 PEDIU UMA PESSOA", extra=_MSG)},
    {"chave": "analise_humana", "grupo": "atencao", "icone": "scale", "nome": "Análise humana do caso",
     "descricao": "O caso precisa da análise de alguém do escritório.", "chaves": ["sinal:analise_humana"],
     "modelo": _modelo("⚖️ ANÁLISE HUMANA", extra=_MSG)},
    {"chave": "nao_sabe_ler", "grupo": "atencao", "icone": "book-x", "nome": "Lead não sabe ler",
     "descricao": "O lead disse que não sabe ler ou lê com dificuldade.", "chaves": ["sinal:nao_sabe_ler"],
     "modelo": _modelo("📵 NÃO SABE LER", extra=_MSG)},
    {"chave": "quer_audio", "grupo": "atencao", "icone": "mic", "nome": "Quer receber áudio",
     "descricao": "O lead pediu para conversar por áudio.", "chaves": ["sinal:quer_audio"],
     "modelo": _modelo("🎙️ QUER ÁUDIO", extra=_MSG)},
    {"chave": "videochamada", "grupo": "atencao", "icone": "video", "nome": "Pediu videochamada",
     "descricao": "O lead quer falar por chamada de vídeo.", "chaves": ["sinal:quer_videochamada"],
     "modelo": _modelo("📹 PEDIU VIDEOCHAMADA", extra=_MSG)},
    {"chave": "cliente_antigo", "grupo": "atencao", "icone": "contact", "nome": "É cliente do escritório",
     "descricao": "O lead disse que já é cliente do escritório.", "chaves": ["sinal:cliente_antigo"],
     "modelo": _modelo("🗂️ CLIENTE DO ESCRITÓRIO", extra=_MSG)},
    {"chave": "outro_beneficio", "grupo": "atencao", "icone": "shuffle", "nome": "Quer outro benefício",
     "descricao": "O lead pediu um benefício diferente do que está em conversa.", "chaves": ["sinal:outro_beneficio"],
     "modelo": _modelo("🔀 OUTRO BENEFÍCIO", extra=_MSG)},
    {"chave": "muitas_objecoes", "grupo": "atencao", "icone": "messages-square", "nome": "Muitas objeções",
     "descricao": "O lead resistiu várias vezes e a conversa travou.", "chaves": ["sinal:muitas_objecoes"],
     "modelo": _modelo("🧱 MUITAS OBJEÇÕES", extra=_MSG)},
    {"chave": "foto_contrato", "grupo": "atencao", "icone": "image", "nome": "Mandou foto do contrato",
     "descricao": "Na fase do contrato, o lead mandou foto ou arquivo do contrato.", "chaves": ["sinal:foto_contrato"],
     "modelo": _modelo("🖼️ FOTO DO CONTRATO", extra=_MSG)},
    {"chave": "endereco_sem_falar", "grupo": "atencao", "icone": "map-pin-off", "nome": "Não quer passar o endereço",
     "descricao": "Na fase do contrato, o lead recusou ou desviou do endereço.", "chaves": ["sinal:endereco_sem_falar"],
     "modelo": _modelo("📍 ENDEREÇO SEM FALAR", extra=_MSG)},
    {"chave": "contrato_manual", "grupo": "atencao", "icone": "printer", "nome": "Precisa de contrato manual",
     "descricao": "Contrato físico, assinatura por representante ou sem como assinar digital.", "chaves": ["sinal:contrato_manual"],
     "modelo": _modelo("🖨️ CONTRATO MANUAL", extra=_MSG)},
    {"chave": "lead_quente", "grupo": "atencao", "icone": "flame", "nome": "Lead quente",
     "descricao": "A nota do lead chegou a 7 ou mais: vale a equipe olhar agora.", "chaves": ["lead_quente"],
     "modelo": "> `🔥 LEAD QUENTE`\n\n" + _CAB + "\n⭐ *Nota:* {{nota}}\n📌 *Motivos:* {{motivos}}\n" + _RODAPE},
    {"chave": "lead_parado", "grupo": "atencao", "icone": "hourglass", "nome": "Lead parado",
     "descricao": "O lead não respondeu aos follow-ups: hora de alguém retomar o contato.", "chaves": ["lead_parado"],
     "modelo": _modelo("⏳ LEAD PARADO")},
    # ---------------------------------------------------------------- problemas
    {"chave": "dificuldade_assinatura", "grupo": "problema", "icone": "alert-triangle", "nome": "Dificuldade na assinatura",
     "descricao": "O lead não consegue assinar ou abriu o link e não concluiu.", "chaves": ["sinal:dificuldade_assinatura"],
     "modelo": _modelo("⚠️ DIFICULDADE NA ASSINATURA", "✍️ *Link de assinatura:* {{link_assinatura}}", _MSG)},
    {"chave": "ia_falhou", "grupo": "problema", "icone": "bot-off", "nome": "A IA não conseguiu responder",
     "descricao": "Erro na resposta da IA (provedor fora do ar, sem crédito…): alguém precisa responder.", "chaves": ["ia_falhou"],
     "modelo": _modelo("🔴 IA NÃO RESPONDEU", extra=_MSG)},
]
GRUPOS = [("funil", "Etapas do funil"), ("atencao", "Pedidos de atenção"), ("problema", "Problemas")]
POR_CHAVE = {item["chave"]: item for item in CATALOGO}
TODAS_AS_CHAVES = {c for item in CATALOGO for c in item["chaves"]}

MARCADORES = [
    ("nome", "Nome do cliente"), ("telefone", "WhatsApp do cliente"), ("produto", "Produto"), ("etapa", "Etapa do funil"),
    ("data_hora", "Data e hora"), ("valor", "Honorários"), ("link_assinatura", "Link de assinatura"), ("resumo", "Resumo"),
    ("origem", "Origem"), ("link_conversa", "Link da conversa"), ("mensagem_lead", "O que o lead disse"),
    ("nota", "Nota do lead"), ("motivos", "Motivos da nota"),
]
EXEMPLO = {"nome": "Maria Souza", "telefone": "(11) 98888-7777", "produto": "Auxílio-Acidente", "etapa": "Closer",
           "data_hora": "26/11/2026, 14:32", "valor": "30% no final", "link_assinatura": "https://app.zapsign.com.br/verificar/exemplo",
           "resumo": "Acidente de moto em 2023, sequela no joelho, carteira assinada na época.", "origem": "Anúncio no Instagram",
           "link_conversa": "https://app.lawchat.com.br/chat/exemplo", "mensagem_lead": "Dá para ser por videochamada?",
           "nota": "8/10 (quente)", "motivos": "acidente recente, sequela e carteira assinada"}


def _config(escritorio: dict[str, Any] | None) -> dict[str, Any]:
    bruto = (escritorio or {}).get("config")
    return bruto if isinstance(bruto, dict) else json.loads(bruto or "{}")


def _canal_para_tela(c: dict[str, Any]) -> dict[str, Any]:
    pode = notificacoes.canal_envia_aviso(c.get("tipo"), c.get("tipo_helena"))
    return {"id": str(c["id"]), "numero": c.get("numero_normalizado"), "nome": c.get("nome_exibicao"),
            "tipo": c.get("tipo"), "tipo_helena": c.get("tipo_helena"), "ativo": bool(c.get("ativo")),
            "agente": c.get("nome_agente"), "oficial": not pode, "pode_enviar": pode and bool(c.get("numero_normalizado"))}


def _numero_de_envio(canais: list[dict[str, Any]], config: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """(canal que envia, escolhido_pela_conta). Sem escolha: o primeiro canal ativo que pode enviar (o mesmo que o envio usa)."""
    escolhido = str(config.get(notificacoes.CONFIG_NUMERO_ENVIO) or "").strip()
    if escolhido:
        numero = notificacoes.normalizar_numero(escolhido)
        canal = next((c for c in canais if escolhido == c["id"] or (numero and c["numero"] == numero)), None)
        if canal:
            return canal, True
    return next((c for c in canais if c["pode_enviar"] and c["ativo"]), None), False


def _destinatarios(config: dict[str, Any], avisos: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Quem recebe (da conta). Conta que ainda não tem a lista: junta os números que estavam em cada aviso."""
    if isinstance(config.get(CONFIG_DESTINATARIOS), list):
        itens = config[CONFIG_DESTINATARIOS]
    else:
        itens = [d for a in avisos for d in (a.get("destinatarios") or [])]
    return [{"rotulo": d.rotulo, "numero": d.numero} for d in notificacoes.filtrar_destinatarios(itens, None)]


async def _eventos_da_conta(repo: Any, id_escritorio: str) -> set[str]:
    from app.gestao.rotas import _eventos_do_escritorio
    return set(_eventos_do_escritorio(await repo.agentes(id_escritorio)))


def _chaves_para_gravar(item: dict[str, Any], eventos: set[str]) -> list[str]:
    presentes = [c for c in item["chaves"] if c in eventos]
    return presentes or item["chaves"][:1]


@api.get("/avisos")
async def ver_avisos(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    esc = ctx.escritorio()
    import asyncio
    from app.gestao.rotas import _eventos_do_escritorio
    escritorio, canais_brutos, avisos, agentes = await asyncio.gather(
        repo.escritorio(esc), repo.canais(esc), repo.notificacoes(esc), repo.agentes(esc))
    config = _config(escritorio)
    canais = [_canal_para_tela(c) for c in canais_brutos if c.get("numero_normalizado")]
    envio, escolhido = _numero_de_envio(canais, config)
    eventos = set(_eventos_do_escritorio(agentes))
    por_tipo = {a["tipo_evento"]: a for a in avisos}
    grupos = []
    for codigo, titulo in GRUPOS:
        itens = []
        for item in CATALOGO:
            if item["grupo"] != codigo or (item.get("so_se_existir") and not any(c in eventos for c in item["chaves"])):
                continue
            salvos = [por_tipo[c] for c in item["chaves"] if c in por_tipo]
            salvo = next((s for s in salvos if s["habilitada"]), salvos[0] if salvos else None)
            itens.append({"chave": item["chave"], "nome": item["nome"], "descricao": item["descricao"], "icone": item["icone"],
                          "ligado": bool(salvo and salvo["habilitada"]), "configurado": bool(salvo),
                          "nome_interno": (salvo or {}).get("nome") or item["nome"],
                          "modelo": (salvo or {}).get("modelo_mensagem") or item["modelo"], "modelo_padrao": item["modelo"]})
        grupos.append({"chave": codigo, "titulo": titulo, "itens": itens})
    funcao = [a for a in agentes if ((a.get("config") if isinstance(a.get("config"), dict) else json.loads(a.get("config") or "{}"))
                                     .get("funcoes") or {}).get("avisos")]
    return {
        "numero_envio": envio, "numero_escolhido": escolhido, "canais": canais,
        "destinatarios": _destinatarios(config, avisos), "grupos": grupos,
        "antigos": [{"tipo_evento": a["tipo_evento"], "nome": a["nome"], "habilitada": a["habilitada"]}
                    for a in avisos if a["tipo_evento"] not in TODAS_AS_CHAVES],
        "marcadores": [{"chave": k, "rotulo": r} for k, r in MARCADORES], "exemplo": EXEMPLO,
        "agentes": {"total": len(agentes), "com_avisos": [a["nome"] for a in funcao],
                    "sem_avisos": [a["nome"] for a in agentes if a not in funcao]},
    }


class Destinatario(BaseModel):
    rotulo: str = Field(default="", max_length=80)
    numero: str = Field(max_length=40)


class Conta(BaseModel):
    numero_envio: str | None = None                 # id do canal; "" = automático
    destinatarios: list[Destinatario] | None = None


async def _gravar_config(repo: Any, id_escritorio: str, mudancas: dict[str, Any]) -> None:
    await repo.pool.execute(
        "update agentesia_escritorios set config = coalesce(config, '{}'::jsonb) || $2::jsonb where id = $1::uuid",
        id_escritorio, json.dumps(mudancas, ensure_ascii=False))


@api.put("/avisos/conta")
async def salvar_conta(dados: Conta, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Número que envia e quem recebe: valem para todos os avisos da conta."""
    repo = _repo(pedido)
    esc = ctx.escritorio()
    canais = [_canal_para_tela(c) for c in await repo.canais(esc) if c.get("numero_normalizado")]
    config = _config(await repo.escritorio(esc))
    mudancas: dict[str, Any] = {}
    if dados.numero_envio is not None:
        if dados.numero_envio:
            canal = next((c for c in canais if c["id"] == dados.numero_envio), None)
            if not canal:
                raise HTTPException(404, "Número não encontrado nesta conta.")
            if not canal["pode_enviar"]:
                raise HTTPException(400, "Número oficial: o WhatsApp só permite mensagens aprovadas. Escolha um número não oficial.")
        mudancas[notificacoes.CONFIG_NUMERO_ENVIO] = dados.numero_envio or None
    envio, _ = _numero_de_envio(canais, {**config, **mudancas})
    if dados.destinatarios is not None:
        for d in dados.destinatarios:
            if not d.numero.strip():
                continue
            numero = notificacoes.normalizar_numero(d.numero) or ""
            if len(numero) < 12 or len(numero) > 15:
                raise HTTPException(400, f"Número inválido: {d.numero}. Use DDD (e DDI, se não for do Brasil).")
            if envio and numero == envio["numero"]:
                raise HTTPException(400, "O número que envia os avisos não pode estar entre quem recebe.")
        lista = notificacoes.filtrar_destinatarios([d.model_dump() for d in dados.destinatarios], (envio or {}).get("numero"))
        if len(lista) > MAX_DESTINATARIOS:
            raise HTTPException(400, f"No máximo {MAX_DESTINATARIOS} pessoas.")
        mudancas[CONFIG_DESTINATARIOS] = [{"rotulo": d.rotulo, "numero": d.numero} for d in lista]
    if not mudancas:
        return {"ok": True}
    await _gravar_config(repo, esc, mudancas)
    if CONFIG_DESTINATARIOS in mudancas:
        # O envio lê a lista de cada aviso: todos os avisos da conta passam a ter a mesma lista.
        await repo.pool.execute("update agentesia_notificacoes set destinatarios = $2::jsonb where id_escritorio = $1::uuid",
                                esc, json.dumps(mudancas[CONFIG_DESTINATARIOS], ensure_ascii=False))
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=esc, tabela="agentesia_escritorios", id_registro=esc,
                                   acao="alterou", resumo="Avisos no WhatsApp: " + ", ".join(
                                       (["número de envio"] if notificacoes.CONFIG_NUMERO_ENVIO in mudancas else [])
                                       + (["quem recebe"] if CONFIG_DESTINATARIOS in mudancas else [])),
                                   antes={k: config.get(k) for k in mudancas}, depois=mudancas)
    return {"ok": True}


async def _gravar_aviso(repo: Any, ctx: Contexto, item: dict[str, Any], eventos: set[str], destinatarios: list[dict[str, str]],
                        *, ligado: bool | None = None, modelo: str | None = None, nome: str | None = None) -> None:
    for tipo in _chaves_para_gravar(item, eventos) if ligado is not False else item["chaves"]:
        antes = await repo.notificacao(ctx.escritorio(), tipo)
        if not antes and ligado is False:
            continue                                         # desligar o que nunca existiu: nada a gravar
        salvo = await repo.salvar_notificacao(
            ctx.escritorio(), tipo, nome=(nome or (antes or {}).get("nome") or item["nome"]).strip()[:120],
            habilitada=ligado if ligado is not None else bool((antes or {}).get("habilitada", False)),
            modelo_mensagem=(modelo or (antes or {}).get("modelo_mensagem") or item["modelo"]).strip()[:2000],
            destinatarios=destinatarios)
        mudou = not antes or antes["habilitada"] != salvo["habilitada"] or antes["modelo_mensagem"] != salvo["modelo_mensagem"] \
            or antes["nome"] != salvo["nome"]
        if mudou:
            await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_notificacoes",
                                           id_registro=salvo["id"], acao="alterou" if antes else "criou",
                                           resumo=f"Aviso \"{salvo['nome']}\" " + ("ligado" if salvo["habilitada"] else "desligado"),
                                           antes=antes, depois=salvo)


class Ligados(BaseModel):
    ligados: list[str] = Field(default_factory=list)       # chaves do catálogo que ficam ligadas; as outras desligam


@api.put("/avisos/ligados")
async def salvar_ligados(dados: Ligados, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """"Gerenciar avisos": marca quais ficam ligados (o resto desliga). Usa quem recebe e o número da conta."""
    repo = _repo(pedido)
    desconhecidos = [c for c in dados.ligados if c not in POR_CHAVE]
    if desconhecidos:
        raise HTTPException(400, f"Aviso desconhecido: {desconhecidos[0]}.")
    eventos = await _eventos_da_conta(repo, ctx.escritorio())
    config = _config(await repo.escritorio(ctx.escritorio()))
    destinatarios = _destinatarios(config, await repo.notificacoes(ctx.escritorio()))
    for item in CATALOGO:
        await _gravar_aviso(repo, ctx, item, eventos, destinatarios, ligado=item["chave"] in dados.ligados)
    # Avisos fora do catálogo (o genérico "qualquer sinal", tipos que não existem mais): desligam junto, para não
    # duplicar com os da lista. Continuam aparecendo em "antigos" para apagar.
    await repo.pool.execute(
        "update agentesia_notificacoes set habilitada = false where id_escritorio = $1::uuid and habilitada and not (tipo_evento = any($2::text[]))",
        ctx.escritorio(), sorted(TODAS_AS_CHAVES))
    return {"ok": True, "ligados": len(set(dados.ligados))}


class AvisoItem(BaseModel):
    ligado: bool | None = None
    modelo: str | None = Field(default=None, min_length=3, max_length=2000)
    nome: str | None = Field(default=None, min_length=2, max_length=120)


@api.put("/avisos/item/{chave}")
async def salvar_item(chave: str, dados: AvisoItem, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Liga/desliga um aviso ou troca o texto (e o nome interno) dele."""
    item = POR_CHAVE.get(chave)
    if not item:
        raise HTTPException(404, "Aviso desconhecido.")
    repo = _repo(pedido)
    eventos = await _eventos_da_conta(repo, ctx.escritorio())
    config = _config(await repo.escritorio(ctx.escritorio()))
    destinatarios = _destinatarios(config, await repo.notificacoes(ctx.escritorio()))
    await _gravar_aviso(repo, ctx, item, eventos, destinatarios, ligado=dados.ligado, modelo=dados.modelo, nome=dados.nome)
    return {"ok": True}


@api.post("/avisos/item/{chave}/teste")
async def testar_item(chave: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Manda o aviso (texto salvo, dados de exemplo) para quem recebe, pelo número de envio da conta."""
    item = POR_CHAVE.get(chave)
    if not item:
        raise HTTPException(404, "Aviso desconhecido.")
    repo = _repo(pedido)
    esc = ctx.escritorio()
    escritorio, canais_brutos, avisos = await repo.escritorio(esc), await repo.canais(esc), await repo.notificacoes(esc)
    config = _config(escritorio)
    canais = [_canal_para_tela(c) for c in canais_brutos if c.get("numero_normalizado")]
    envio, _ = _numero_de_envio(canais, config)
    if not envio or not envio["pode_enviar"]:
        raise HTTPException(409, "Escolha um número de envio não oficial antes de testar.")
    destinatarios = [d for d in notificacoes.filtrar_destinatarios(_destinatarios(config, avisos), envio["numero"])]
    if not destinatarios:
        raise HTTPException(409, "Cadastre quem recebe os avisos antes de testar.")
    salvo = next((a for a in avisos if a["tipo_evento"] in item["chaves"]), None)
    texto = "🧪 *TESTE*\n" + notificacoes.renderizar_modelo((salvo or {}).get("modelo_mensagem") or item["modelo"], EXEMPLO)
    marca = int(time.time())
    for d in destinatarios:
        await repo.enfileirar_acao(id_escritorio=esc, tipo="notificar", chave_unica=f"teste-aviso:{chave}:{d.numero}:{marca}",
                                   dados={"de": envio["numero"], "para": d.numero, "rotulo": d.rotulo, "texto": texto,
                                          "tipo_canal": envio["tipo"], "evento": item["chaves"][0]})
    return {"texto": texto, "enfileirados": len(destinatarios)}
