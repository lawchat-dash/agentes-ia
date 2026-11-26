"""Cenário sc03 do Sousa e Costa (avaliacao/cenarios_sousa_costa/sc03_esposa_pelo_marido.json).

Inspirado no CHAT 3 do escritório, com fatos, falas e dados 100% inventados (só o jeito da lead foi aproveitado): a
esposa fala pelo marido (dois acidentes, trajeto, mês incerto), pergunta da mãe aposentada por invalidez, adia os dados e volta, e na coleta corrige nome, e-mail, cidade e
bairro antes do ZapSign; depois diz que assinou e pergunta se demora o contato. Aqui só se prova, de graça, que o
cenário carrega, que o gabarito segue o prompt do escritório (oráculo genérico desligado), que o 'proibido' pega as
invenções vistas no chat sem barrar a resposta certa e que o cartão do lead cobre o fluxo do Sousa e Costa até o
contrato assinado (modelo roteirizado). A qualidade do prompt é o modo real (pago), rodado pelo orquestrador.
"""

import re

from app.avaliacao import cenario, falso, simulador
from app.avaliacao.falso import passo
from app.contrato import dados as cdados

PASTA = cenario.PASTA / "cenarios_sousa_costa"
ARQUIVO = PASTA / "sc03_esposa_pelo_marido.json"
MIDIA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/"
NOME_CERTO = "Josimar Aparecido dos Santos Moura"
EMAIL_NOVO = "josimar.moura@exemplo.invalid"


def caso():
    return cenario.expandir(cenario.carregar(ARQUIVO))[0]


def test_sc03_carrega_com_o_gabarito_do_prompt_do_escritorio():
    cen = cenario.carregar(ARQUIVO)
    assert cen.id == "sc03_esposa_pelo_marido" and cen.agente == "avaliacao/agentes/sousa_costa.json"
    assert [c.id for c in cenario.casos(["sc03"], pasta=PASTA)] == [cen.id]
    snap = cen.carregar_agente()
    assert snap["escritorio"]["nome"] == "Sousa e Costa Advogados" and snap["agente"]["nome"] == "Ana"
    # Oráculo genérico desligado (destino fixo): o SDR do escritório manda para o closer no "CLT = sim", sem perguntar
    # aposentado/advogado; e a incerteza só do mês não abre o período de graça (vínculo certo).
    assert cen.esperado.destino_qualificacao == "closer"
    destino = cen.destino_esperado()
    assert destino.destino == "closer" and not destino.passa_periodo
    assert cen.esperado.trajetoria == ["sdr", "closer", "contratos", "assinatura", "contrato_assinado"]
    assert cen.esperado.estado_final == "encerrado" and cen.esperado.ferramentas == {"zapsign": 1}
    assert cen.esperado.transferencias_com_frase == ["closer", "contratos"]
    assert cen.esperado.fatos["email"] == EMAIL_NOVO and cen.esperado.fatos["nome_completo"] == NOME_CERTO
    assert cen.lead.tipo == "cartao" and cen.lead.ao_receber_link == "assina" and cen.ferramentas.zapsign.assina
    aceites = [a for a in cen.lead.assuntos if a.aceite]
    assert len(aceites) == 2                                  # a volta depois do adiamento e o "pode sim"


def test_sc03_dados_sao_sinteticos_e_o_cep_resolve():
    cen = cenario.carregar(ARQUIVO)
    v = cen.lead.verdade
    assert cdados.cpf_valido(v["cpf"])
    assert v["email"].endswith("@exemplo.invalid") and v["email_antigo"].endswith("@exemplo.invalid")
    assert re.fullmatch(r"55\d{2}99000\d{4}", cen.lead.telefone)
    assert re.sub(r"\D", "", v["telefone_contrato"]).startswith("3399000")
    cep = re.sub(r"\D", "", v["cep"])
    assert cen.ferramentas.cep[cep] == {"logradouro": v["endereco"], "bairro": v["bairro"], "cidade": v["cidade"],
                                        "uf": v["uf"]}
    falas = " ".join(a.responde.texto_corrido() for a in cen.lead.assuntos)
    falas += " " + " ".join(g.fala.texto_corrido() for g in cen.lead.gatilhos if g.fala)
    for trecho in (v["nome_digitado_errado"], NOME_CERTO, re.sub(r"\D", "", v["cpf"]), v["email_antigo"], EMAIL_NOVO,
                   "Minas gerais", "fica onde?", "ligamento", "aposentada por invalidez", "amanhã ou depois"):
        assert trecho in falas, trecho
    assert any(a.responde.tipo == "audio" for a in cen.lead.assuntos)


