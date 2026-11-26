# Fluxo n8n "WEAVER - Arquivos Transcrição PDF": especificação para a reescrita

Fonte: export `WEAVER - Arquivos Transcrição PDF.json` (ativo, tag "99 - Novo", `executionOrder: v1`, `binaryMode: separate`).
`pinData` foi ignorado. Nenhum segredo foi copiado: onde há um, aparece `<SEGREDO: tipo>`.

> **Aviso de escopo.** Apesar do pedido falar em áudio e imagem, **este fluxo só trata documentos**
> (TXT, Markdown, DOC, DOCX, PDF, XLSX). Não há nenhum ramo de áudio ou imagem: esses MIME types
> não casam com nenhuma regra do Switch e a execução termina sem saída. No sistema antigo o áudio
> vinha transcrito pela própria Helena (`content.details.transcription.text`, que o
> `app/canal/helena.py` já usa) e a imagem era tratada (ou não) no `99 - Fluxo Principal`.
> A seção 9 propõe áudio e imagem como **novidade**, separada do que o fluxo antigo fazia.

---

## 1. Objetivo

Subfluxo chamado pelo fluxo principal quando o lead envia um arquivo. Recebe o link e o MIME type,
baixa o arquivo, extrai o texto conforme o tipo, corrige problemas de codificação (mojibake) e:

- se o texto tem **menos de 2000 caracteres**, devolve o texto como está;
- se tem **2000 ou mais**, pede a um modelo da OpenAI um resumo estruturado de até ~2000
  caracteres (pensado para autos de processo do PJe) e devolve o resumo.

O texto devolvido entra na conversa como se fosse o conteúdo da mensagem do lead.

## 2. Gatilho e entrada

| Item | Valor |
|---|---|
| Nó | `Weaver` (`executeWorkflowTrigger` v1.2): só roda quando outro fluxo o chama (Execute Workflow) |
| Entradas declaradas | `Doc`, `MimeType`, `CompanyId` (todas texto) |
| `Doc` | URL pública do arquivo. Na Helena é `content.details.file.publicUrl` (CDN `cdn.flw.chat` ou URL assinada do S3, segundo o comentário do código) |
| `MimeType` | MIME type informado pela Helena. O próprio código avisa que **não é confiável**: a Helena pode mandar `text/plain` e o S3 responder `application/octet-stream` para o mesmo arquivo |
| `CompanyId` | Declarado, **não é usado** em nenhum nó deste fluxo |

Exemplo de item de entrada (formato, sem dados reais):

```json
{ "Doc": "https://<cdn>/<caminho>/<arquivo>.pdf", "MimeType": "application/pdf", "CompanyId": "<id da conta>" }
```

## 3. Lógica passo a passo

### 3.1 Roteamento por tipo (nó `Switch`, v3.2)

Comparação **exata e sensível a maiúsculas** de `$json.MimeType`. Sem saída de fallback e sem
"todas as saídas que casarem": vale a primeira regra que casar.

| # | Saída | MIME | Vai para |
|---|---|---|---|
| 0 | `.TXT` | `text/plain` | `Download Arquivo4` → `Doc → Texto` |
| 1 | `.md` | `text/markdown` | `Download Arquivo4` → `Doc → Texto` |
| 2 | `msword` | `application/msword` | `Download Arquivo` → `MSWord (.doc) → Texto` |
| 3 | `PDF` | `application/pdf` | `Download Arquivo1` → `Extract from File` (pdf) → `Arruma PDF Extraido` |
| 4 | `XLSX` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | `Download Arquivo3` → `Extract from File1` (xlsx) → `Aggregate` → `Summarize1` → `Code` |
| 5 | `Google Sheet` | `application/vnd.google-apps.spreadsheet` | igual ao XLSX |
| 6 | `.DOCX` | `=text/plain` (expressão, vira `text/plain`) | `Download Arquivo2` → ramo DOCX. **Regra morta**: `text/plain` já casa na regra 0 |
| 7 | `.DOCX` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `Download Arquivo2` → ramo DOCX |

