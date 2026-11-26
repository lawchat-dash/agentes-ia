# Base de conhecimento: como cada agente consulta

Desenho de 2026-11-25. Substitui a parte "documentos" do DESENHO.md 7.x, onde falava em reaproveitar
`sistemaia_conhecimento_vetores`. Ficamos com as nossas tabelas `agentesia_*`.

Objetivo: a IA responder **fatos do escritório** (valores, prazos, documentos, endereço, regras do benefício)
só com o que está escrito pelo escritório, com poucos trechos certos por turno, e **avisar o escritório**
quando a pergunta não tem resposta na base.

---

## 1. O que aproveitamos do Weaver e o que corrigimos

| Weaver (n8n) | Problema | No motor Python |
|---|---|---|
| Uma tabela de trechos com vetor 3-small 1536 | ok | Mantém o mesmo modelo (text-embedding-3-small, 1536). |
| Trechos de 3.000 caracteres sem título | vários assuntos num vetor só, baixa precisão | Trechos de ~1.000 caracteres, com "Documento > Seção" no começo do texto vetorizado. Cada FAQ e cada objeção é um trecho próprio. |
| topK 100, sem nota mínima | até ~75 mil tokens por chamada, muito texto irrelevante | Até 4 trechos, nota mínima absoluta + corte relativo, teto de 3.500 caracteres. Nada passa = nada entra. |
| Filtro só por agente | closer recebe base do SDR | Filtro por agente (= escritório + produto) **e** por papel/etapa, com "todos os papéis" como padrão. |
| Busca só se a IA decidir chamar a ferramenta, com frase escrita pela IA | às vezes não busca, às vezes busca errado | Busca feita pelo código antes do turno, em paralelo com o extrator, com a fala do lead. |
| FAQ e objeções como texto fixo no prompt | não escala, dilui a instrução | Pequeno fica fixo (cache de prompt); grande vai para a busca. |
| Sem registro de lacuna | escritório nunca sabe o que falta | Pergunta sem resposta vira linha em `agentesia_conhecimento_lacunas`, com contador, para virar FAQ no painel. |
| `sistemaia_match_conhecimento` SECURITY DEFINER aberto a `authenticated` | vazamento entre escritórios | Não usamos. Nossa busca roda só no servidor, sempre com `id_agente` e `id_escritorio`. (Avisar o time do Weaver; não mexemos lá.) |
| Desqualificado e fluxo GERAL sem base | sem resposta | Todos os papéis consultam, inclusive desqualificado. |

O que o motor Python faz hoje e muda:

- consulta = 4 últimas mensagens **incluindo as da IA** → passa a ser só a fala nova do lead (mais a última pergunta da IA quando a fala é curta);
- nota mínima 0,05 (não filtra nada com embeddings reais) → mínima calibrada + corte relativo;
- até 5 trechos / 9.000 caracteres quase todo turno → até 4 trechos / 3.500 caracteres, muitas vezes zero;
- 40 FAQ + 30 objeções inteiras em todo turno → fixas só se couberem em ~3.000 caracteres; senão, buscadas;
- trechos escolhidos vão no SISTEMA (quebra o cache) → vão no CONTEÚDO do turno; o sistema fica estável;
- nada registrado → turno guarda o que entrou e com que nota.

---

## 2. Modelo de dados

Reaproveita `agentesia_documentos` e `agentesia_documento_trechos`. Uma migração nova (`003_agentesia_conhecimento.sql`)
só com colunas e uma tabela pequena:

**`agentesia_documentos`** (documento = arquivo, texto colado, ou a coleção de FAQ/objeções do agente)
- `tipo`: aceita também `'faq'` e `'objecoes'` (um documento "virtual" por agente para cada um, gerado da config).
- `papeis text[] not null default '{}'`: escopo. Vazio = **todos os papéis**. Ex.: `{contratos,assinatura}`.

