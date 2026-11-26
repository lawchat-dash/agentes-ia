# API de produtos, ativação, mídia e conhecimento (contrato do painel)

Telas copiadas do `agents-lawchat-main` (pasta `painel/src/components`, `pages`, `hooks`) falam com estas rotas.
Todas sob `/api`, com o cliente `api()` / `enviar()` de `painel/src/api.ts` (manda `X-Escritorio` sozinho).
As linhas voltam **com os mesmos nomes de colunas das tabelas `sistemaia_*` do sistema de referência**
(em português), mais `created_at` / `updated_at` (apelidos de `criado_em` / `atualizado_em`) e `id_conta` (= `id_escritorio`).
Assim as funções de mapeamento dos hooks de lá (`mapBibliotecaProduto`, `mapProdutoAtivado`…) ficam iguais.

Tabelas (migração 002): `agentesia_biblioteca_produtos`, `agentesia_biblioteca_agentes`, `agentesia_frases_troca`,
`agentesia_produtos_ativados`, `agentesia_biblioteca_midia`, `agentesia_documentos` (+ `agentesia_documento_trechos`).

## Catálogo (qualquer usuário logado)
| Método | Rota | Corpo / resposta |
|---|---|---|
| GET | `/biblioteca/produtos` | linhas de `biblioteca_produtos` com status `publicado` ou `em_breve` (equipe LawChat com `?todos=1` recebe também `rascunho`), ordenadas por nome |
| GET | `/biblioteca/produtos/{slug_ou_id}` | uma linha (404 se não existe ou é rascunho para cliente) |
| GET | `/biblioteca/produtos/{id}/agentes` | linhas de `biblioteca_agentes` do produto, por `ordem` |
| GET | `/biblioteca/produtos/{id}/documentos` | documentos padrão do produto: `{id, nome, tipo, formato, tamanho_bytes, caracteres, created_at}` |
| GET | `/biblioteca/frases-troca?id_produto=` | linhas de `frases_troca` (globais + do produto) |

## Admin do catálogo (equipe LawChat)
| Método | Rota | Corpo / resposta |
|---|---|---|
| POST | `/admin/biblioteca/produtos` | colunas do produto → linha criada |
| PATCH | `/admin/biblioteca/produtos/{id}` | colunas a mudar → linha |
| DELETE | `/admin/biblioteca/produtos/{id}` | `{ok}` |
| POST | `/admin/biblioteca/produtos/{id}/duplicar` | → linha nova (rascunho, slug `-copia-xxxx`, agentes copiados) |
| POST | `/admin/biblioteca/produtos/padrao` | `{nome, area_juridica, categoria, descricao}` → produto com os 5 agentes padrão |
| PUT | `/admin/biblioteca/produtos/{id}/agentes` | `[{papel, nome_exibicao, descricao, icone, ordem, blocos_prompt, texto_prompt, mensagem_boas_vindas, config_modelo, regras_handoff}]` (upsert por papel; papel ausente é apagado) → linhas |
| PUT | `/admin/biblioteca/frases-troca` | `{id?, id_produto_biblioteca?, etapa_destino, nome, frase, descricao?, ordem?}` → linha (propaga o texto novo para os prompts dos agentes já ativados daquele produto) |
| DELETE | `/admin/biblioteca/frases-troca/{id}` | `{ok}` |
| POST | `/admin/biblioteca/produtos/{id}/documentos` | `{nome, tipo:'arquivo'|'texto', conteudo_base64?, texto?, mime?}` → documento |
| DELETE | `/admin/biblioteca/produtos/{id}/documentos/{id_doc}` | `{ok}` |