Qualquer outro MIME (imagem, áudio, vídeo, `application/zip`, `application/octet-stream`, MIME com
`; charset=...`) não sai do Switch: a execução termina sem item e quem chamou recebe vazio.

Todos os ramos terminam no nó `If` (seção 3.8).

### 3.2 Download (nós `Download Arquivo`, `1`, `2`, `3`, `4`)

`GET` na URL, resposta como arquivo binário (`responseFormat: file`), sem cabeçalhos, sem
autenticação, sem nova tentativa, timeout padrão do n8n.
Ver seção 4 para o detalhe e o defeito do ramo XLSX.

### 3.3 Ramo TXT / Markdown (`Doc → Texto`, Code, "Run Once for All Items")

O código decide pelo **conteúdo** (magic bytes dos 8 primeiros bytes), não pelo MIME:

| Assinatura (hex) | Tratamento |
|---|---|
| `D0CF11E0` | É `.doc` legado (OLE2): extrai como no ramo 3.4 |
| `504B0304` | É ZIP (docx): erro "use a rota Google Drive" (resto de versão antiga) |
| `25504446` (`%PDF`) | Erro "coloque um Extract from File antes" |
| outra | Texto puro (abaixo) |

Texto puro, decodificação:
1. BOM `EF BB BF` → UTF-8 sem o BOM.
2. BOM `FF FE` → UTF-16 LE; BOM `FE FF` → UTF-16 BE.
3. Sem BOM: tenta UTF-8; se aparecer `U+FFFD` (caractere inválido), decodifica como Windows-1252.

Limpeza (`limpar`): `\r\n`/`\r` → `\n`; remove `U+FEFF`; tira espaços/tabs no fim da linha;
3+ quebras seguidas viram 2; `trim`. Texto vazio é erro.

O código também sabe buscar a URL sozinho (campos `Doc`, `doc`, `url`, `fileUrl`, `link`... ou
varrendo o JSON até profundidade 8), mas neste fluxo o binário já chega do download, então esse
caminho não é usado. Saída: `{ text }`.

### 3.4 Ramo DOC legado (`MSWord (.doc) → Texto`, Code)

Parser OLE2 (Compound File Binary) + Word 97, escrito à mão em JS, sem dependências:

1. Confere a assinatura `D0CF11E0A1B11AE1`. Se vier `504B0304` (docx), erro. Se não for nenhuma
   das duas, trata como texto (UTF-8, ou latin-1 se houver `U+FFFD`).
2. Lê cabeçalho OLE2 (setor, mini setor, FAT, DIFAT, diretório, mini FAT, corte de mini stream).
3. Abre o stream `WordDocument`; confere o FIB `0xA5EC`.
4. Escolhe a tabela `1Table` ou `0Table` pelo bit `0x0200` do FIB (`fWhichTblStm`).
5. Percorre o FIB dinamicamente até `ccpText` (tamanho do corpo principal) e `fcClx`/`lcbClx`.
6. No Clx, pula os `grpprl` (tipo 1) até achar a piece table `PlcPcd` (tipo 2).
7. Para cada peça: se o bit `0x40000000` do `fc` estiver ligado, é texto comprimido de 8 bits
   (Windows-1252, offset `(fc & 0x3FFFFFFF) >> 1`); senão, UTF-16 LE.
8. Corta em `ccpText` (só o corpo; tira cabeçalho, rodapé e notas).
9. Limpa: remove campos do Word (`\x13 ... \x15`, ex.: MERGEFIELD, HYPERLINK); `\x07` (fim de
   célula) → `\n`; `\x0B`, `\x0C`, `\r` → `\n`; remove `\x01 \x02 \x05 \x08 \x1E \x1F ﻿`;
   `\xA0` → espaço; espaços no fim da linha; 3+ quebras → 2; `trim`.
10. Texto com menos de **20 caracteres** é erro.

Saída: `{ ...entrada, data, text, _formato, _bytes, _caracteres }` (só `text` importa depois).