**`agentesia_documento_trechos`**
- `id_escritorio uuid not null`: defesa extra (a busca filtra pelos dois).
- `papeis text[] not null default '{}'`: copiado do documento ou do item de FAQ/objeção (o item pode ter escopo próprio).
- `titulo text`: "Documento > Seção" ou a pergunta do FAQ (aparece no prompt como fonte).
- `fonte text check (fonte in ('documento','faq','objecao'))`.
- `hash text not null`: sha256 de `modelo + texto vetorizado`. É o cache de embedding: texto igual não é vetorizado de novo.
- `modelo text not null default 'text-embedding-3-small'`, `dimensoes int not null default 1536`.
- índice `(id_agente)` já existe; novo índice `(id_agente, hash)`.

**`agentesia_conhecimento_lacunas`** (nova)
- `id, id_escritorio, id_agente, papel, pergunta, pergunta_normalizada, vezes int, ultimo_lead uuid, ultimo_turno uuid,
  situacao ('aberta','respondida','ignorada'), resposta text, criado_em, ultima_em`.
- único `(id_agente, pergunta_normalizada) where situacao = 'aberta'`: a mesma dúvida soma em `vezes`.
- RLS como as outras `agentesia_*`.

Escopo, em resumo:

| Nível | Onde | Como filtra |
|---|---|---|
| Escritório | `id_escritorio` no documento e no trecho | `where id_escritorio = $1` (sempre) |
| Produto | o agente (1 produto = 1 agente) | `where id_agente = $2` (sempre) |
| Papel/etapa | `papeis text[]` | em Python: `not papeis or papel in papeis` |
| Padrão do produto | `origem = 'produto'`, `travado` | copiado na ativação, com o `papeis` do catálogo |

Pgvector: **não por enquanto**. Um agente tem centenas de trechos; com os vetores já normalizados no cache em memória
o produto escalar em Python é rápido o bastante (medido no protótipo, seção 9). Passa a valer a pena acima de ~3.000 trechos
por agente; aí entra `vector(1536)` + HNSW com filtro por agente antes (ou `hnsw.iterative_scan`), não depois como no Weaver.

FAQ e objeções continuam sendo **editados** em `agentesia_agentes.config.conhecimento` (o painel não muda de lugar);
cada item ganha um campo opcional `papeis` (lista). A indexação lê a config e mantém os documentos virtuais em dia.

---

## 3. Quando consultar

**Em todo turno em que o lead escreveu algo com conteúdo**, decidido por uma regra local (sem IA):

- consulta se a fala nova tem `?` ou pelo menos 2 palavras de conteúdo (fora de "ok", "sim", "bom dia", números soltos...);
- não consulta em saudação, confirmação, resposta curta à pergunta de qualificação ("sim", "2019", "uns 2 anos").

Por que não esperar o extrator marcar "dúvida": o extrator é uma chamada de IA; esperar por ele soma a latência dele à da busca,
e ele erra dúvidas implícitas ("e se eu perder?"). Rodamos a busca **em paralelo com o extrator** (`asyncio.gather`), então
a latência extra é zero na prática (embedding ~150–300 ms, extrator bem mais).

Custo: a consulta tem ~30–80 tokens → ~US$ 0,000002 por turno no 3-small. O custo real é o texto que entra no prompt,
por isso o teto de 3.500 caracteres (~900 tokens) e o "nada passa = nada entra". O custo do embedding da consulta
passa a ser gravado em `agentesia_chamadas_ia` com papel `conhecimento_consulta`.

**Texto da consulta**:
1. as mensagens novas do lead (pendentes), juntas;
2. se a fala tiver menos de 4 palavras de conteúdo ("e quanto é?", "precisa ir aí?") e a última mensagem da IA terminar
   em pergunta, põe essa pergunta antes (até 200 caracteres) para dar o assunto;
3. nunca o histórico antigo nem outras falas da IA.

---

## 4. Busca

