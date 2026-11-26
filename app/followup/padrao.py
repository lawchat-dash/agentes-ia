"""Follow-up padrão do produto: o que a ativação copia para o agente, o resumo da cadência e o "ligar com o padrão".

Decisão do dono (25/11): o follow-up vem LIGADO ao ativar um produto (opt-out). A cadência e os prompts por etapa
vêm do produto da biblioteca (agentesia_biblioteca_produtos.padrao_followup, editado no admin › Produtos › Follow-up):

    {"cadence": [{"order": 1, "delay": "10m"}, {"order": 2, "delay": "1h"}, ...]   # ou [1, 5, 24] (horas)
     "restart_on_reply": true,
     "agentes": {"sdr": {"nome_agente": "...", "prompt": "...", "habilitado_padrao": true, "ordem": 0}, ...}}

Cada "delay" conta a partir da última mensagem da IA (não é cumulativo), igual a regras.Passo.apos_horas.
Regras da OAB e da Meta (a partir de 25/11/2026, só para quem ativa ou liga com o padrão daqui em diante): no máximo
4 toques (os 4 primeiros da cadência do produto; sem cadência no produto, 1 h, 24 h, 72 h e 7 dias), no máximo 2 para
quem nunca respondeu à IA e o penúltimo toque oferece parar (config.followup.limites, ver regras.py).
Etapas do CRM do catálogo -> etapas do agente: sdr -> sdr e periododegraca (o Weaver espelhava, migração 0126),
closer -> closer, contrato -> contratos, assinatura -> assinatura. Desqualificado e contrato assinado nunca recebem.
Nada aqui liga follow-up sozinho: quem chama é a ativação, o botão "Ligar com o padrão", o admin ou o script.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.followup import regras

ETAPAS_DO_CATALOGO = {"sdr": ("sdr", "periododegraca"), "closer": ("closer",), "contrato": ("contratos",),
                      "contratos": ("contratos",), "assinatura": ("assinatura",)}

POR_QUE_LIGAR = ("Muitos leads param de responder no meio da conversa e esfriam. O follow-up manda um lembrete curto, "
                 "no tom do agente, e para sozinho quando o lead responde ou alguém da equipe assume.")
AVISO_DESLIGADO = "Follow-up desligado — leads que param de responder não recebem lembrete"
AVISO_OFICIAL = ("Número da API oficial: depois de 24 h sem resposta do lead, o WhatsApp só aceita modelo aprovado. "
                 "Escolha o modelo em Agente › Follow-up; sem ele, as tentativas depois de 24 h não saem.")


def _obj(valor: Any) -> dict[str, Any]:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor or "{}")
        except json.JSONDecodeError:
            return {}
    return dict(valor) if isinstance(valor, dict) else {}


def horas_do_atraso(valor: Any) -> float | None:
    """'10m', '1h', '2d', '1sem', 24 (horas) ou {'delay': '1h'} -> horas. None se não der para ler."""
    if isinstance(valor, dict):
        valor = valor.get("delay", valor.get("apos_horas"))
    if isinstance(valor, bool) or valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if valor > 0 else None
    achado = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([a-z]*)", str(valor).strip().lower())
    if not achado:
        return None
    n = float(achado.group(1).replace(",", "."))
    unidade = achado.group(2)
    fator = ({"m": 1 / 60, "min": 1 / 60, "mins": 1 / 60, "minuto": 1 / 60, "minutos": 1 / 60, "": 1, "h": 1, "hs": 1, "hr": 1,
              "hrs": 1, "hora": 1, "horas": 1, "d": 24, "dia": 24, "dias": 24, "sem": 168, "semana": 168, "semanas": 168}
             .get(unidade))
    return n * fator if fator and n > 0 else None


def cadencia_do_produto(padrao_followup: Any) -> list[float]:
    """Horas de cada tentativa, em ordem e sem repetir. Vazio = o produto não definiu (vale a cadência do sistema)."""
    bruto = _obj(padrao_followup).get("cadence")
    itens = bruto if isinstance(bruto, list) else []
    ordenados = sorted(itens, key=lambda s: (s.get("order") or 0) if isinstance(s, dict) else 0)
    horas: list[float] = []
    for item in ordenados:
        if isinstance(item, dict) and item.get("enabled") is False:
            continue
        h = horas_do_atraso(item)
        if h is not None and round(h, 4) not in {round(x, 4) for x in horas}:
            horas.append(round(h, 4))
    return sorted(horas)[:12]


def horas_escolhidas(bruto: Any) -> list[float]:
    """Cadência escolhida na ativação: 1 a 4 tempos (15 min a 30 dias), em ordem crescente e sem repetir.
    Lista inválida → ValueError com a mensagem para a tela."""
    if not isinstance(bruto, list) or not 1 <= len(bruto) <= regras.MAX_TOQUES_PADRAO:
        raise ValueError(f"Escolha de 1 a {regras.MAX_TOQUES_PADRAO} tentativas de follow-up.")
    try:
        horas = [round(float(h), 4) for h in bruto]
    except (TypeError, ValueError):
        raise ValueError("Tempo de follow-up inválido.") from None
    if any(h < 0.25 or h > 720 for h in horas):
        raise ValueError("Cada tentativa precisa ficar entre 15 minutos e 30 dias.")
    if any(b <= a for a, b in zip(horas, horas[1:])):
        raise ValueError("Cada tentativa precisa vir depois da anterior.")
    return horas


def config_do_produto(catalogo: dict[str, Any] | None, *, ativo: bool, horas: list[float] | None = None) -> dict[str, Any]:
    """config.followup do agente a partir do padrão do produto (já validada por regras.validar). `horas`: a cadência
    escolhida na ativação (já conferida por horas_escolhidas); sem ela vale a do produto/sistema."""
    padrao = _obj((catalogo or {}).get("padrao_followup"))
    horas = list(horas) if horas else (cadencia_do_produto(padrao) or list(regras.CADENCIA_PADRAO))[:regras.MAX_TOQUES_PADRAO]
    etapas: list[str] = []
    por_etapa: dict[str, str] = {}
    for estagio, item in sorted((_obj(padrao.get("agentes")) or {}).items(), key=lambda kv: (_obj(kv[1]).get("ordem") or 0)):
        item = _obj(item)
        for codigo in ETAPAS_DO_CATALOGO.get(str(estagio), ()):
            if item.get("habilitado_padrao") is not False and item.get("habilitado_padrao") not in ("false", "False", 0):
                etapas.append(codigo)
            if str(item.get("prompt") or "").strip():
                por_etapa[codigo] = str(item["prompt"]).strip()
    # Nenhuma etapa marcada no produto = todas as de conversa (regras.Config.vale_para com etapas vazias).
    return regras.validar({
        "ativo": ativo, "etapas": list(dict.fromkeys(etapas)), "por_etapa": por_etapa,
        "passos": [{"apos_horas": h, "modo": "ia", "instrucao": "", "texto": ""} for h in horas],
        "desistir": {"ativo": False},
        "limites": dict(regras.LIMITES_PADRAO),
    })


def rotulo_tempo(horas: float) -> str:
    minutos = round(horas * 60)
    if minutos < 60:
        return f"{minutos} min"
    if minutos % 60:
        return f"{minutos // 60} h {minutos % 60} min"
    h = minutos // 60
    if h <= 72 or h % 24:
        return f"{h} h"
    return f"{h // 24} dias"


def resumo(config_followup: dict[str, Any] | None) -> list[str]:
    return [rotulo_tempo(p.apos_horas) for p in regras.Config.de(config_followup).passos]


def situacao(config_agente: Any) -> dict[str, Any]:
    """O que o painel mostra do follow-up do agente: ligado? configurado? a cadência resumida."""
    bruto = _obj(config_agente).get("followup")
    configurado = isinstance(bruto, dict)
    return {"ligado": bool(configurado and bruto.get("ativo")), "configurado": configurado,
            "passos": len(regras.Config.de(bruto).passos), "resumo": resumo(bruto)}


def previa_do_produto(catalogo: dict[str, Any] | None) -> dict[str, Any]:
    """Para a etapa "Follow-up" da ativação: a cadência que vai ser copiada e o texto de por que deixar ligado."""
    config = config_do_produto(catalogo, ativo=True)
    return {"resumo": resumo(config), "passos": [p["apos_horas"] for p in config["passos"]], "etapas": config["etapas"],
            "do_produto": bool(cadencia_do_produto((catalogo or {}).get("padrao_followup"))),
            "por_que": POR_QUE_LIGAR, "aviso_oficial": AVISO_OFICIAL}


# ------------------------------------------------------------------ banco
_PANORAMA = """
    select p.id::text as id_ativado, p.nome, p.status, p.id_escritorio::text as id_escritorio, e.nome as escritorio,
           p.id_agente::text as id_agente, a.config as config_agente, a.situacao as situacao_agente,
           a.id_canal is null as sem_numero, c.tipo as tipo_canal, b.nome as produto_catalogo, b.padrao_followup
    from agentesia_produtos_ativados p
    join agentesia_escritorios e on e.id = p.id_escritorio
    join agentesia_agentes a on a.id = p.id_agente
    left join agentesia_canais c on c.id = a.id_canal
    left join agentesia_biblioteca_produtos b on b.id = p.id_produto_biblioteca
    where p.excluido_em is null"""


def _linha_panorama(r: Any) -> dict[str, Any]:
    linha = dict(r)
    config = _obj(linha.pop("config_agente"))
    linha.pop("padrao_followup", None)
    return {**linha, "followup": situacao(config), "modelo_oficial": bool((_obj(config.get("followup")).get("modelo_oficial") or {}).get("id_modelo"))}


async def panorama(pool: Any, id_escritorio: str | None = None) -> list[dict[str, Any]]:
    """Todos os produtos ativados (com agente, fora da lixeira) e o follow-up de cada um. Sem escritório = todos."""
    sql = _PANORAMA + (" and p.id_escritorio = $1::uuid" if id_escritorio else "") + " order by e.nome, p.nome"
    return [_linha_panorama(r) for r in await pool.fetch(sql, *([id_escritorio] if id_escritorio else []))]


async def desligados_do_escritorio(pool: Any, id_escritorio: str) -> list[dict[str, Any]]:
    """Produtos ATIVOS do escritório com follow-up desligado (o aviso do Início)."""
    return [{"id_ativado": p["id_ativado"], "nome": p["nome"]} for p in await panorama(pool, id_escritorio)
            if p["status"] == "ativo" and not p["sem_numero"] and not p["followup"]["ligado"]]


async def registrar(pool: Any, *, id_usuario: str | None, id_escritorio: str | None, id_agente: str, resumo_txt: str,
                    antes: Any, depois: Any) -> None:
    await pool.execute(
        """insert into agentesia_alteracoes (id_usuario, id_escritorio, tabela, id_registro, acao, resumo, antes, depois)
           values ($1::uuid, $2::uuid, 'agentesia_agentes', $3::uuid, 'alterou', $4, $5::jsonb, $6::jsonb)""",
        id_usuario, id_escritorio, id_agente, resumo_txt,
        None if antes is None else json.dumps(antes, ensure_ascii=False), json.dumps(depois, ensure_ascii=False))


async def ligar_com_padrao(pool: Any, id_ativado: str, *, id_usuario: str | None, id_escritorio: str | None = None,
                           origem: str = "painel") -> dict[str, Any] | None:
    """Liga o follow-up do produto com a cadência e os prompts padrão do produto da biblioteca e registra em
    agentesia_alteracoes. Guarda o modelo aprovado e o horário que o agente já tinha (são do número/escritório).
    id_escritorio limita ao escritório (cliente); None = qualquer um (admin/script). None se o produto não tem agente."""
    filtro = " and p.id_escritorio = $2::uuid" if id_escritorio else ""
    linha = await pool.fetchrow(
        f"""select p.id_agente::text as id_agente, p.id_escritorio::text as id_escritorio, p.nome, a.config, c.tipo as tipo_canal,
                   b.padrao_followup
            from agentesia_produtos_ativados p join agentesia_agentes a on a.id = p.id_agente
            left join agentesia_canais c on c.id = a.id_canal
            left join agentesia_biblioteca_produtos b on b.id = p.id_produto_biblioteca
            where p.id = $1::uuid and p.excluido_em is null{filtro}""", id_ativado, *([id_escritorio] if id_escritorio else []))
    if not linha:
        return None
    config = _obj(linha["config"])
    antes = config.get("followup")
    novo = config_do_produto({"padrao_followup": linha["padrao_followup"]}, ativo=True)
    anterior = _obj(antes)
    if anterior.get("modelo_oficial"):
        novo["modelo_oficial"] = anterior["modelo_oficial"]
    if anterior.get("horario"):
        novo["horario"] = anterior["horario"]
    if anterior.get("modelo"):
        novo["modelo"] = anterior["modelo"]
    # Só a chave followup muda (jsonb_set): não pisa numa alteração de outra parte da config feita ao mesmo tempo.
    await pool.execute("update agentesia_agentes set config = jsonb_set(coalesce(config, '{}'::jsonb), '{followup}', $2::jsonb) where id = $1::uuid",
                       linha["id_agente"], json.dumps(novo, ensure_ascii=False))
    texto = ", ".join(resumo(novo))
    await registrar(pool, id_usuario=id_usuario, id_escritorio=linha["id_escritorio"], id_agente=linha["id_agente"],
                    resumo_txt=f"Follow-up de {linha['nome']} ligado com o padrão do produto ({origem}): {texto}",
                    antes=antes, depois=novo)
    aviso = AVISO_OFICIAL if linha["tipo_canal"] == "oficial" and not (novo.get("modelo_oficial") or {}).get("id_modelo") else None
    return {"id_ativado": id_ativado, "id_agente": linha["id_agente"], "nome": linha["nome"], "followup": situacao({"followup": novo}),
            "aviso": aviso}