### 3.5 Ramo DOCX (descompressão)

1. `Renomeia para ZIP` (Code): troca nome `.docx` → `.zip`, extensão `zip`, MIME `application/zip`
   (só para o nó de compressão aceitar).
2. `Descompacta ZIP` (`compression` v1.1, padrão: descompactar): vira um binário por arquivo interno.
3. `Isola document.xml` (Code): pega o primeiro binário cujo nome termina em `document.xml`
   (ou seja, `word/document.xml`). Se não achar: erro "word/document.xml nao encontrado no arquivo."
4. `Le XML como texto` (`extractFromFile`, operação `text`): binário → string.
5. `XML para Texto + Corrige` (Code):
   - XML → texto: `</w:p>` → `\n`; `<w:br/>` → `\n`; `<w:tab/>` → `\t`; remove todas as tags;
     decodifica `&amp; &lt; &gt; &quot; &apos;` e entidades numéricas decimais e hexadecimais;
     3+ quebras → 2; `trim`.
   - Corrige mojibake "Windows-1252 lido como UTF-8": recodifica cada caractere para o byte
     cp1252 correspondente e decodifica de novo como UTF-8. Remendos: `CR�TICA` → `CRÍTICA`,
     `U+FFFD` restante → `à`, `à` + vários espaços → `à `.

Saída: `{ text }`. Cabeçalhos, rodapés, notas e caixas de texto fora de `document.xml` ficam de fora.

### 3.6 Ramo PDF (extração)

1. `Extract from File` (operação `pdf`, campo binário `data`): texto da camada de texto do PDF
   (pdf.js do n8n). **Não há OCR**: PDF escaneado (só imagem) sai com texto vazio ou quase vazio.
2. `Arruma PDF Extraido` (Code, um item por vez): corrige o mojibake que o pdf.js produz em PDFs
   brasileiros. Substituições de string, **das chaves mais longas para as mais curtas**:
   - `õ` corrompido: `çÍμ`→`çõ`, `Íμ`→`õ`, `Ã§Ãμ`→`çõ`, `Ã‡Ã•`→`ÇÕ`, `Ãμ`→`õ`;
   - maiúsculas: `ÇÍO`→`ÇÃO`, `SÍO`→`SÃO`, `NÍO`→`NÃO`;
   - mojibake clássico de minúsculas (`Ã¡`→`á`, `Ã©`→`é`, `Ã§`→`ç`, `Ã£`→`ã`, `Ãµ`→`õ`... 20 pares)
     e de maiúsculas (`Ã‰`→`É`, `Ã‡`→`Ç`... 13 pares);
   - pontuação: `â€"`→`—`, `â€¢`→`•`, `â€œ`→`“`, `â€™`→`’`, `â€˜`→`‘`, `â€¦`→`…`;
   - `Í`→`í` (depois das maiúsculas acima); `Â` parasita → vazio.
   Depois, regex: `Ã` + minúscula → `í`; `â†` + 1 caractere → `→`; `â€` + 1 caractere → `”`;
   `aàé` → `aí é`; `à` colado na palavra seguinte → `à `; remove `U+FFFD` e controles
   (`\x00-\x08`, `\x0B`, `\x0C`, `\x0E-\x1F`).

Saída: `{ text }`.

### 3.7 Ramo XLSX / Google Sheet

1. `Extract from File1` (operação `xlsx`): um item por linha da **primeira planilha**, chaves = cabeçalho.
2. `Aggregate` (todos os dados dos itens): um item com `data = [linha1, linha2, ...]`.
3. `Summarize1`: concatena o campo `data` com separador `\n\n` → `concatenated_data`.
4. `Code`: `JSON.parse(concatenated_data)` e formata cada linha como
   `CHAVE_EM_MAIÚSCULAS: valor`, uma por linha, linhas da planilha separadas por linha em branco.

Saída: `{ text }`. O passo 3→4 depende de o Summarize transformar a lista em texto JSON; é frágil.