## Produtos ativados (escritório; gestor ou equipe)
| Método | Rota | Corpo / resposta |
|---|---|---|
| GET | `/produtos-ativados?lixeira=0|1` | linhas com `biblioteca: {id, slug, nome, icone, capa_gradiente, descricao_curta, categoria, versao, oferece_periodo_graca, modo_midia}`, `followup: null` e `followup_situacao: {ligado, configurado, passos, resumo}` (null sem agente; ver docs/FOLLOWUP.md) |
| GET | `/produtos-ativados/{id}` | linha + `etapas: [{id, etapa, ordem, prompt, config, mensagem_troca, nome}]` (do agente criado) + `variables` |
| POST | `/produtos-ativados/rascunho` | `{id_produto_biblioteca}` → acha ou cria o rascunho do escritório para o produto (copia faq, objeções, regras e dados do catálogo) |
| PATCH | `/produtos-ativados/{id}` | qualquer de: `nome, descricao, faq, objecoes, conhecimento, dados_escritorio, regras_markdown, integracoes, numero_ia, rascunho, status, versao_template, periodo_graca_ativo, excluido_em` → linha. `excluido_em` (qualquer valor verdadeiro) = lixeira: o servidor grava `now()`, pausa o agente, **solta o número** (agente sem `id_canal`, o anterior vai para `id_canal_anterior`), cancela os follow-ups pendentes e tira o número da ativação salva. `excluido_em: null` = restaurar: volta pausado e sem número (`precisa_ativar: true`). A linha traz `precisa_ativar` e `numero_liberado`. |
| POST | `/produtos-ativados/{id}/ativar` | payload do assistente (abaixo) → `{ok, id_agente, verificacao}`; cria o agente, as etapas e copia os documentos padrão |
| POST | `/produtos-ativados/{id}/sincronizar` | mesmo payload (modo edição) → `{ok}`; atualiza prompts e configurações do agente |
| POST | `/produtos-ativados/{id}/status` | `{status: 'ativo'|'pausado'}` → linha. `ativo` com `precisa_ativar` (ou na lixeira) → 409: escolha o número no editor. |
| DELETE | `/produtos-ativados/{id}` | exclusão definitiva: libera o número sempre; apaga o agente sem leads, ou o deixa pausado e sem número |

Payload de ativar/sincronizar:
```json
{ "nome": "Júlia", "numero_ia": "5531985830725", "id_canal": "<agentesia_canais.id>",
  "delay_s": 10, "pausa_min": 30, "temperatura": 0.7, "modelo": "gpt-4.1-mini", "ativar_imediatamente": true,
  "periodo_graca_ativo": false,
  "agentes": [{ "papel": "sdr", "nome": "SDR — Qualificação", "boas_vindas": "...", "prompt": "<markdown já expandido>", "mensagem_troca": "frase de entrada" }],
  "faq": [{"pergunta":"","resposta":""}], "objecoes": [{"titulo":"","resposta":""}],
  "regras_markdown": "", "dados_escritorio": "", "variables": {"CAMPO": "valor"} }
```

## Números (canais)
| GET | `/canais/disponiveis` | `[{id, numero, numero_formatado, nome, tipo, id_canal_helena, disponivel, em_uso_por}]` |
| POST | `/integracoes/helena/canais` | (já existe) sincroniza com a Helena |

## Biblioteca de mídia (escritório)
| GET | `/midia` | `{itens: [linha], usado_bytes, limite_bytes}` (limite 200 MB) |
| POST | `/midia` | `{nome, conteudo_base64, mime}` (≤ 50 MB; áudio ogg/oga/opus/mp3/wav/m4a/aac/flac, vídeo mp4/webm/mov, imagem jpg/jpeg/png/webp) → linha com `url` pública |
| PATCH | `/midia/{id}` | `{nome}` → linha |
| DELETE | `/midia/{id}` | `{ok}` |
O caminho é `{escritorio}/{tipo}/{uuid}-{nome}.{ext}` (vai em `caminho_storage`). A URL pública (em `url`) depende de
`AGENTESIA_MIDIA_ARMAZENAMENTO` (`app/armazenamento.py`): `supabase` =
`{AGENTESIA_SUPABASE_URL}/storage/v1/object/public/{AGENTESIA_MIDIA_BUCKET}/{caminho}`; `local` (padrão) =
`{AGENTESIA_URL_PUBLICA}/midia/{caminho}` (servida pelo próprio servidor).

## Conhecimento do agente
| GET | `/agentes/{id}/documentos` | `[{id, nome, tipo, formato, tamanho_bytes, caracteres, situacao:'processando'|'pronto'|'erro', erro, tokens, origem, travado, created_at, previa}]` |
| POST | `/agentes/{id}/documentos` | `{nome, conteudo_base64, mime}` (arquivo) ou `{nome, tipo:'texto', texto}` (colar texto) |
| DELETE | `/agentes/{id}/documentos/{id_doc}` | só se não travado |
| POST | `/agentes/{id}/documentos/{id_doc}/reprocessar` | volta para `processando` |

