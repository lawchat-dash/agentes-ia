"""Cache do provedor: duas chamadas seguidas do mesmo lead/agente começam pelo mesmo texto, byte a byte.

A OpenAI só cobra o preço de cache (0,10 x 0,40 por milhão no gpt-4.1-mini) do PREFIXO idêntico, a partir de 1024
tokens. Então o que é fixo do agente e do papel (roteiro, regras, base, formato, esquema) vem primeiro e o que muda
(hora, fatos do lead, contas da calculadora, mensagens novas, tentativa do follow-up) vem por último.

Sem API: o ModeloFalso guarda os pedidos e o teste mede o prefixo comum (sistema + conteúdo, ~4 caracteres por token,
a mesma conta de app/avaliacao/custo.py). Metas: etapa >= 85%, extrator >= 80%, follow-up e decisor >= 70%.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.cerebro import catalogo, turno
from app.cerebro import produto as produtos
from app.followup import agente as agente_fu, regras
from app.modelo import ModeloFalso, chave_de_cache

BRASILIA = timezone(timedelta(hours=-3))
SNAPSHOT = json.loads((Path(__file__).parents[1] / "avaliacao/agentes/catalogo_referencia.json").read_text(encoding="utf-8"))
SEM_INTENCAO = {"pediu_humano": False, "pediu_para_parar": False, "engano": False, "diz_que_assinou": False, "pediu_link": False}

CONVERSA = [
    ("lead", "oi vi o anuncio do auxilio acidente"),
    ("você", "Olá! Aqui é a Júlia, do escritório. Me conta, como foi o acidente?"),
    ("lead", "sofri um acidente de moto em março de 2024 indo pro serviço"),
    ("você", "Entendi, sinto muito pelo acidente. Na época você trabalhava de carteira assinada?"),
    ("lead", "eu trabalhava registrado numa metalúrgica, fiquei 4 meses afastado pelo INSS"),
    ("você", "Certo, obrigada por explicar. E ficou com alguma sequela ou limitação depois do acidente?"),
]


def _prefixo(a: dict, b: dict) -> float:
    """Fração do pedido `b` que é igual, desde o começo, ao pedido `a` (sistema e depois conteúdo, como vão à API)."""
    texto_a, texto_b = a["sistema"] + "\n" + a["conteudo"], b["sistema"] + "\n" + b["conteudo"]
    i = 0
    while i < min(len(texto_a), len(texto_b)) and texto_a[i] == texto_b[i]:
        i += 1
    return i / len(texto_b)


def _historico(pares):
    return [{"autor": autor, "texto": texto} for autor, texto in pares]


def _entrada(historico, novas, fatos, agora, fatos_sistema):
    agente = SNAPSHOT["agente"]
    return turno.Entrada(
        escritorio=SNAPSHOT["escritorio"]["nome"], agente=agente["nome"], etapa="sdr", novas=novas, fatos=fatos,
        historico=historico, produto=produtos.carregar("catalogo", agente["config"]),
        instrucoes={e["codigo"]: e.get("instrucao") or "" for e in agente["etapas"]},
        honorarios=agente["config"].get("honorarios"), fatos_sistema=fatos_sistema, agora=agora)


async def _dois_turnos():
    """Turno 1 e turno 2 do mesmo lead, com 7 minutos entre eles, um fato novo e a calculadora mudando."""
    extrator = [
        {"fatos": [{"chave": "sequela", "valor": "sim", "trecho": "fiquei com o joelho ruim"}], "sinais": [],
         "intencoes": SEM_INTENCAO},
        {"fatos": [{"chave": "aposentado", "valor": "nao", "trecho": "não sou aposentado"}], "sinais": [],
         "intencoes": SEM_INTENCAO},
    ]
    etapa = [{"mensagens": [{"texto": "Imagino como isso atrapalha o dia a dia. Você já é aposentado?"}],
              "transferir_para": "", "ferramenta": "", "notificacao": ""},
             {"mensagens": [{"texto": "Combinado. E já tem algum advogado cuidando deste caso?"}],
              "transferir_para": "", "ferramenta": "", "notificacao": ""}]
    modelo = ModeloFalso({"extrator": extrator, "etapa": etapa})
    sistema_do_lead = {"nome no WhatsApp": "Carlos (pode não ser o nome completo)", "telefone": "(11) 99000-0001",
                       "primeiro contato": "24/11/2026 14:00", "contrato": "não gerado"}
    fatos = {"acidente_ano": 2024, "acidente_mes": 3, "vinculo_na_data": "clt"}
    agora = datetime(2026, 11, 24, 14, 30, tzinfo=BRASILIA)
    novas1 = ["fiquei com o joelho ruim, não consigo mais agachar direito"]
    await turno.processar(modelo, _entrada(_historico(CONVERSA), novas1, fatos, agora, sistema_do_lead))
    historico2 = _historico(CONVERSA + [("lead", novas1[0]),
                                        ("você", "Imagino como isso atrapalha o dia a dia. Você já é aposentado?")])
    await turno.processar(modelo, _entrada(historico2, ["não sou aposentado"], {**fatos, "sequela": "sim"},
                                           agora + timedelta(minutes=7),
                                           {**sistema_do_lead, "contrato": "já foi gerado (versão 1) e AINDA NÃO foi assinado."}))
    por_papel = {}
    for pedido in modelo.pedidos:
        por_papel.setdefault(pedido["papel"], []).append(pedido)
    return por_papel


async def test_etapa_e_extrator_repetem_o_prefixo_entre_turnos_do_mesmo_lead():
    por_papel = await _dois_turnos()
    etapa1, etapa2 = por_papel["etapa"]
    extrator1, extrator2 = por_papel["extrator"]
    assert etapa1["sistema"] != etapa2["sistema"]                        # os FATOS DO SISTEMA mudaram (contrato) ...
    assert _prefixo(etapa1, etapa2) >= 0.85, _prefixo(etapa1, etapa2)    # ... e mesmo assim o prefixo fica
    assert _prefixo(extrator1, extrator2) >= 0.80, _prefixo(extrator1, extrator2)
    # O sistema do extrator é do produto: idêntico entre turnos (e entre leads).
    assert extrator1["sistema"] == extrator2["sistema"]


async def test_o_que_muda_vem_depois_do_que_e_fixo():
    por_papel = await _dois_turnos()
    etapa = por_papel["etapa"][0]
    sistema, conteudo = etapa["sistema"], etapa["conteudo"]
    # Fatos do lead no fim do sistema, depois das regras do motor e do formato.
    assert sistema.index("# FATOS DO SISTEMA") > sistema.index("# REGRAS DO ATENDIMENTO")
    assert sistema.rstrip().endswith("(calculado pelo sistema): 32 meses")       # a conta da calculadora é a última
    assert "Hoje é" not in sistema and "Carlos" not in sistema.split("# FATOS DO SISTEMA")[0]
    # Conteúdo: a conversa (que só cresce no fim) primeiro; a hora, a base e as novas depois dela.
    assert conteudo.startswith("CONVERSA ATÉ AQUI (mais antiga primeiro):\nlead: oi vi o anuncio")
    assert conteudo.index("CONVERSA ATÉ AQUI") < conteudo.index("Hoje é 24/11/2026") < conteudo.index("MENSAGENS NOVAS")
    extrator = por_papel["extrator"][0]["conteudo"]
    assert extrator.startswith("CONVERSA ANTERIOR (mais antiga primeiro):\n[lead] oi vi o anuncio")
    assert extrator.index("CONVERSA ANTERIOR") < extrator.index("Hoje é") < extrator.index("FATOS CONHECIDOS") \
        < extrator.index("MENSAGENS NOVAS")


async def test_dois_leads_do_mesmo_agente_dividem_o_sistema_ate_os_fatos_do_lead():
    """Entre leads diferentes só o fim do sistema (FATOS DO SISTEMA) muda: o roteiro e as regras entram no cache."""
    agente = SNAPSHOT["agente"]
    pedidos = []
    for nome, telefone in (("Carlos", "(11) 99000-0001"), ("Ana", "(21) 98888-7777")):
        modelo = ModeloFalso({"extrator": {"fatos": [], "sinais": [], "intencoes": SEM_INTENCAO},
                              "etapa": {"mensagens": [{"texto": "Me conta, como foi o acidente?"}], "transferir_para": "",
                                        "ferramenta": "", "notificacao": ""}})
        await turno.processar(modelo, _entrada([], ["oi"], {}, datetime(2026, 11, 24, 14, 30, tzinfo=BRASILIA),
                                               {"nome no WhatsApp": nome, "telefone": telefone}))
        pedidos.append(modelo.pedidos[1]["sistema"])
    fixo = pedidos[0].split("# FATOS DO SISTEMA")[0]
    assert pedidos[1].startswith(fixo) and len(fixo) / len(pedidos[1]) >= 0.95
    assert agente["nome"] in fixo


def _lead_do_followup():
    agente = SNAPSHOT["agente"]
    sdr = next(e for e in agente["etapas"] if e["codigo"] == "sdr")
    return {"nome": "Carlos Souza", "nome_agente": agente["nome"], "escritorio": SNAPSHOT["escritorio"]["nome"],
            "etapa": "sdr", "produto": "catalogo", "instrucao_etapa": sdr["instrucao"], "config_agente": agente["config"],
            "config_escritorio": {}}


def test_followup_e_decisor_repetem_o_prefixo_entre_tentativas():
    config = regras.Config.de({"prompt": "Retome com gentileza, sem pressão. " * 20,
                               "por_etapa": {"sdr": "Na qualificação, retome pela última pergunta feita."}})
    lead = _lead_do_followup()
    historico = _historico(CONVERSA)
    decisor = [{"sistema": agente_fu.sistema_do_decisor(lead, config),
                "conteudo": agente_fu.conteudo_do_decisor(historico + extra, config, passo, 3, agora)}
               for passo, extra, agora in ((0, [], "Hoje é 24/11/2026 15:30"),
                                           (1, [{"autor": "ia", "texto": "Oi, Carlos! Conseguiu ver?"}], "Hoje é 25/11/2026 09:00"))]
    assert decisor[0]["sistema"] == decisor[1]["sistema"]                 # hora e tentativa saíram do sistema
    assert _prefixo(*decisor) >= 0.70, _prefixo(*decisor)
    escrita = [{"sistema": agente_fu.sistema_do_agente_do_lead(lead, config, passo, 3, orientacao),
                "conteudo": "Conversa até aqui:\n" + agente_fu.conversa_em_texto(historico)}
               for passo, orientacao in ((0, "retome pela sequela"), (1, "retome pela sequela, com leveza"))]
    assert _prefixo(*escrita) >= 0.70, _prefixo(*escrita)


def test_chave_de_cache_estavel_por_agente_e_papel():
    sistema = catalogo.REGRAS_CONVERSA * 5
    a = chave_de_cache("etapa", "gpt-4.1-mini", sistema + "\n# FATOS DO SISTEMA\n- telefone: 1")
    b = chave_de_cache("etapa", "gpt-4.1-mini", sistema + "\n# FATOS DO SISTEMA\n- telefone: 2")
    assert a == b and len(a) <= 64                                     # o que muda por lead fica fora da chave
    assert chave_de_cache("extrator", "gpt-4.1-mini", sistema) != a    # outro papel, outra chave
    assert chave_de_cache("etapa", "gpt-4.1-mini", "Outro roteiro\n" + sistema) != a


async def test_modelo_openai_manda_a_chave_de_cache():
    from types import SimpleNamespace

    from app.modelo import ModeloOpenAI

    recebidos = []

    class Completions:
        async def create(self, **parametros):
            recebidos.append(parametros)
            uso = SimpleNamespace(prompt_tokens=2000, completion_tokens=10,
                                  prompt_tokens_details=SimpleNamespace(cached_tokens=1536))
            escolha = SimpleNamespace(message=SimpleNamespace(content='{"ok": true}', refusal=None), finish_reason="stop")
            return SimpleNamespace(usage=uso, model="gpt-4.1-mini", choices=[escolha])

    cliente = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    resultado = await ModeloOpenAI(cliente).gerar(papel="etapa", sistema="roteiro fixo", conteudo="oi", esquema={},
                                                  modelo="gpt-4.1-mini")
    assert recebidos[0]["prompt_cache_key"] == chave_de_cache("etapa", "gpt-4.1-mini", "roteiro fixo")
    assert resultado.chamadas[0].tokens_cache == 1536 and resultado.chamadas[0].tokens_entrada == 464