### 3.8 Decisão de tamanho e resumo (nós `If`, `AI Agent`)

- `If`: `$json.text.length < 2000` (número, estrito).
  - **verdadeiro** → `Volta para o Fluxo` (NoOp): devolve `{ text }` como está.
  - **falso** → `AI Agent` (resumo, seção 5) → saída `{ output }`, que vai para
    `Volta para o Fluxo1` (NoOp) e para `Contar Token SUBFLUXO`.
- Item com `_ok: false` (erro parcial do `Doc → Texto`) chega ao `If` sem `text`: a expressão
  `text.length` falha.

### 3.9 Nós sem efeito na execução

- `DECIDE TAGS DESQUALIFICADO` (HTTP para a OpenAI): **órfão**, sem conexões. Referencia nós que
  não existem aqui (`Receber Dados`, `Summarize`) e lê a chave da OpenAI de um campo do payload
  (`api_openai`, `<SEGREDO: chave OpenAI>`). É o "auditor de qualificação" de outro fluxo, colado
  aqui por engano. Não faz parte desta spec.
- `Sticky Note`, `Sticky Note1`: anotações (link para lista de MIME types; "pode criar novas rotas").

## 4. Chamadas externas

| Nó | Método | Host + caminho | Cabeçalhos | Corpo | O que se usa da resposta |
|---|---|---|---|---|---|
| `Download Arquivo`, `1`, `2`, `4` | GET | URL de `Doc` (CDN da Helena / S3 assinado) | nenhum | nenhum | bytes do arquivo (binário `data`) |
| `Download Arquivo3` (XLSX) | GET | `{{ $json.publicUrl }}` | nenhum | nenhum | bytes. **Defeito**: a entrada se chama `Doc`, não `publicUrl`; a URL sai vazia e o ramo XLSX falha |
| `OpenAI Chat Model` (via `AI Agent`) | POST | `api.openai.com/v1/chat/completions` (pelo nó LangChain) | `Authorization: Bearer <SEGREDO: credencial openAiApi do n8n>`, `Content-Type` | `model: gpt-4.1-mini`, mensagens `system` (prompt da seção 5) + `user` (texto extraído inteiro); sem temperatura, sem limite de tokens | `choices[0].message.content` → campo `output` |
| `Contar Token SUBFLUXO` | Execute Workflow | subfluxo `99 - CONTAR TOKEN` | — | `ExecutionId`, `executionMode`, `executionResumeUrl`, `$executionResumeFormUrl`, `Execution` (objeto inteiro da execução) | nada: `waitForSubWorkflow: false` (dispara e esquece). Contabiliza tokens nas tabelas do Weaver |
| `DECIDE TAGS DESQUALIFICADO` | POST | `api.openai.com/v1/chat/completions` | `Authorization: Bearer <SEGREDO: chave OpenAI vinda do payload>`, `Content-Type: application/json` | `gpt-4.1`, `temperature: 0` | órfão, nunca roda |

Downloads: o comentário do `Doc → Texto` lembra que a URL assinada do S3 deve ser usada **inteira**,
sem remontar a query string (a assinatura cobre a query).

## 5. Prompt de IA (nó `AI Agent`, modelo `gpt-4.1-mini`)

- Tipo: agente LangChain sem ferramentas e sem memória; na prática, uma chamada de chat.
- Entrada do usuário: `{{ $json.text }}` (texto extraído completo, sem corte).
- Intenção: resumir autos de processo judicial (PJe) para consulta rápida do advogado.
- Saída: **texto livre** em português, até ~2000 caracteres, em 3 blocos numerados. Não é JSON.

Prompt de sistema (íntegra):