## ZapSign (já existe)
`GET /integracoes/zapsign`, `PUT /integracoes/zapsign` (token), `GET /integracoes/zapsign/modelos`, `PUT /integracoes/zapsign/config`.

## Planos
Não há planos aqui: `usePlanGate` / `usePlanFeatures` devolvem sempre liberado.

## Pedidos do porte (assistente)
Usados pelas telas `pages/Ativar.tsx`, `pages/ProdutoEditor.tsx` e `components/agent/ProductConfigurator.tsx`.

| Método | Rota | Corpo / resposta |
|---|---|---|
| GET | `/produtos-ativados/{id}` | além do já descrito, a linha traz `dados_escritorio`, `rascunho` e **`agente: {id, modelo, temperatura, delay_s, pausa_min, id_canal} \| null`** (comportamento atual do agente criado). O modo edição lê daí modelo/temperatura/delay/pausa; sem isso cai nos padrões (gpt-4.1-mini, 0.7, 10 s, 30 min) e sobrescreve o valor real ao salvar. `useProducts.mapProdutoAtivado` precisa repassar `dados_escritorio`, `rascunho`, `agente` e `id_canal`. |
| GET | `/canais/disponiveis` | `numero` em dígitos (é o que vai em `numero_ia`); `em_uso_por` = **id do agente** que usa o número (o editor reconhece "Número atual deste agente" comparando com `id_agente` do produto). |
| POST | `/produtos-ativados/{id}/ativar` | resposta de sucesso `{ok: true, id_agente, verificacao}`; falha = HTTP 4xx/5xx com `detail` (texto mostrado no overlay de erro) **ou** `{ok: false, erro}`. O servidor marca o produto como `falhou` quando não termina (a tela não grava mais `status_provisionamento`). |
| POST | `/produtos-ativados/{id}/sincronizar` | mesmo payload, **sem** `ativar_imediatamente` (editar não muda o status). `numero_ia`/`id_canal` diferentes do atual = trocar o canal do agente (falhou → nada é salvo, responde erro). Produto com `precisa_ativar` (voltou da lixeira): é a reativação — exige o número, aceita `ativar_imediatamente` (padrão true; false = pausado), reaproveita o agente/prompts/documentos/contrato; número em uso por outro agente → 409. O agente que assume um número herda os leads dele (entram na etapa inicial; estado e conversa ficam). |

Detalhes do payload montado pela tela:
- `agentes[].prompt` = blocos do prompt (sem o `handoff_trigger`) com `@Transferência: X` → frase exata e `@Agente X`/ferramentas → ``acionar tool `x` ``, unidos por `\n`. No modo edição a tela faz o caminho inverso com `recolherHandoffsDoBot(etapas[].prompt)`, então `etapas[].prompt` deve voltar exatamente o texto recebido.
- `agentes[].mensagem_troca` = frase de entrada da etapa (frase cadastrada em `frases-troca` para a etapa; senão o gatilho do agente; Assinatura nunca vazia). `etapas[].mensagem_troca` volta esse texto.
- `etapas[].nome` = `agentes[].nome` recebido (o editor mostra esse nome; se vazio usa o do catálogo). `etapas[].config.boas_vindas` (ou `welcome_message`) = `agentes[].boas_vindas`.
- `numero_ia` vai só com dígitos; `id_canal` vem de `/canais/disponiveis` pelo número.
- `periodo_graca_ativo` = o funil tem o agente `periododegraca`.
- O rascunho do assistente é salvo com `PATCH /produtos-ativados/{id}` (`nome, regras_markdown, faq, objecoes, conhecimento, dados_escritorio, integracoes, numero_ia, rascunho`). O jsonb `rascunho` guarda `catalogStamp` (maior `updated_at` entre `GET /biblioteca/produtos/{id}` e as linhas de `/agentes`): as duas rotas precisam devolver `updated_at`.

ZapSign: `GET /integracoes/zapsign` **não existe** em `app/gestao/rotas.py`; a tela lê o estado em `GET /integracoes` (`integracoes.zapsign` → `situacao, final_segredo, tem_segredo, config`). O token nunca volta ao navegador. O modelo escolhido no diálogo é gravado com `PUT /integracoes/zapsign/config {modelos: [{id_modelo, nome, padrao: true, mapeamento: [{variavel, campo}]}]}` (só as variáveis que o servidor sabe preencher). Não há rota para apagar o token ("Desconectar" só desliga a ZapSign no produto).