1. Carrega os trechos do agente (cache em memória, ver seção 7), já com o vetor **normalizado**.
2. Filtra por papel: `not papeis or papel_atual in papeis`.
3. Nota = cosseno(consulta, trecho) + **0,08 × reforço por palavra** (fração das palavras de conteúdo da consulta que
   aparecem no trecho; mesma normalização de `conhecimento._palavras`). O reforço resolve nomes próprios, siglas e
   números ("LOAS", "13º", "Rua X") que o embedding às vezes não pesa.
4. Cortes:
   - nota mínima **absoluta**: 0,35 para o text-embedding-3-small (valor inicial; calibrar, seção 8). Com o vetorizador
     falso (modo de teste/demonstração) não se usa vetor: vai direto para a busca por palavras, que acerta mais nesse modo;
   - corte **relativo**: descarta abaixo de 80% da melhor nota;
   - até **4 trechos**, no máximo **2 do mesmo documento**;
   - teto de **3.500 caracteres** (configurável por agente em `config.conhecimento.teto_documentos`, 1.000 a 8.000;
     corrigir `_limpar_conhecimento` para não apagar esse campo).
5. Falhas:
   - embedding falhou → busca por palavras (`conhecimento.escolher`) com o mesmo filtro de papel e o mesmo teto;
   - dimensão do vetor guardado ≠ do vetorizador (ex.: indexado no modo falso) → busca por palavras **e** marca os
     documentos para reindexar + evento `base_dimensao_diferente` (hoje a base some sem aviso).
6. Documentos ainda em `processando`/`erro` entram pela busca por palavras, dentro do mesmo teto (como hoje).

Divisão em trechos (indexação):
- documentos: ~1.000 caracteres, 150 de sobreposição, cortando em parágrafo/frase; o texto **vetorizado** começa com
  `Documento: <nome> > <título da seção mais próxima>` (linha em maiúsculas, linha terminada em ":" ou markdown `#`);
- FAQ: um trecho por item, `Pergunta: ...\nResposta: ...`;
- objeção: um trecho por item, `Objeção do lead: ...\nComo responder: ...`.

---

## 5. Como entra no prompt e a regra anti-alucinação

**No SISTEMA (fixo por papel, aproveita o cache de prompt):**

```
# FATOS DO ESCRITÓRIO: DE ONDE PODEM VIR
Valores, prazos, documentos, endereço, horários, regras do benefício e como o escritório trabalha só podem vir de:
o roteiro desta etapa, DADOS DO ESCRITÓRIO, FATOS DO SISTEMA ou a BASE DE CONHECIMENTO enviada no turno.
Se o lead perguntar algo que não está em nenhum desses: não invente, não estime, não use conhecimento geral de
internet como se fosse do escritório. Diga em 1 frase que vai confirmar com a equipe, volte para a pergunta da etapa
e preencha "base.sem_resposta" com a pergunta do lead.
O roteiro manda mais que a base. Use a base em 1 ou 2 frases, com suas palavras, e volte para a etapa.
```

**No CONTEÚDO do turno** (logo antes de "MENSAGENS NOVAS DO LEAD"), só quando algum trecho passou:

```
BASE DE CONHECIMENTO DO ESCRITÓRIO (achada para a mensagem nova; use só isto para fatos do escritório):
[1] FAQ: Quanto o escritório cobra?
    30% do retroativo, só no êxito...
[2] Documento: Contrato padrão > Documentos necessários
    RG ou CNH, comprovante de residência...
```

Sem trecho nenhum, o bloco vem como `BASE DE CONHECIMENTO: nada encontrado para esta mensagem.` quando houve consulta
(assim a IA sabe que não há fonte e aplica a regra), e não aparece quando não houve consulta.

**Saída do agente** (esquema JSON do agente clássico e do catálogo) ganha um campo opcional:

```json
"base": {"usados": [1, 2], "sem_resposta": ""}
```