```text
Você é um assistente jurídico especializado em resumir autos de processos judiciais brasileiros (formato PJe) extraídos em texto bruto via OCR, para uso interno de escritório de advocacia.

OBJETIVO: Gerar um resumo estruturado de até 2000 caracteres, em português, cobrindo os pontos essenciais do processo para consulta rápida por advogado(a).

FORMATO DE SAÍDA (nesta ordem):

1) DADOS DO PROCESSO
- Número do processo, vara/comarca, classe, assunto.
- Partes (autor x réu).
- Data de distribuição, se disponível.

2) DADOS DO CLIENTE (parte autora)
- Nome completo, profissão/ocupação.
- Dado relevante ao caso (ex: data do acidente, benefício já recebido/cessado, CID/lesão relatada, nexo com acidente de trabalho).
- Advogado(a) responsável.

3) RESUMO DO CASO
- Objeto da ação e causa de pedir, em 2-3 linhas.
- Cronologia essencial: contestação, decisões de competência, nomeação(ões) de perito e recusas, data da perícia realizada.
- Resultado da perícia judicial: conclusão médica objetiva (há ou não incapacidade/redução de capacidade), CID, nexo causal.
- Manifestações finais das partes após o laudo.
- Decisão/sentença: resultado (procedente/improcedente), fundamento principal em 1-2 linhas, condenações (honorários, custas, restituições).
- Situação atual (transitado em julgado, recurso pendente, arquivado, etc).

O QUE IGNORAR/RESUMIR AO MÍNIMO:
- Certidões cartorárias repetitivas (juntada, carga, remessa, termos de recebimento).
- Tabelas extensas de CNIS/remunerações e laudos administrativos repetidos ano a ano — mencionar apenas que existem, sem detalhar.
- Jurisprudência citada nas peças — no máximo o nome do tribunal e a tese, sem reproduzir ementas inteiras.

REGRAS:
- Seja direto e telegráfico; use frases curtas, não texto corrido longo.
- Nunca reproduza texto integral de petições, decisões ou sentenças — sempre parafraseie.
- Datas no formato dd/mm/aaaa.
- Se uma informação estiver ilegível ou ambígua no OCR, escreva "não identificado" em vez de supor ou inventar.
- Omita CPF, RG completos, endereços completos e dados bancários.
- Respeite rigorosamente o limite de ~2000 caracteres; se faltar espaço, priorize identificação do processo > dados do cliente > desfecho da ação, cortando histórico intermediário.
```

Observações: o prompt fala em OCR, mas o fluxo não faz OCR. E ele vale para qualquer documento
longo: um laudo, um CNIS ou uma carta do INSS de 2000+ caracteres também cai neste molde de
"autos do PJe".

## 6. Limites e constantes

| Constante | Valor | Onde |
|---|---|---|
| Corte para resumir | `text.length < 2000` devolve cru; `>= 2000` resume | `If` |
| Tamanho do resumo | ~2000 caracteres (pedido no prompt, não verificado no código) | `AI Agent` |
| Modelo do resumo | `gpt-4.1-mini` | `OpenAI Chat Model` |
| Texto mínimo do `.doc` | 20 caracteres | `MSWord (.doc) → Texto` |
| Assinaturas | OLE2 `D0CF11E0A1B11AE1`, ZIP `504B0304`, PDF `25504446`; FIB do Word `0xA5EC` | Code |
| DIFAT no cabeçalho OLE2 | 109 entradas; fim de cadeia `>= 0xFFFFFFFC` | Code |
| Timeout de download por URL | 30 s (só no modo URL do `Doc → Texto`, não usado aqui) | Code |
| Varredura de URL no JSON | profundidade máxima 8 | Code |
| `PARAR_NO_ERRO` | `false` (marca `_erro` e segue; só estoura se todos falharem) | `Doc → Texto` |
| Tamanho máximo de arquivo, páginas, timeout de download | **não há** | — |

## 7. Saída devolvida a quem chamou

O n8n devolve ao fluxo pai os itens do último nó executado. Formato na prática:

| Caso | Item devolvido |
|---|---|
| Texto curto (< 2000) | `{ "text": "<texto extraído e corrigido>" }` |
| Texto longo (>= 2000) | `{ "output": "<resumo do gpt-4.1-mini>" }` |
| MIME sem rota | nenhum item |
| Erro em nó | a execução falha; o nó Execute Workflow do pai recebe o erro |