def test_sc03_proibido_pega_as_invencoes_do_chat_e_deixa_passar_o_certo():
    proibido = caso().esperado.proibido

    def barra(texto):
        return any(re.search(r, texto) for r in proibido)

    for errado in ("Que ótimo! Você conseguiu enviar a foto ou o arquivo do contrato para a nossa equipe?",
                   "Geralmente nossa equipe entra em contato com o INSS em até 5 dias úteis.",
                   "Em 48 horas a equipe te chama.",
                   "Sim, o rompimento do ligamento do joelho será incluído como sequela no seu caso.",
                   "O ligamento do joelho entra sim no pedido.",
                   "Obrigado! Incluiremos essa informação no contrato.",
                   "Entendo, mas para garantir que o processo ande rápido, precisamos iniciar a formalização agora.",
                   "Sim, ela também tem direito ao auxílio-acidente.",
                   "Ela pode receber os dois benefícios juntos.",
                   "Para valer, você precisa imprimir o contrato e assinar à mão.",
                   "Depois é só reconhecer firma no cartório."):
        assert barra(errado), errado
    for certo in ("Perfeito! Estamos gerando o seu contrato.\n\nEm alguns segundos você vai receber o link para assinatura!",
                  "Não precisa imprimir nada nem mandar foto do contrato: a assinatura é digital, pelo link.",
                  "Quem já é aposentado por invalidez não pode receber o auxílio-acidente junto, pela regra do INSS.",
                  "Sobre o ligamento, vou deixar anotado para o advogado avaliar se ele pode entrar no pedido.",
                  "Sem problema! Quando estiver com os documentos dele, é só me chamar por aqui.",
                  "Tranquilo. A formalização leva poucos minutos e você resolve pelo celular. Quer aproveitar e já começar?",
                  "• Pode ter retroativo de até 5 anos se recebeu auxílio-doença.",
                  "Atendimento simples e 100% online.",
                  "Anotei o e-mail novo, ele vai no contrato.",
                  "A equipe vai te chamar por aqui para os próximos passos."):
        assert not barra(certo), certo


def _extrator(sistema, conteudo):
    """O extrator de regras do roteirizado mais o que este lead manda (o extrator de verdade tem de pegar): nome com
    erro e a correção, RG, estado civil, endereço numa mensagem só, complemento, o e-mail NOVO, telefone, profissão e
    as correções de cidade e bairro da confirmação."""
    dados = falso.extrator_de_regras(sistema, conteudo)
    texto, _ultima = falso._secoes(conteudo)
    fatos = [f for f in dados["fatos"] if f["chave"] not in ("email", "numero_casa")]

    def fato(chave, valor):
        fatos.append({"chave": chave, "valor": valor, "trecho": texto})

    if m := re.search(r"Josimar Aparecido dos Sant\w+ M\w+", texto):
        fato("nome_completo", m.group(0))
    if m := re.search(r"(?i)mg-[\d.]+", texto):
        fato("rg", m.group(0))
    if re.fullmatch(r"(?i)casad[oa]", texto.strip()):
        fato("estado_civil", "casado")
    if m := re.search(r"(Rua [A-Za-zÀ-ú ]+?) (\d+) (Vila Esperança)", texto):
        fato("endereco", m.group(1))
        fato("numero_casa", m.group(2))
        fato("bairro", m.group(3))
    if re.search(r"(?i)minas gerais", texto) and not re.search(r"(?i)é o estado", texto):
        fato("uf", "MG")
    if texto.strip().lower() == "casa":
        fato("complemento", "casa")
    if emails := re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", texto):
        fato("email", emails[-1])                             # "troca o email": vale o último
    if m := re.search(r"\(\d{2}\) \d{5}-\d{4}", texto):
        fato("telefone_contrato", m.group(0))
    if texto.strip().lower() == "ajudante de producao":
        fato("profissao", "ajudante de produção")
    if m := re.search(r"cidade ta errada, é ([A-Za-zÀ-ú ]+)", texto):
        fato("cidade", m.group(1).strip())
    if re.search(r"(?i)saiu repetido", texto):
        fato("bairro", "Vila Esperança")
    if re.search(r"(?i)\bele (j[áa] )?assinou\b", texto):     # a esposa avisa que o marido assinou
        dados["intencoes"]["diz_que_assinou"] = True
    dados["fatos"] = fatos
    return dados