O turno:
- grava em `agentesia_turnos.contexto.conhecimento`: consulta, gatilho (consultou/pulou), trechos com id, nota, fonte,
  e o `usados` da IA (auditoria e avaliação pelo juiz);
- se `sem_resposta` vier preenchido → upsert em `agentesia_conhecimento_lacunas` (soma `vezes`) e evento `pergunta_sem_resposta`
  (gravidade `info`, responsável `cadastro`); o painel mostra "Perguntas sem resposta" com botão "Responder e virar FAQ".

O **auditor** recebe os mesmos trechos como fonte. Valor em R$, porcentagem, prazo em dias/meses ou endereço na resposta
que não aparece em nenhuma fonte (roteiro, dados, fatos, base) → recusa e pede reescrita (extensão do guarda
`endereco_sem_fonte` de `turno.py`, que já usa o texto da base como fonte).

---

## 6. O que fica fixo no prompt e o que vai para a base

| Conteúdo | Onde | Motivo |
|---|---|---|
| Roteiro/instrução da etapa | Sistema (fixo) | É o que manda. |
| Regras gerais, formato, regra anti-alucinação | Sistema (fixo) | Iguais em todo turno; cache. |
| DADOS DO ESCRITÓRIO (nome, endereço, horário, canais, OAB) | Sistema (fixo, até 1.500 caracteres) | Pequeno e perguntado o tempo todo. Acima disso, o excedente vira documento. |
| Honorários | Conteúdo, nas etapas com valores (como hoje) | Já controlado pelo produto. |
| FAQ e objeções **do papel** que somam até 3.000 caracteres | Sistema (fixo por papel) | Pouco texto, zero risco de a busca errar, cache. |
| FAQ e objeções acima disso | Base (busca) | Escala sem limite de 40/30 e sem cortar em silêncio. |
| Documentos (PDF, Word, texto) | Base (busca) | Sempre. Se todos os do papel somarem até 2.000 caracteres, ficam fixos. |
| Fatos do lead e do sistema | Conteúdo (como hoje) | São do lead, não do escritório. |

A regra "pequeno fica fixo, grande vai para a busca" é por papel: o closer com 6 objeções curtas tem tudo fixo; o SDR com
60 FAQ busca. O painel mostra em cada item se ele está "sempre no prompt" ou "buscado quando perguntarem".

---

## 7. Cache e reindexação

- **Trechos por agente** em memória (como hoje, 60 s), com os vetores já normalizados; a chave inclui a "versão da base"
  (`max(atualizado_em)` dos documentos do agente), então edição no painel vale no próximo turno, sem esperar 60 s.
- **Embedding de trecho**: `hash` = sha256(modelo + texto vetorizado). Ao reindexar, trechos com hash já existente no agente
  copiam o vetor; só os novos vão para a API. Editar 1 FAQ vetoriza 1 trecho.
- **Embedding da consulta**: LRU em memória (2.000 entradas, 1 h) pela consulta normalizada. "Quanto custa?" repete muito.
- **Quando reindexa**:
  - documento enviado/editado → `situacao = 'processando'` (como hoje; tarefa `indexar_conhecimento` a cada 30 s ou na hora);
  - PATCH da aba Conhecimento (FAQ/objeções/papéis) → os documentos virtuais `faq`/`objecoes` voltam para `processando`;
  - mudar só `papeis` de um documento → atualiza `papeis` dos trechos, sem vetorizar;
  - modelo de embedding diferente do gravado, ou dimensão diferente → reindexa tudo do agente e avisa;
  - ativação de produto do catálogo → copia os documentos padrão com o `papeis` do catálogo (já existe a cópia).
- Custo de indexar: 1 milhão de caracteres ≈ 250 mil tokens ≈ US$ 0,005.