O campo muda conforme o ramo (`text` ou `output`): o fluxo pai precisa ler os dois. Como o
`AI Agent` tem duas saídas finais (`Volta para o Fluxo1` e `Contar Token SUBFLUXO`), o item
devolvido depende da ordem de execução; os dois repassam o mesmo `{ output }`.

## 8. Tratamento de erro

- Nenhum nó tem `continueOnFail`, `onError` ou `retryOnFail`. Qualquer exceção para o subfluxo.
- Download com 4xx/5xx (link expirado, por exemplo): falha, sem nova tentativa.
- `Doc → Texto`: erros por documento viram item `{ _ok: false, _erro, _origem }` e seguem, a menos
  que todos falhem (aí lança "Nenhum documento pôde ser lido"). O item com erro quebra no `If`.
- `MSWord (.doc) → Texto`: lança erro em arquivo sem binário, docx disfarçado, OLE2 corrompido,
  piece table ausente ou texto < 20 caracteres.
- DOCX sem `word/document.xml`: lança erro.
- PDF escaneado: não é erro; sai texto vazio, que passa no `If` (0 < 2000) e volta vazio.
- MIME não mapeado: não é erro; termina sem saída.
- Falha da OpenAI: o `AI Agent` falha e o subfluxo inteiro falha (o texto extraído se perde).

---

## 9. Como fica no sistema novo

### 9.1 Princípios

- Um módulo novo, `app/midia/` (ou `app/ferramentas/arquivos.py`, que já se anuncia como lugar de
  "arquivos"). Nada de n8n, nada das tabelas do Weaver.
- Decidir o formato pelos **magic bytes**, com o MIME só como dica (o fluxo antigo aprendeu isso).
- O resultado vai para `agentesia_mensagens.texto_extraido` da própria mensagem (coluna já existe:
  "transcrição ou descrição da mídia"). Histórico, extrator e equipe leem dali via
  `Mensagem.para_a_ia()`; nada é processado duas vezes.
- Saída sempre no mesmo formato (o fluxo antigo alternava `text`/`output`).
- Falha nunca derruba o turno: vira um texto de aviso para a IA pedir de novo (DESENHO.md 11.2).

### 9.2 Funções (assinaturas)