def roteiro_sc03(caso_):
    papeis = caso_.carregar_agente()["agente"]["config"]["catalogo"]["papeis"]
    dados = ("Nome: {nome}\nCPF: 471.385.926-55\nRG: MG-21.907.335\nEstado civil: casado\nProfissão: ajudante de produção\n"
             "Endereço: Rua das Paineiras, 418, casa\nBairro: {bairro}\nCidade: {cidade}\nCEP: 39999-100\n"
             "Telefone: (33) 99000-0302\nE-mail: " + EMAIL_NOVO)
    return {
        "sdr": [
            passo(MIDIA + "PTV.mp4", "Olá! Me chamo Ana, do escritório Sousa e Costa Advogados.",
                  "Me conta como aconteceu o acidente. De forma direta, vamos precisar de detalhes especificos para o "
                  "pedido , mas caso não se lembre agora, não se preocupe, vamos perguntar com calma todas etapas tudo bem?"),
            passo("Sinto muito pelo que aconteceu com o seu esposo.", "Em qual ano aconteceu o acidente da moto?"),
            passo("Tudo bem, não precisa ser exato.", "Ele recebeu auxílio-doença na época do acidente?"),
            passo("Ele estava trabalhando de carteira assinada (CLT) quando o acidente da moto aconteceu?"),
            passo("Só pra confirmar: ele já tem um advogado atuando HOJE no caso de auxílio-acidente?"),
            passo(papeis["closer"]["mensagem_troca"], "Posso te explicar como funciona o Auxílio-Acidente?",
                  transferir="closer"),
        ],
        "closer": [
            passo(MIDIA + "Como%20Funciona%20o%20Auxilio%20Acidente.ogg",
                  "Conseguiu entender certinho como funciona o benefício?"),
            passo("Quero te mostrar, de forma bem simples, o que muda na sua vida quando esse benefício é aprovado.",
                  "• Renda extra mensal até a aposentadoria.\n• Ele continua trabalhando normalmente.",
                  "Essas vantagens fariam diferença no seu dia a dia?"),
            passo("Sinto muito pela sua mãe.",
                  "Pela regra do INSS, o auxílio-acidente não pode ser recebido junto com uma aposentadoria. Quem já é "
                  "aposentado por invalidez não tem esse direito.",
                  "Voltando ao caso do seu esposo: essas vantagens fariam diferença no dia a dia dele?"),
            passo("Antes de falar em valor ou contrato, quero te mostrar por que vale a pena fazer tudo com a gente.",
                  # O tópico fixo do prompt: "100% online" não é honorário (checagens.valores_de_honorario).
                  "• Cálculo exato feito por especialista.\n• Atendimento simples e 100% online.\n"
                  "• Você só paga se o benefício for aprovado."),
            passo(MIDIA + "video-honorarios-5salarios.mp4", "Conseguiu entender certinho as condições dos honorários?"),
            passo("Perfeito! Vamos avançar para a formalização da nossa representação. Podemos iniciar a coleta dos seus dados?"),
            passo("Sem problema! Quando estiver com os documentos dele, é só me chamar por aqui."),
            passo(papeis["contratos"]["mensagem_troca"], transferir="contratos"),
        ],
        "contratos": [
            passo(MIDIA + "PedidoDocumento.mp4",
                  "Sobre o ligamento: vou deixar anotado para o advogado avaliar junto com o caso.",
                  "Agora me informe o CPF dele, por favor."),
            passo("Nome corrigido.", "Agora me informe o CPF dele, por favor."),
            passo("Qual o RG dele? Se não tiver em mãos, seguimos sem."),
            passo("Qual o estado civil dele?"),
            passo("Qual o CEP de onde ele mora?"),
            passo("Buscamos nos Correios e o endereço é: Rua das Paineiras, Vila Esperança, Vale Sereno/MG.",
                  "Normal essa dúvida. Atendimento online existe pra agilizar sua vida, sem fila.",
                  "O contrato é formal e o processo é seguro. Somos o Sousa e Costa Advogados, CNPJ 44.326.345/0001-05.",
                  "Podemos avançar?"),
            passo("Tem complemento? Se não tiver, é só me dizer."),
            passo("Qual o e-mail dele? Se não tiver, seguimos sem."),
            passo("Anotei o e-mail novo: " + EMAIL_NOVO + ".", "Qual o telefone de contato dele?"),
            passo("Sobre o ligamento: quem avalia o que entra no pedido é o advogado, depois de analisar o caso. Não consigo "
                  "te confirmar isso por aqui.", "Qual a profissão dele hoje?"),
            passo("Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho.",
                  dados.format(nome=NOME_CERTO, bairro="Vila Esperança Vila Esperança", cidade="Minas Gerais"),
                  "Está tudo correto? Posso gerar o contrato?"),
            passo("Atualizei a cidade.", dados.format(nome=NOME_CERTO, bairro="Vila Esperança Vila Esperança",
                                                      cidade="Vale Sereno"), "Posso gerar o contrato?"),
            passo("Pronto, tirei o bairro repetido.", dados.format(nome=NOME_CERTO, bairro="Vila Esperança",
                                                                   cidade="Vale Sereno"), "Posso gerar o contrato?"),
            # A mensagem obrigatória do prompt passa na trava: "receber o link" é aviso de envio, não promessa.
            passo("Perfeito! Estamos gerando o seu contrato.", "Em alguns segundos você vai receber o link para assinatura!",
                  ferramenta="zapsign"),
        ],
        "assinatura": [passo("Que bom! Vou conferir a assinatura por aqui.",
                             "Depois da assinatura, a nossa equipe segue com o atendimento e te chama por aqui.")],
    }