Importação da base do Weaver (quando autorizado, só leitura): ler `grupo_conhecimentos.conteudo` (texto inteiro) e criar
`agentesia_documentos` com `id_externo`, deixando o nosso indexador dividir em trechos de 1.000 com título. Não copiar os
vetores de lá: os trechos de 3.000 não servem para o novo corte e não há garantia de que o modelo da consulta no n8n era o 3-small.
Custo de vetorizar de novo é desprezível.

---

## 8. Calibração da nota mínima (antes de ligar em produção)

Um conjunto pequeno em `avaliacao/base/`: ~40 perguntas reais (sem dados de lead) com o trecho esperado ou "nenhum",
para 2 escritórios. Script vetoriza com o modelo real (custo < US$ 0,01), mede para cada corte (0,25 a 0,50):
acerto do primeiro trecho, trechos irrelevantes por turno, e casos "nenhum" que ainda trouxeram algo.
Escolhe o menor corte com ≤ 1 trecho irrelevante médio e grava em `vetores.LIMIAR_MINIMO`.
A avaliação (`app/avaliacao/montagem.py`) passa a rodar com o vetorizador real (ou com o falso e o limiar dele), para que as
notas reflitam a busca de produção.

---

## 9. Tabela por agente

Papel = código da etapa (`sdr`, `periododegraca`, `closer`, `contratos`, `assinatura`, `desqualificado` no catálogo; as etapas
do Auxílio-Acidente clássico no produto próprio).

| Agente / papel | O que consulta (escopo) | Fixo no prompt | Exemplos de perguntas que a base deve responder |
|---|---|---|---|
| **SDR** (qualificação) | FAQ e documentos "todos" + marcados `sdr`; regras do benefício | Dados do escritório; FAQ curta do SDR | "Precisa ir no escritório?" · "Vocês atendem minha cidade?" · "Auxílio-acidente acumula com salário?" · "Acidente fora do trabalho dá direito?" · "Quanto tempo demora?" |
| **Período de graça** | Documentos de qualidade de segurado, FAQ `periododegraca` | Dados; regras curtas do período de graça | "Fiquei 2 anos sem contribuir, ainda tenho direito?" · "Seguro-desemprego conta?" · "Contribuí como MEI, vale?" |
| **Closer** | FAQ de honorários e funcionamento, objeções `closer`, documentos "todos" | Dados; objeções do closer se couberem; honorários (conteúdo) | "Quanto vocês cobram?" · "Tem que pagar adiantado?" · "E se eu perder?" · "Isso é golpe?" · "Vocês têm OAB?" |
| **Contratos** | FAQ e documentos `contratos` (documentos aceitos, cláusulas), objeções de documentos | Dados; lista de documentos se curta | "Foto do RG serve?" · "Comprovante tem que estar no meu nome?" · "Não tenho laudo, e agora?" · "O contrato tem multa?" |
| **Assinatura** | FAQ `assinatura` (ZapSign, passo a passo), objeções de segurança | Dados; passo a passo se curto | "Como assino pelo celular?" · "O link expira?" · "Precisa de certificado digital?" · "É seguro assinar online?" |
| **Desqualificado** | FAQ `desqualificado` (outros serviços, quando tentar de novo), documentos "todos" | Dados | "Por que não tenho direito?" · "Vocês fazem outro tipo de ação?" · "Posso tentar depois?" |
| **Auxílio-Acidente clássico** (etapas próprias) | Mesmo esquema, papel = etapa atual | Dados; FAQ curta | Iguais ao SDR e ao closer, conforme a etapa |
| **Extrator** | Não consulta | — | Só lê a fala do lead. |
| **Auditor** | Recebe os mesmos trechos do turno como fonte | — | Confere se valor, prazo e endereço da resposta estão em alguma fonte. |
| **Formatador, resumo, follow-up** | Não consultam | — | Follow-up usa modelos aprovados; resumo não afirma fatos do escritório. |

---

## 10. Medidas do protótipo local (sem API)

Script descartável no scratchpad da sessão (`proto_base.py`), com o VetorizadorFalso. Serve para testar a lógica, não para
as notas reais.