```python
# app/midia/baixar.py
LIMITE_BYTES = 20 * 1024 * 1024
HOSTS_PERMITIDOS: tuple[str, ...]          # CDN da Helena e S3; evita SSRF com URL do webhook

async def baixar(url: str, http: httpx.AsyncClient, *, limite_bytes: int = LIMITE_BYTES,
                 tentativas: int = 2, timeout_s: float = 30) -> bytes:
    """GET da URL inteira (não remontar a query da URL assinada), em streaming, abortando acima do limite.
    Repete em erro de rede, 429 e 5xx. Lança ErroMidia('link_expirado' | 'grande_demais' | 'download')."""

# app/midia/formato.py
def detectar_formato(dados: bytes, mime: str | None, nome: str | None) -> str:
    """'pdf' | 'docx' | 'xlsx' | 'doc' | 'texto' | 'imagem' | 'audio' | 'desconhecido'.
    %PDF -> pdf; PK -> olha [Content_Types].xml / word/ ou xl/ dentro do zip; D0CF11E0 -> doc;
    JPEG/PNG/WEBP/GIF -> imagem; OGG/MP3/M4A/WAV -> audio; senão o MIME, senão tenta texto."""

# app/midia/extrair.py
def extrair_pdf(dados: bytes, *, max_paginas: int = 50) -> str: ...            # pypdf
def extrair_docx(dados: bytes, *, max_xml_bytes: int = 10 * 1024 * 1024) -> str: ...  # zipfile + xml.etree
def extrair_xlsx(dados: bytes, *, max_linhas: int = 500) -> str: ...           # zipfile + xml.etree, 1ª planilha
def extrair_doc(dados: bytes) -> str: ...                                      # olefile + piece table (porte do JS)
def decodificar_texto(dados: bytes) -> str: ...                                # BOM, UTF-8, cp1252
def corrigir_mojibake(texto: str) -> str: ...                                  # só se houver marcadores (Ã, Â, â€, Íμ)
def limpar(texto: str) -> str: ...                                             # \r, espaços no fim, 3+ quebras

# app/midia/resumo.py
CORTE_RESUMO = 2000
async def resumir_documento(modelo: Modelo, texto: str, *, nome_modelo: str = "gpt-4.1-mini",
                            max_entrada: int = 200_000) -> tuple[str, list[Chamada]]:
    """Usa Modelo.gerar(papel='resumo_documento', esquema={'resumo': str}); corta o resumo em ~2200 chars."""

# app/midia/audio_imagem.py   (novidade, não existia neste fluxo)
async def transcrever_audio(cliente_openai: AsyncOpenAI, dados: bytes, nome: str,
                            *, modelo: str = "gpt-4o-mini-transcribe") -> tuple[str, Chamada]: ...
async def descrever_imagem(modelo: Modelo, dados: bytes, mime: str, legenda: str | None,
                           *, nome_modelo: str = "gpt-4.1-mini") -> tuple[str, list[Chamada]]: ...

# app/midia/__init__.py
@dataclass
class ResultadoMidia:
    texto: str                 # o que vai para texto_extraido
    formato: str               # pdf, docx, ..., audio, imagem
    resumido: bool
    erro: str | None           # código curto: link_expirado, sem_texto, formato_nao_suportado...
    chamadas: list[Chamada]

async def tratar_midia(*, tipo: str, url: str | None, mime: str | None, nome: str | None,
                       legenda: str | None, transcricao_helena: str | None,
                       http: httpx.AsyncClient, modelo: Modelo) -> ResultadoMidia:
    """Ponto único. Áudio com transcrição da Helena usa a da Helena e não baixa nada."""
```

`extrair_*` são síncronas (CPU): chamar com `await asyncio.to_thread(...)` para não travar o loop.

Texto que vai para a IA, no mesmo estilo dos colchetes de `_texto_para_a_ia`:

- `[O lead enviou o documento "<nome>". Conteúdo:]\n<texto>` (curto)
- `[O lead enviou o documento "<nome>". Resumo do conteúdo:]\n<resumo>` (longo)
- `[O lead enviou o documento "<nome>", mas não foi possível ler (PDF escaneado ou arquivo protegido). Peça para ele contar o que diz ou mandar foto legível.]`
- Legenda do lead, se houver, vai depois, como hoje.

### 9.3 Bibliotecas

| Necessidade | Sugestão | Por quê |
|---|---|---|
| PDF | `pypdf` (pura Python, sem binário) | única dependência realmente necessária |
| DOCX | `zipfile` + `xml.etree.ElementTree` (biblioteca padrão) | o fluxo antigo já fazia só isso; `python-docx` é dispensável |
| XLSX | `zipfile` + `xml.etree` (lê `sharedStrings.xml` e `sheet1.xml`); `openpyxl` só se o caseiro não bastar | planilha de lead é rara |
| DOC legado | `olefile` (pura Python, pequena) + porte da piece table do JS; ou não suportar e responder texto fixo | `.doc` é raro em 2026 |
| Mojibake | função própria (`texto.encode('cp1252').decode('utf-8')` com fallback no mapa da seção 3.6) | evita `ftfy`; com `pypdf` o problema deve ser menor que no pdf.js |
| Áudio, imagem | SDK `openai` já instalado | sem dependência nova |
| HTTP | `httpx` já instalado | — |

OCR de PDF escaneado: não incluir agora (exige Tesseract ou serviço). Alternativa sem dependência:
se o PDF não tiver texto, mandar as primeiras páginas como imagem para o modelo de visão. Fica
como evolução, depois de medir quantos PDFs chegam sem texto.