async def test_sc03_roda_no_roteirizado_ate_o_contrato_assinado():
    c = caso()
    snap = c.carregar_agente()
    modelo = falso.ModeloRoteirizado(snap, roteiro_sc03(c), extrator=_extrator)
    conversa = await simulador.rodar_conversa(c, modelo, snapshot=snap)
    falhas = [f.como_dict() for f in conversa.falhas]
    assert not conversa.lead_invalido, conversa.lead_invalido
    origens = [f.origem for r in conversa.rodadas for f in r.falas]
    assert "padrao" not in origens, origens                     # o cartão cobre cada pergunta do fluxo do escritório
    assert conversa.trajetoria == c.esperado.trajetoria, (conversa.trajetoria, falhas)
    assert conversa.parada == "contrato_assinado" and conversa.estado_final == "encerrado", conversa.parada
    assert conversa.ferramentas["zapsign"] == 1 and conversa.ferramentas["cep"] >= 1     # o CEP completou a cidade
    assert conversa.aprovada, falhas
    # Leva 1 (B4): o prompt do escritório não pergunta aposentadoria (nem o aceite do jeito que o portão reconhece);
    # a única correção aceita é a do portão de fatos, que manda perguntar o que falta antes de passar o lead.
    refeitos = [f for f in conversa.falhas if f.codigo == "refeito_pela_trava"]
    assert all("Ainda falta perguntar antes de passar" in f.evidencia for f in refeitos), falhas
    assert "honorario_divergente" not in conversa.codigos(), falhas
    dados = conversa.contratos[-1]["dados"]
    assert dados["nome"] == NOME_CERTO and dados["email"] == EMAIL_NOVO
    assert dados["cidade"] == "Vale Sereno" and dados["bairro"] == "Vila Esperança" and dados["estado"] == "MG"
    assert dados["cpf"] == "471.385.926-55" and dados["numero"] == "418"
    # A ordem do chat: a mãe depois das vantagens, o adiamento e a volta, o nome corrigido no pedido do CPF, as duas
    # correções da confirmação (gatilhos, para a confirmação refeita não virar pergunta_repetida) e o "já assinei".
    textos = [f.texto_corrido() for r in conversa.rodadas for f in r.falas]
    ordem = ["aposentada por invalidez", "amanhã ou depois", "vamos fazer sim", "Santod Mpura", "foi o corretor",
             "fica onde", "usa esse outro", "conta tambem", "cidade ta errada", "saiu repetido", "pode gerar",
             "ele assinou"]
    posicoes = [next(i for i, t in enumerate(textos) if trecho in t) for trecho in ordem]
    assert posicoes == sorted(posicoes), list(zip(ordem, posicoes))