- Filtro local: "oi bom dia" e "ok" → não consulta (custo zero).
- Escopo por papel: "quais documentos tenho que mandar" → nada no `sdr`, FAQ de documentos no `contratos` (nota 0,50).
- "Tenho medo de ser golpe" no closer → só a objeção certa. "Meu cachorro fugiu" → nada.
- "Fiquei 2 anos sem contribuir" → nada com o vetor falso ("contribuir" ≠ "contribuições"), e "quanto vcs cobram?" pegou
  um trecho errado por colisão de hash. Isso confirma que o vetorizador falso não serve para calibrar e que a nota mínima
  precisa ser medida com o modelo real (seção 8). No modo falso, o padrão deve ser a busca por palavras.
- Tempo: 500 trechos × 1536 dimensões = 68 ms com `vetores.cosseno` e 23 ms com `math.sumprod` sobre vetores já
  normalizados (Python 3.12 do .venv). Sem numpy e sem pgvector, está dentro do orçamento do turno.

---

## 11. Estado da implementação (25/11/2026)

Feito (passos 1 a 9 do plano), sem chamar API:

- `db/migracoes/003_agentesia_conhecimento.sql` e `desfazer_003.sql` (testadas no PGlite: `db/testes/teste_migracoes.mjs`;
  `servidor_local.mjs` já aplica a 003).
- `app/conhecimento.py`: trechos de 1.000/150 com "Documento > Seção", `precisa_consultar`, `montar_consulta`,
  `ultima_pergunta_da_ia`, `reforco_lexico`, `montar_bloco` numerado, `REGRA_FONTES`, `fato_sem_fonte`.
- `app/vetores.py`: `LIMIAR_MINIMO = 0.35`, `normalizar`/`produto` (`math.sumprod`), `hash_do_texto`, `CacheDeConsultas` (LRU 2.000/1 h).
- `app/conhecimento_indice.py`: `preparar` (fixo × buscado por papel), `buscar` (paralela ao extrator, queda para palavras),
  `escolher_por_vetor`, `limites` (teto_documentos, trechos_por_turno, nota_minima por agente), `indexar_pendentes` com
  reaproveitamento por hash e documentos virtuais, `sincronizar_virtuais`, `trechos_do_agente` (escopo agente + escritório,
  cache pela versão da base), `marcar_para_reindexar`, `registrar_lacuna`.
- `app/cerebro/base_conhecimento.py` + ajustes mínimos em `agente.py`, `turno.py` e `pipeline.py`: regra no sistema, bloco no
  conteúdo, campo `base` na saída, `contexto.conhecimento` no turno, evento `pergunta_sem_resposta`, custo do embedding da
  consulta em `agentesia_chamadas_ia` (`conhecimento_consulta`) e no consumo, guarda `fato_sem_fonte` (leve) no catálogo.
- Rotas: `papeis` por documento (envio e `PUT .../papeis`), `papeis` por item de FAQ/objeção, limites mantidos no PATCH,
  `GET/POST /agentes/{id}/lacunas` (listar, responder = vira FAQ, ignorar). Painel: papéis por item e por documento, selo
  "sempre no prompt"/"buscado", tela "Perguntas sem resposta".
- Testes: `tests/test_base_conhecimento.py` (sem banco) e `tests/test_base_conhecimento_pg.py` (com AGENTESIA_TESTE_PG_URL).
- Teste real com teto: `scripts/testar_base_conhecimento.py --teto-usd 0.30` (COM × SEM, juiz); `--falso` prova o script sem API.

Ficou de fora: o auditor (ele confere sinais, não fatos; a conferência de fato ficou no guarda `fato_sem_fonte`), o guarda de
fonte no agente clássico (o clássico já tem a trava de honorários), a calibração real do `LIMIAR_MINIMO` (passo 10) e a
importação da base do Weaver (passo 11).