### 9.4 Encaixe no pipeline (antes do extrator)

Hoje: `ler_webhook` grava em `texto_extraido` um aviso fixo ("Você não consegue abrir arquivos"),
e só o áudio aproveita a transcrição da Helena. O turno usa `m.para_a_ia()`.

Proposta, seguindo DESENHO.md 11.2 e 11.3:

1. **Recepção** (`Atendimento.receber`, mensagem do lead): grava a mensagem como hoje, com o aviso
   fixo como valor provisório. Se `tipo in ('documento', 'imagem')` ou (`tipo == 'audio'` e sem
   transcrição da Helena), cria `asyncio.create_task(self._tratar_midia(id_mensagem, evento))` e
   guarda a tarefa em `self._midias[id_lead]`. O relógio do debounce não muda.
2. **`_tratar_midia`**: chama `tratar_midia(...)`, grava com um método novo do repositório,
   `atualizar_texto_extraido(id_mensagem, texto)`, e registra as chamadas de IA em
   `agentesia_chamadas_ia` (`gravar_chamadas`, com `id_turno=None`) e falhas em eventos
   (`responsavel='provedor'` para link expirado, `'lawchat'` para erro de extração).
3. **Turno** (`_um_turno`, antes de `mensagens_pendentes`): espera as tarefas de mídia do lead com
   `asyncio.wait(..., timeout=config.espera_midia_s)` (proposta: 60 s). O que não terminou entra
   com o texto provisório ("não foi possível entender") e a IA pede de novo; quando terminar,
   o texto gravado vale para os turnos seguintes.
4. Daí em diante nada muda: `_montar_entrada` lê `para_a_ia()`, o extrator recebe o texto.

Decisão pendente para o extrator: ele só aceita fato cujo `trecho` exista nas mensagens do lead.
Se `texto_extraido` traz um **resumo gerado por IA**, um fato pode ser "provado" por texto que o
lead não escreveu. Opções: (a) aceitar fatos de documento só quando o texto é extraído cru (< 2000);
(b) marcar a origem do fato como `documento` e deixar a equipe conferir; (c) nunca extrair fatos de
resumo. Sugestão: (b), com a origem gravada junto do fato.

Também ajustar `_tempo_de_espera`: mensagem sem texto (arquivo) hoje usa `espera_padrao_s`; serve.

### 9.5 O que descartar

- `Contar Token SUBFLUXO` e o subfluxo `99 - CONTAR TOKEN`: substituídos por `Chamada` +
  `gravar_chamadas` (tokens, custo e duração já medidos em `app/modelo.py`).
- `DECIDE TAGS DESQUALIFICADO`: órfão; a qualificação já é código (`app/cerebro/travas.py`,
  `auxilio_acidente.py`). E nunca ler chave de API do payload.
- Rota `Google Sheet` (`application/vnd.google-apps.spreadsheet` não se baixa por URL) e a regra
  morta `=text/plain` do `.DOCX`.
- Renomear para ZIP, nó de compressão, "ler XML como texto": vira uma função com `zipfile`.
- Agregar/Summarize/`JSON.parse` do XLSX: vira leitura direta das linhas.
- Os dois parsers OLE2 duplicados em JS (ficam um, em Python, ou nenhum).
- A busca de URL varrendo o JSON (`CAMPOS_URL`, profundidade 8): a URL vem tipada do `Evento`.
- O mapa gigante de mojibake do PDF, se os testes com `pypdf` mostrarem que não é mais preciso.

### 9.6 Testes sugeridos

Arquivos sintéticos em `tests/arquivos/` (sem dados de lead): PDF com texto, PDF só imagem, DOCX
com acentos e tabela, XLSX de 3 linhas, `.doc` antigo, TXT em cp1252 e em UTF-16, "docx" com MIME
`text/plain`, ZIP malicioso (bomba) e arquivo acima do limite. Para cada um: formato detectado,
texto esperado, e o caminho curto/longo (com `ModeloFalso` no resumo).