# ---------------------------------------------------------------------------- achados da rodada real 2026-11-25
def test_sc03_proibido_pega_incluir_o_ligamento_e_pedir_documentos():
    proibido = caso().esperado.proibido

    def barra(texto):
        return any(re.search(r, texto) for r in proibido)

    for errado in ("Entendi sobre o joelho. Vamos incluir essa sequela no pedido para garantir o direito dele.",
                   "Sobre o ligamento do joelho, sim, vamos incluir essa sequela no pedido.",
                   "Podemos incluir o ligamento no pedido também.",
                   "Bom dia! Sem problemas pela demora, vamos avançar.\nPreciso dos documentos pessoais dele e "
                   "comprovantes médicos ou laudos que mostrem a sequela da bacia.",
                   "Separe os laudos e exames dele, por favor."):
        assert barra(errado), errado
    for certo in ("O advogado vai avaliar se podemos incluir o joelho.",
                  "Não vamos incluir o joelho sem o advogado avaliar o caso.",
                  "Vou incluir o e-mail novo no contrato.",
                  "Não precisamos de laudo nenhum agora.",
                  "Preciso do CPF dele, por favor."):
        assert not barra(certo), certo


def _lead():
    from app.avaliacao import leads
    lead = leads.LeadCartao(caso().lead)
    lead.abrir()
    return lead


async def test_sc03_abertura_da_confirmacao_nao_autoriza_gerar():
    """T25/T26: diante só do 'Vamos confirmar juntos..., tudo bem?' a lead diz 'ss'; 'pode gerar' só no 'posso gerar'."""
    lead = _lead()
    (fala,) = await lead.responder(["Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho, "
                                    "tudo bem?"], rodada=25)
    assert fala.texto_corrido() == "ss"
    (fala,) = await lead.responder(["Nome completo: Josimar Aparecido dos Santos Moura\nEndereço: Rua das Paineiras, "
                                    "Vila Esperança, 418, casa, Vale Sereno/MG, CEP 39999-100",
                                    "Está tudo correto? Posso gerar o contrato?"], rodada=26)
    # A lista mostra a cidade e o bairro certos: nenhuma correção falsa.
    assert fala.texto_corrido() == "agora sim, pode gerar" and fala.origem.startswith("assunto:"), fala.origem


async def test_sc03_correcoes_so_quando_o_erro_aparece():
    lead = _lead()
    (fala,) = await lead.responder(["Nome: Josimar Aparecido dos Santos Moura\nBairro: Vila Esperança Vila Esperança\n"
                                    "Cidade: Minas Gerais\nCEP: 39999-100", "Está tudo correto? Posso gerar o contrato?"],
                                   rodada=30)
    assert "cidade ta errada" in fala.texto_corrido()
    (fala,) = await lead.responder(["Bairro: Vila Esperança Vila Esperança\nCidade: Vale Sereno",
                                    "Posso gerar o contrato?"], rodada=31)
    assert "saiu repetido" in fala.texto_corrido()
    # O estado por extenso ao lado da cidade certa não é erro de cidade.
    lead = _lead()
    (fala,) = await lead.responder(["Endereço: Rua das Paineiras, 418, Vila Esperança, Vale Sereno, Minas Gerais",
                                    "Posso gerar o contrato?"], rodada=30)
    assert fala.texto_corrido() == "agora sim, pode gerar"


async def test_sc03_pedido_do_estado_pelo_sistema_recebe_a_sigla():
    """T26: o pedido do sistema vem numa frase sem '?' e, antes dele, a IA perguntou 'tudo bem?': a lead manda 'MG'."""
    lead = _lead()
    falas = await lead.responder([
        "Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho, tudo bem?",
        "Nome completo: Josimar Aparecido dos Santos Moura / Endereço: Rua das Paineiras, Vila Esperança, 418, casa, "
        "Vale Sereno/MG, CEP 39999-100",
        "Para finalizar seu contrato, preciso confirmar uma informação: o seu estado (a sigla, como MG ou SP). "
        "Pode me enviar novamente, por favor?"], rodada=26)
    assert falas[0].texto_corrido() == "MG", (falas[0].origem, falas[0].texto_corrido())
    # E a pergunta do estado civil não cai no assunto do estado (UF).
    (fala,) = await _lead().responder(["Qual o seu estado civil?"], rodada=19)
    assert fala.texto_corrido() == "casado"
