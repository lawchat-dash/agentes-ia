# Agente de triagem (recepção do escritório)

Desenho, 25/11/2026. Nada aqui está implementado. Continua a seção 4.5 do [DESENHO.md](../DESENHO.md) e fecha a lacuna
"decisão e roteamento por produto" do [WEAVER_PARA_CODIGO.md](WEAVER_PARA_CODIGO.md).

- Prompt pronto: [avaliacao/agentes/triagem_PROMPT.md](../avaliacao/agentes/triagem_PROMPT.md)
- Cenários de teste: [avaliacao/cenarios_triagem/](../avaliacao/cenarios_triagem/). Eles ainda não rodam: a seção 12
  diz o que falta.

---

## 1. Em uma frase

Um número de WhatsApp passa a ter uma **recepção**. Ela descobre o assunto do lead, pela origem do anúncio ou com
1 a 3 perguntas curtas, e entrega o lead ao **primeiro agente do produto certo** (o SDR do auxílio-acidente, por
exemplo), à **equipe humana** ou a um **encerramento educado**. Junto vai um resumo, para o próximo agente não repetir
perguntas. A recepção não qualifica, não avalia direito e não promete nada.

## 2. Como é hoje e por que não basta

| Hoje (código) | Consequência |
|---|---|
| `agentesia_agentes.id_canal` é UNIQUE: um número tem um agente, e um agente tem um produto | Para atender dois produtos, o escritório precisa de dois números. A ativação devolve 409 ("Este número já está em uso pelo agente X") |
| O agente de cada turno é resolvido **pelo canal** (`pipeline.py:92` e `:374`), não por `lead.id_agente` | Mesmo que alguém troque o agente do lead, o turno seguinte volta ao agente do canal. Se o `id_etapa` for de outro agente, o motivo vira `agente_sem_etapa` |
| `classificar_origem` (`acoes.py:656`) descobre o benefício do anúncio, mas só põe nota e etiqueta | O anúncio de BPC cai no SDR de auxílio-acidente, que pergunta "como foi o acidente?" |
| `outro_beneficio` (sinal do extrator e do auditor) pausa o lead e chama a equipe | O lead que veio pelo número errado sai da IA, mesmo quando o escritório tem um funil de IA para o benefício dele |
| No n8n, o Weaver tem o "UTM -> PRODUTO", mas só o ramo BPC faz algo, e só para um cliente; o Geral não tem nada | Não há o que portar além do prompt do classificador |

## 3. Peças

```
               evento (mensagem ou TRACK)
                         |
                  [canal pelo número]
                         |
          lead já existe? ---- sim ----> agente do LEAD (lead.id_agente)
                         | não
                         v
      CAMADA 0 (código, sem IA): o canal tem um produto só e não há triagem?
                         | -------- sim ----> 1º agente desse produto (como hoje)
                         v não
      CAMADA 1 (origem): anúncio, UTM ou mensagem pré-preenchida dizem o produto
                         com confiança >= 0,75 e ele está ativo no canal?
                         | -------- sim ----> 1º agente do produto (pula a triagem)
                         v não
      CAMADA 2 (conversa): AGENTE DE TRIAGEM, no máximo N perguntas
                         |
          +--------------+--------------+------------------+
          v              v              v                  v
   1º agente do     equipe humana    humano (pediu,      fora do escopo /
   produto X        do produto       cliente antigo,     engano: mensagem
   (funil de IA)    (departamento)   indefinido)         fixa e encerra
```

As duas camadas devolvem o **mesmo resultado** (seção 6). O resto do sistema não precisa saber de onde a decisão veio.

## 4. Quando a triagem entra

