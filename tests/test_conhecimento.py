"""Base de conhecimento por documento: trechos escolhidos pela conversa e o caminho até o prompt."""

from app import conhecimento
from app.cerebro.agente import montar_conhecimento
from tests.test_pipeline import SIMPLES, montar, webhook

TABELA = ("Tabela de honorários do escritório. " * 3 + "\n\n") + "\n\n".join(
    f"Seção {i}: assunto genérico número {i} sobre procedimentos internos e rotinas administrativas." * 4 for i in range(30)
) + "\n\nPerícia médica do INSS: leve exames, laudos e documento com foto. A perícia costuma durar 20 minutos.\n\n" + "\n\n".join(
    f"Anexo {i}: texto de preenchimento sem relação nenhuma com o caso do cliente." * 4 for i in range(30))


def test_divide_em_trechos_com_sobra():
    trechos = conhecimento.dividir(TABELA)
    assert len(trechos) > 5 and all(len(t) <= conhecimento.TAMANHO_TRECHO for t in trechos)
    assert conhecimento.dividir("curto") == ["curto"] and conhecimento.dividir("   ") == []


def test_escolhe_o_trecho_que_combina_com_a_pergunta():
    escolhidos = conhecimento.escolher([("Regras.pdf", TABELA)], "como funciona a perícia do INSS? preciso levar laudo?", teto=4000)
    assert escolhidos and any("Perícia médica do INSS" in t.texto for t in escolhidos)
    assert sum(len(t.texto) for t in escolhidos) <= 4000
    # Documento pequeno entra inteiro; conversa sem palavra útil não puxa trecho de documento grande.
    assert conhecimento.escolher([("Curto.txt", "Atendemos de segunda a sexta.")], "oi") == [conhecimento.Trecho("Curto.txt", "Atendemos de segunda a sexta.")]
    assert conhecimento.escolher([("Regras.pdf", TABELA)], "oi, bom dia") == []
    bloco = montar_conhecimento({"documentos": escolhidos})
    assert bloco.startswith("DOCUMENTOS DO ESCRITÓRIO") and "[Regras.pdf]" in bloco


async def test_documento_entra_no_prompt_do_turno():
    atendimento, repo, helena = montar(SIMPLES)
    repo.__dict__.setdefault("documentos", {})["ag-1"] = [("Horários.txt", "O escritório atende de segunda a sexta, das 8h às 18h.")]
    await atendimento.receber(webhook("qual o horário de vocês?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    sistema = next(p["sistema"] for p in atendimento.modelo.pedidos if p["papel"] == "etapa")
    assert "[Horários.txt]" in sistema and "das 8h às 18h" in sistema