| Situação | Entra na triagem? | Observação |
|---|---|---|
| Lead novo num número com **um produto só**, sem "sempre confirmar" | **Não** | Comportamento de hoje. Nenhum escritório paga a triagem sem precisar |
| Lead novo, o anúncio (TRACK/UTM) ou a mensagem pré-preenchida diz o produto com confiança >= 0,75, e o produto está ativo no número | **Não** | Vai direto ao 1º agente do produto. A origem vira o primeiro fato do pacote de passagem |
| Lead novo **sem origem** ("oi", "boa tarde", "vi o anúncio") num número com 2 ou mais produtos | **Sim** | Caso principal |
| Lead novo com origem de **confiança baixa**, resultado `nao_sei`/`outro`, ou produto que **não está ativo** no número | **Sim** | A origem entra como pista ("o anúncio parece ser de X"), nunca como decisão |
| Escritório marcou **"sempre confirmar"** no número | **Sim** | A triagem confirma em 1 pergunta ("É sobre o auxílio-acidente mesmo?") e passa adiante |
| Lead já no SDR de um produto pede **outro benefício** (sinal `outro_beneficio` confirmado pelo auditor) | **Sim, uma vez por lead** | Em vez de pausar, volta à triagem. Se já voltou uma vez, ou se o benefício pedido não tem funil nem equipe, segue o comportamento de hoje: pausa e chama a equipe |
| Contato que já é lead de um produto **neste escritório** e manda mensagem de novo | **Não** | Continua no agente do lead (é o mesmo registro: `unique(id_canal, id_contato)`) |
| Número da equipe ou de cliente atual (lista do escritório) | **Não** | Vai para humano sem IA (padrão P04 do DESENHO) |

"Número com vários produtos" é a novidade de banco: hoje não existe. Ver seção 9.

## 5. Como decide

### 5.1 Camada 1: origem primeiro (sem conversar)

Reaproveita o que já existe e muda só três coisas:

1. **Hora**: hoje `classificar_origem` é uma ação enfileirada, que roda depois do primeiro turno. Passa a rodar
   **antes** do primeiro turno do lead novo, dentro do buffer que já existe, com espera máxima de ~4 s. Se não ficar
   pronta, a triagem conversa e usa a origem quando ela chegar. O cache por anúncio (`chave_do_anuncio`) faz com que, do
   2º lead do mesmo anúncio em diante, a resposta seja imediata e sem IA.
2. **Limiar**: a nota e a etiqueta continuam com confiança >= 0,6, como hoje. **Pular a triagem** exige >= 0,75.
3. **Mapa**: o enum do classificador (`auxilio_acidente`, `bpc_loas`, `auxilio_doenca`...) é ligado aos **produtos
   ativos do número** por uma tabela simples na config da triagem (`categoria_do_classificador -> slug do produto`).
   Categoria sem produto ativo vira pista para a triagem, não decisão.

Mensagem pré-preenchida do botão do anúncio ("Olá, vi o anúncio sobre BPC") passa pelo mesmo classificador, com fonte
`mensagem_inicial`.

**Divergência**: se o anúncio diz auxílio-acidente e o lead fala do BPC do filho, **vale o que o lead diz**. A
divergência fica gravada em `leads.triagem.divergencia`, porque ajuda a avaliar as campanhas.

### 5.2 Camada 2: o agente de triagem (conversando)

- Lê tudo o que o lead já mandou (texto, áudio transcrito, descrição da imagem) e a pista da origem.
- Se a primeira mensagem já disser o assunto ("sofri um acidente de moto e fiquei com o braço ruim"), **não pergunta
  nada**: passa no mesmo turno.
- Se não disser, faz **uma pergunta por mensagem, no máximo N no total** (padrão 2, máximo configurável 3), sempre
  curtas e abertas primeiro ("Me conta em que posso te ajudar?"), depois fechadas só para desempatar ("É sobre o
  acidente ou sobre a aposentadoria?").
- Também reconhece: pedido de humano, cliente antigo do escritório, assunto fora da área previdenciária, engano/spam,
  parente falando pelo segurado e dois assuntos ao mesmo tempo.
- Devolve uma saída em JSON fixo (seção 6). **O código decide** com base nela: o modelo propõe, o código confere.

**Travas do código sobre a saída da triagem:**

| Trava | O que o código faz |
|---|---|
| `destino` fora da lista de destinos válidos do número | Rejeita e pede de novo (CORRIJA), como `catalogo.conferir` |
| Já fez N perguntas e ainda não decidiu | Força `humano` com a frase fixa de passagem para a equipe |
| Decidiu produto com `confianca` < 0,6 | Não passa: troca por mais uma pergunta (se ainda houver) ou por `humano` |
| Mensagem com promessa, percentual, prazo, "tem direito" ou "não tem direito" | Mesmas travas de proibidos do catálogo, mais estas: a triagem não fala de direito |
| Mais de uma pergunta no balão | Reprovação leve (CORRIJA) |
| Triagem repetida | Segunda volta à triagem no mesmo lead vai direto para `humano` |

### 5.3 Dois assuntos

Um lead fala de dois benefícios ("sofri acidente e minha mãe quer aposentar"). Regra: **um assunto por vez**. A
triagem escolhe o **do próprio lead** e, entre dois do lead, o que tem funil de IA. O outro vai em
`assunto_secundario` no pacote de passagem. O código põe uma nota na Helena e dispara a automação `triagem:assunto_secundario`,
que o escritório pode ligar a um departamento. O lead ouve: "Vamos começar pelo seu acidente; sobre a aposentadoria
da sua mãe, a equipe também vai te chamar."

## 6. Resultado da triagem (o que passa adiante)

A mesma estrutura sai da camada 1 (preenchida pelo código) e da camada 2 (preenchida pelo modelo):

```json
{
  "mensagens": [{"texto": "..."}],
  "decisao": "perguntar | passar",
  "destino": "auxilio-acidente | bpc-loas | ... | humano | fora_do_escopo | engano | ''",
  "categoria": "auxilio_acidente | incapacidade | aposentadoria | bpc_loas | pensao_morte | salario_maternidade | revisao | outro_previdenciario | fora_da_area | indefinido",
  "subcategoria": "bpc_crianca | bpc_adulto | bpc_idoso | aposentadoria_especial | rural | ''",
  "confianca": 0.0,
  "fonte": "anuncio | mensagem_inicial | conexao | historico | conversa",
  "motivo": "uma frase, interna",
  "passagem": {
    "resumo": "Esposa (Cleide) falando pelo marido. Acidente de moto indo pro trabalho em 2016, ficou mancando. Veio de anúncio de auxílio-acidente.",
    "quem_fala": "proprio | parente",
    "parentesco": "esposa",
    "nome_segurado": "",
    "fatos": {"acidente_descricao": "...", "acidente_ano": 2016, "sequela": "sim", "aposentado": "nao"},
    "ja_perguntado": ["como aconteceu"],
    "assunto_secundario": "aposentadoria da mãe",
    "pedido_do_lead": "quer saber se tem direito a indenização"
  }
}
```

**Como o próximo agente recebe isso:**

1. **Histórico**: o lead é o mesmo registro, então a conversa inteira com a triagem já aparece em "CONVERSA ATÉ AQUI".
2. **Fatos**: os `fatos` que batem com o esquema do produto de destino (por exemplo `acidente_ano`, `sequela`,
   `aposentado` no auxílio-acidente) são gravados em `agentesia_lead_fatos` com fonte `triagem`. Eles aparecem em
   "DADOS JÁ INFORMADOS PELO LEAD (não pergunte de novo)", e o FORMATO do catálogo já manda não repetir essas perguntas.
   Os fatos que não estão no esquema do destino ficam só no resumo.
3. **Linha de passagem**: no primeiro turno do agente de destino, o conteúdo ganha uma linha
   `PASSAGEM DA TRIAGEM (sistema): <resumo>. Ainda não perguntado: <...>`.
4. **Primeira resposta do agente**: hoje `primeira = not any(autor == "você")` (`turno.py`) e o SDR do Sousa e Costa
   só manda o vídeo de abertura "caso não tenha nenhum histórico". Depois da triagem sempre há histórico. A regra passa
   a ser **"primeira resposta deste agente"** (nenhuma mensagem da IA desde a troca de `id_agente`). A linha de passagem
   diz: "envie a mídia de apresentação do roteiro, se houver; não se apresente de novo pelo nome; comece pela primeira
   pergunta que ainda não foi respondida".

**Passagem no mesmo turno (encadeada):** quando a triagem decide `passar` para um produto de IA, o código roda o
primeiro turno do agente de destino **no mesmo lote**. Assim o lead não fica olhando para "vou te passar" esperando
outra mensagem. A frase de passagem da triagem é curta e sem pergunta ("Entendi, é sobre o acidente. Vou seguir com
você nisso."), e a pergunta vem do agente do produto. São 2 chamadas de IA nesse turno, só na passagem.

**Uma pessoa só para o lead:** a triagem usa o mesmo nome de atendente do escritório (a "Ana"). O lead nunca lê
"agente", "triagem", "transferir" nem "setor de IA". Para a equipe humana, sim: "vou chamar a nossa equipe responsável
por X".

## 7. Para onde manda

| Destino | Quando | O que o código faz | Frase de passagem (modelo do prompt) |
|---|---|---|---|
| `<slug do produto>` com atendimento **IA** | Assunto claro e o produto tem funil de IA no número | Troca `id_agente` e `id_etapa` do lead para o agente do produto e a etapa `principal`; grava histórico; encadeia o 1º turno do destino | "Entendi, é sobre {produto}. Vou seguir com você nisso." |
| `<slug do produto>` com atendimento **equipe** | Produto ativo, mas atendido por humanos (o BPC da Castro e Borges, por exemplo) | Manda a mensagem e a mídia fixas do produto, transfere a sessão da Helena para o departamento (`id_equipe`), pausa a IA (`motivo = triagem:equipe:<slug>`) | "Perfeito! Vou chamar a nossa equipe responsável por {produto}. Eles te respondem por aqui mesmo." |
| `humano` | Pediu atendente; cliente antigo; outro benefício previdenciário sem produto ativo e com equipe configurada; indefinido depois de N perguntas | Transfere para o departamento padrão do escritório (`config_agente.id_equipe_transferencia`), pausa a IA, dispara `triagem:humano` | "Vou chamar uma pessoa da nossa equipe para falar com você por aqui, tudo bem?" |
| `fora_do_escopo` | Assunto real que o escritório não atende (trabalhista, família, consumidor, criminal) | Mensagem fixa do escritório, encerra o lead (`estado = encerrado`, `motivo = triagem:fora_do_escopo`), etiqueta "Fora do escopo" | "Esse assunto a gente não atende aqui, porque nosso escritório é só de INSS e previdência. O ideal é procurar um advogado da área de {área}." |
| `engano` | Número errado, spam, propaganda, conversa sem assunto depois de N tentativas | Mensagem fixa curta e encerra; **sem** card de lead (ou card arquivado) | "Acho que essa mensagem veio por engano. Se precisar de ajuda com INSS, é só chamar aqui." |

O escritório configura, por número: os produtos atendidos ali e se cada um é **IA**, **equipe** ou **recusa**; o
departamento da equipe; a mensagem de fora do escopo; se os "outros benefícios" sem produto vão para `humano` ou para
`fora_do_escopo`; o máximo de perguntas; e "sempre confirmar".

## 8. Como fica na Helena

| Momento | Card (CRM) | Etiqueta | Nota |
|---|---|---|---|
| Lead novo entra na triagem | Criado na coluna **Triagem** (nova coluna configurável no painel, como as do SDR) | `Triagem` | Origem, como hoje ("Anúncio de: X") |
| Passou para produto de IA | Move para a 1ª coluna do produto (a do SDR) | Tira `Triagem`, põe a do produto (`etiquetas_por_produto`) e a do SDR, que hoje `_lead_novo` põe na hora | "Triagem: <resumo> -> <produto>" |
| Passou para equipe/humano | Coluna do produto ou "Com humano" | Etiqueta do produto | Resumo da triagem, para a pessoa não perguntar tudo de novo |
| Fora do escopo / engano | Arquivado ou coluna "Fora do escopo" | `Fora do escopo` | Motivo |

Tudo isso passa pelas automações que já existem (`app/automacoes.py`), com gatilhos novos: `triagem:entrou`,
`triagem:produto:<slug>`, `triagem:equipe:<slug>`, `triagem:humano`, `triagem:fora_do_escopo`, `triagem:engano`,
`triagem:assunto_secundario`. Um escritório que não configura nada recebe o padrão acima.

## 9. Banco (proposta de `db/migracoes/003_agentesia_triagem.sql`, não escrita)

O rascunho `db/rascunhos/estrutura_completa_001.sql` já previa parte disso. Proposta mínima e compatível (um número
com um produto e sem triagem continua igual):

| Tabela | Mudança | Por quê |
|---|---|---|
| `agentesia_agentes` | `id_canal` deixa de ser UNIQUE. Novo `tipo text not null default 'produto' check (tipo in ('produto','triagem'))`. Índice único `(id_canal) where tipo = 'triagem'` | Vários agentes por número: uma recepção e um agente por produto |
| `agentesia_agentes.produto` | Aceita `'triagem'` (em `app/cerebro/produto.py:carregar`) | O cérebro sabe montar o turno da triagem |
| `agentesia_canais` | `id_agente_entrada uuid null references agentesia_agentes` | Quem recebe o lead novo. Nulo = o único agente do canal (o de hoje) |
| `agentesia_produtos_ativados` | `atendimento text not null default 'ia' check (atendimento in ('ia','equipe','recusa'))`, `id_equipe_helena text`, `mensagem_equipe text`, `descricao_triagem text`, `categorias_classificador text[]` | É daqui que sai `{produtos_ativos}` do prompt e o mapa da camada 1. Produto `equipe` não precisa de agente (`id_agente` já é anulável) |
| `agentesia_leads` | `triagem jsonb not null default '{}'` (decisão, fonte, confiança, perguntas feitas, voltas, divergência, assunto secundário) | Auditoria e métricas por campanha. `id_agente` passa a ser a **fonte de verdade** do agente do lead |
| `agentesia_lead_fatos.fonte` | Check aceita `'triagem'` | Fatos passados adiante, separados dos que o extrator leu |
| `agentesia_lead_etapas_historico` (nova, do rascunho) | `id_lead, id_agente_de, id_etapa_de, id_agente_para, id_etapa_para, motivo, em` | Linha do tempo da troca de agente (hoje só há `etapa_antes`/`etapa_depois` no turno, sem agente) |
| `agentesia_biblioteca_agentes.papel` | **Sem mudança** | A triagem não é papel de produto. É um agente do número, com um prompt de plataforma (o `triagem_PROMPT.md`) e o mesmo editor de prompt do painel |

A chave `unique(id_canal, id_contato)` **fica**: o lead continua sendo um só por pessoa e número. O que muda de produto
é o `id_agente`. Assim não há card duplicado na Helena nem histórico partido.

## 10. O que muda no código (sem implementar)

| Arquivo | Mudança |
|---|---|
| `app/pipeline.py` | (a) lead novo: agente de entrada = `canal.id_agente_entrada` ou o único agente do canal; (b) cada turno: agente = `repo.agente(lead.id_agente)`, com o do canal como reserva (linhas 92 e 374); (c) aplicar a decisão da triagem: trocar agente e etapa, gravar histórico, encadear o 1º turno do destino, pausar/encerrar nos outros destinos; (d) camada 1 antes do 1º turno; (e) "primeira resposta deste agente" |
| `app/banco/postgres.py` e `app/banco/memoria.py` | `agente(id)`, `agentes_do_canal(id_canal)`, `achar_ou_criar_lead(agente_entrada)`, `trocar_agente_do_lead(...)` com histórico, leitura de `produtos_ativados` do canal |
| `app/cerebro/triagem.py` (novo) | Monta o prompt (`{produtos_ativos}`, `{pista_da_origem}`, `{max_perguntas}`), o esquema JSON da seção 6, as travas da seção 5.2 e o mapeamento dos fatos de passagem para o esquema do destino |
| `app/cerebro/turno.py` | Ramo `produto.codigo == "triagem"` (sem extrator nem auditor: a própria triagem devolve intenção e fatos, o que economiza 2 chamadas por turno); `outro_beneficio` volta à triagem quando ela está ligada, o benefício tem destino e `voltas == 0` |
| `app/cerebro/produto.py` | `carregar` reconhece `"triagem"` |
| `app/acoes.py` e `app/origem.py` | `classificar_origem` devolve a decisão (não só etiqueta), roda antes do 1º turno, usa o limiar de 0,75 para pular a triagem e lê a mensagem pré-preenchida |
| `app/gestao/produtos.py` | `_canal()` deixa de dar 409 quando o número tem a recepção ligada; `/canais/disponiveis` mostra "número com recepção"; rota para ligar a recepção num número e escolher os produtos dele |
| `app/automacoes.py` | Gatilhos `triagem:*` da seção 8 |
| `painel/` | Tela "Recepção" por número: liga/desliga, produtos e modo (IA/equipe/recusa), departamento, máximo de perguntas, "sempre confirmar", mensagem de fora do escopo, prompt editável |
| `app/avaliacao/*` | Suporte aos cenários de triagem (seção 12) |

**Ordem sugerida**: (1) resolver o agente por `lead.id_agente` (sozinho já é seguro e não muda nada para quem tem um
agente por número); (2) banco 003; (3) camada 1 decidindo produto; (4) agente de triagem; (5) `outro_beneficio` voltando
à triagem; (6) painel.

## 11. Limites e custo

**Limites (no prompt e conferidos pelo código):**
- No máximo **N perguntas** (padrão 2, teto 3). Depois disso, decide com o que tem ou passa para humano.
- **Uma pergunta por mensagem**, mensagens de até ~300 caracteres.
- **Nunca** dá parecer jurídico: não diz "tem direito", "não tem direito", "seu caso é bom", nem explica requisito.
- **Nunca** promete resultado, valor, prazo ou percentual, e não fala de honorários.
- **Nunca** pede documento, CPF ou dado pessoal: isso é do funil.
- **Nunca** qualifica. Mesmo que o lead diga "sou aposentado" a caminho do auxílio-acidente, a triagem só anota
  `aposentado: sim` e passa: quem desqualifica é o SDR do produto, com o roteiro do escritório.
- **Nunca** diz que é robô, triagem ou agente. Se perguntarem, responde "sou a assistente virtual do escritório" (igual
  ao resto do funil).

**Custo:** modelo `gpt-4.1-mini` (o mesmo dos funis; preço de tabela em `app/modelo.py`: US$ 0,40 por milhão de tokens
de entrada, 1,60 de saída, 0,10 de entrada em cache).
- Prompt do sistema da triagem: ~1.500 tokens, fixo por escritório, entra no cache do provedor do 2º turno em diante.
- Conteúdo por turno: ~300 a 800 tokens (conversa curta). Saída: ~150 a 250 tokens.
- Por turno de triagem: cerca de US$ 0,001. A triagem toda (0 a 3 turnos): **US$ 0,000 a 0,004 por lead**, sem
  extrator nem auditor nesses turnos.
- Camada 1 com cache por anúncio: custo zero do 2º lead do mesmo anúncio em diante.
- A passagem encadeada não é custo novo: é o 1º turno do SDR, que aconteceria de qualquer forma.

Comparado a um lead de auxílio-acidente inteiro (`app/avaliacao/custo.py:previsto_lead_ia`), a triagem é uma fração
pequena. Ainda assim, ela só liga em número com mais de um produto ou com "sempre confirmar".

## 12. Testes: o que falta para os cenários rodarem

Os cenários de `avaliacao/cenarios_triagem/` estão escritos no formato de `app/avaliacao/cenario.py`, com **três
campos novos** que o formato de hoje recusa (`extra="forbid"`). Por isso eles ficam numa pasta própria: `listar()` só lê
`avaliacao/cenarios/` por padrão, e nada do que roda hoje quebra.

| Falta | Onde |
|---|---|
| `lead.origem` (dict com `campanha`, `titulo`, `conteudo`, `url`, `clid` ou `mensagem_inicial`): gera o evento TRACK antes da 1ª mensagem | `cenario.py` (`Lead`) e `montagem.py` (webhook do TRACK, que hoje não existe na simulação) |
| `esperado.triagem` (`destino`, `pula_triagem`, `max_perguntas`, `fatos_passados`, `assunto_secundario`, `nao_perguntar_no_destino`) | `cenario.py` (`Esperado`) e `checagens.py` (checagens novas: `destino_triagem`, `perguntas_triagem`, `pulou_triagem`, `fatos_passados`, `repetiu_pergunta_da_triagem`) |
| Snapshot com **vários agentes** no mesmo número (`avaliacao/agentes/triagem_referencia.json`: escritório + `triagem` + `produtos`, cada um com `atendimento` e, se IA, o snapshot do agente) | `cenario.py:carregar_agente` (hoje exige `{escritorio, agente}`) e `montagem.py` (hoje `repo.agentes[ID_CANAL]` guarda um agente só) |
| Trajetória com agente: `"triagem"`, depois `"auxilio-acidente/sdr"` | `simulador.py:_trajetoria` (hoje só lê o código da etapa, que se repete entre produtos) |
| `limites.parar_em` aceitar `agente/etapa` | `simulador.py:_parada` |
| O destino `equipe`/`humano` termina com o lead `pausado` e uma transferência na Helena falsa | `efeitos.py` (`HelenaFalsa.transferir` registrando o `id_equipe`) |

Os cenários usam `limites.parar_em` na 1ª etapa do destino: o objetivo é testar a recepção e a 1ª resposta do agente
seguinte (que não pode repetir pergunta), não o funil inteiro.

Conferido em 25/11/2026: os 10 arquivos são JSON válidos, todas as regex compilam e o validador de hoje
(`Cenario.model_validate`) recusa **só** os campos novos (`lead.origem` e `esperado.triagem`). Sem eles, cada cenário
valida e expande (11 casos, contando as 2 variantes do t02).

**Campos de `esperado.triagem` usados nos cenários:**

| Campo | Confere |
|---|---|
| `destino` | Destino final da triagem (slug do produto, `humano`, `fora_do_escopo`, `engano`) |
| `categoria`, `subcategoria`, `fonte` | Os campos do resultado (seção 6) |
| `pula_triagem` | `true` quando a camada 1 decidiu e a triagem não falou com o lead no 1º turno |
| `max_perguntas` | Teto de mensagens da triagem com pergunta (`?`) |
| `fatos_passados` | Fato -> trecho esperado nos fatos com fonte `triagem` |
| `nao_perguntar_no_destino` | Regex que a 1ª resposta do agente de destino não pode ter |
| `quem_fala`, `parentesco`, `assunto_secundario`, `voltas`, `divergencia` | Campos do pacote de passagem e de `leads.triagem` |
| `transferiu_para_equipe` | Nome do departamento na transferência da Helena falsa |
| `card_na_helena` | `false` quando o destino não pode criar card de lead |

**Snapshot de referência a criar (`avaliacao/agentes/triagem_referencia.json`):**

```json
{
  "escritorio": {"nome": "Escritório Exemplo Advocacia", "config": {}},
  "agente": {
    "id": "agente-triagem", "nome": "Júlia", "produto": "triagem",
    "config": {"modelos": {"etapa": "gpt-4.1-mini"},
               "triagem": {"max_perguntas": 2, "sempre_confirmar": false, "outros_beneficios": "humano",
                           "area": "benefícios do INSS e previdência", "id_equipe_padrao": "dep-atendimento"}},
    "etapas": [{"id": "et-triagem", "codigo": "triagem", "principal": true, "instrucao": "<triagem_PROMPT.md>"}]
  },
  "produtos": [
    {"destino": "auxilio-acidente", "nome": "Auxílio-Acidente", "atendimento": "ia",
     "cobre": "acidente de qualquer tipo que deixou sequela", "categorias": ["auxilio_acidente"],
     "agente": "avaliacao/agentes/catalogo_referencia.json"},
    {"destino": "bpc-loas", "nome": "BPC/LOAS", "atendimento": "equipe", "id_equipe_helena": "BPC/LOAS",
     "cobre": "pessoa com deficiência ou idosa de baixa renda", "categorias": ["bpc_loas"]},
    {"destino": "aposentadoria", "nome": "Aposentadoria", "atendimento": "equipe", "id_equipe_helena": "Aposentadoria",
     "cobre": "aposentadoria por idade, tempo, rural ou especial", "categorias": ["aposentadoria"]}
  ]
}
```
