# Agente sob teste: Sousa e Costa Advogados (`sousa_costa.json`)

Snapshot no formato do `catalogo_referencia.json` (o que `Laboratorios._montar` consome), com os **6 prompts reais** do
fluxo n8n "13 - Sousa e Costa - SDR-CLOSER". O texto de cada agente foi copiado inteiro, com só as conversões abaixo,
para o nosso motor entender as ferramentas. Nenhum dado de lead entrou aqui. Ficaram os dados do escritório que já
estavam no prompt: nome, CNPJ, OAB dos advogados, endereço, e-mail, redes e links de mídia.

Para usar: `cenario.casos([...])[i].model_copy(update={"agente": "<caminho>/sousa_costa.json"})`, como o `comparar` faz.
Também dá `--agente-a/--agente-b` no `comparar`. Pelo CLI: `--cenarios avaliacao/cenarios_sousa_costa` roda a bateria do
escritório (que já aponta para este snapshot) e `--agente avaliacao/agentes/sousa_costa.json` aponta qualquer outra
bateria para ele. A prova offline está em `tests/test_avaliacao_sousa_costa.py`.

## Papéis

| n8n | aqui (`codigo`) | destinos (`papeis[x].destinos`) | ações | alertas | calculadora |
|---|---|---|---|---|---|
| SDR | `sdr` (principal) | periododegraca, closer, desqualificado | - | sim | sim |
| PERIODO DE GRAÇA | `periododegraca` | closer, desqualificado | - | sim | sim |
| CLOSER | `closer` | contratos | - | sim | - |
| AGENTE CONTRATO | `contratos` | (nenhum) | zapsign, buscar_cep | sim | - |
| ETAPA DE ASSINATURA | `assinatura` | (nenhum) | (nenhuma) | sim | - |
| DESQUALIFICADO | `desqualificado` | (nenhum) | - | - | - |

Os destinos e as ferramentas seguem as tools ligadas a cada agente no n8n, gravadas em
`papeis[x].ferramentas`, que sobrepõem `FERRAMENTAS_DO_PAPEL`. Duas diferenças em relação ao padrão do catálogo:

- O **Closer** do n8n só tinha a tool `contrato`: aqui não tem destino `desqualificado`.
- A **Assinatura** do n8n não tinha `criardocumento`: aqui `acoes: []`. O padrão do catálogo dá zapsign à Assinatura,
  para refazer o contrato.

`contratos` não tem destino. Quem leva o lead para `assinatura` é a ação `gerar_contrato`, depois que o contrato sai.
Assim o lead não troca de etapa antes de o sistema conferir os dados.

## Modelo

No n8n os 6 agentes usam "6 Luna" (`gpt-6-luna`, sem opções). A pedido do usuário, aqui fica `gpt-4.1-mini` com
temperatura 0.5 em todas as etapas. Isso vale em `config.modelos.etapa` e também no `modelo` de cada etapa. O extrator e
o auditor também usam `gpt-4.1-mini` (o auditor fica ligado, como em produção). Com o roteirizado, o `estimar` dá cerca
de US$ 1,06 para os 8 casos × 3 rodadas com juiz, ou US$ 0,74 com cache. Os prompts têm o dobro do tamanho dos do
catálogo de referência.

## Frases de troca (`mensagem_troca` do destino)

Vêm do nó "Definir departamento" do fluxo, que é a tabela (agente atual + frase) → próximo agente:

| destino | frase | de onde |
|---|---|---|
| `closer` | "Maravilha! Nós podemos te ajudar no seu caso." | sdr→closer e periododegraca→closer |
| `periododegraca` | "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?" | sdr→periododegraca |
| `contratos` | "Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização." | closer→contrato |
| `desqualificado` | "Analisei com atenção o que você nos contou e, neste momento, pelas regras atuais, você não se enquadra nos critérios para esse benefício específico." | **não existe no "Definir departamento"**: é a 1ª frase da mensagem exata de "APÓS DESQUALIFICAR" do prompt do SDR |
| `assinatura` | (nenhuma) | no n8n era "Perfeito! Estamos gerando o seu contrato." (contrato→etapadeassinatura). Aqui quem move é o contrato gerado |

"Verifica Frase" ("Não tenho interesse", "SAIR", "foi engano") é o filtro de saída do lead. Ele corresponde às intenções
`pediu_para_parar` e `engano` do extrator, sem conversão no prompt.

## Conversões no texto dos prompts

Cada troca foi feita por script, conferindo quantas vezes o trecho aparecia, e as conferências estão no teste.

1. **Data do n8n**: o `=` inicial e o `A data de hoje é {{ $now... }}` saíram de todos os prompts. O motor põe a data no
   conteúdo do turno ("Hoje é dd/mm/aaaa (dia), horário de Brasília hh:mm. Sempre considere esta data como a data
   atual."). No Período de Graça a frase ficou "A data de hoje vem no começo da conversa (...) A DATA DE HOJE É A
   INFORMADA NO COMEÇO DA CONVERSA", e o resto continua igual. No Closer saíram as 3 linhas de data/hora/dia da semana.
2. **tool `qualificado` → `closer`** (SDR, Período de Graça e as seções copiadas no Closer e na Assinatura). É o que a
   ativação do painel faz (`@Agente Closer` → "acionar tool \`closer\`"), e `ferramentas_do_prompt` passa a ler o destino.
3. **tool `contrato` → `contratos`** (Closer, 4 vezes).
4. **`criardocumento` → `zapsign`** (Contrato, em todas as ocorrências), como o alias legado do painel
   (`LEGACY_TOOL_ALIASES`).
5. **`BUSCARCEP` → `buscarcep`**. "utilize a tool \"BUSCARCEP\"" virou "acionar tool \`buscarcep\`", e o motor lê a ação
   `buscar_cep`. A busca de verdade é automática: o extrator pega o CEP e `_enriquecer_por_cep` completa o endereço.
6. **Sistema Notificação → sinais do catálogo** (`app/cerebro/sinais.py`). Cada prompt terminava com a seção "SISTEMA DE
   NOTIFICAÇÃO", com a regra-mestra e os 7 valores. Ela foi trocada por um parágrafo curto: os avisos (videochamada,
   áudio, não sabe ler, cliente antigo, outro benefício, dificuldade na assinatura, muitas objeções) o sistema percebe
   sozinho, pelas palavras do lead; o agente não aciona nada. No motor, o extrator marca o sinal com as mesmas regras e
   os mesmos "NÃO é" do n8n, o auditor confere, a IA sai da conversa e o aviso vai à equipe. Os demais pontos:
   - SDR, "já sou cliente → ACIONAR cliente" virou "o sistema avisa a equipe sozinho (aviso cliente antigo)".
   - SDR, `jatemadvogado` não está na lista fechada do próprio n8n nem no motor:
     - "tem advogado atuando hoje": saiu o "Acionar Sistema Notificação tipo jatemadvogado" e ficou o encerramento com
       `desqualificado`.
     - "tem, mas quer trocar": virou "preencha a notificação `analise_humana`". É o único sinal que o agente marca, e a
       equipe assume.
   - Assinatura, código de assinatura: virou "o sistema percebe sozinho a dificuldade na assinatura". Saiu o "responda
     com a mensagem que a tool devolver", porque quem responde nesse caso é o sistema.
   - Assinatura, "dúvida muito difícil" que não se resolve depois de orientar: virou `analise_humana`.
   - Contrato, a seção "Regras críticas para tool videochamada" e "## Tool \`videochamada\`" virou um parágrafo: o
     sistema percebe o pedido de videochamada, avisa a equipe e responde. O "NÃO trate pedido de áudio como
     videochamada" ficou.
7. **Calculator → calculadora do sistema** (SDR e Período de Graça): uma linha antes das regras da pergunta 5.1 (SDR) e
   no começo de "CÁLCULO" (Período de Graça). Ela diz que as contas de meses vêm prontas em FATOS DO SISTEMA
   (`contexto.fatos_da_calculadora`). O algoritmo do prompt ficou.
8. **BUSCARCPF**: não existe consulta de CPF no motor. O sistema confere os dígitos do CPF quando gera o contrato e, se
   estiver errado, manda a correção ao lead. O bloco "Use a tool BUSCARCPF / valido true/false" virou "Não há consulta de
   CPF nesta etapa: o sistema confere (...) Ao receber o CPF, não precisa avisar (...) Se o sistema avisar que o CPF está
   errado, peça novamente (...)".
9. **encerramento** (Desqualificado): não há tool de encerramento para o agente. "chame a tool ‘encerramento’" virou "não
   há ferramenta de encerramento para acionar: o sistema encerra o atendimento", nos 2 lugares. No teste, a conversa
   para quando o lead entra em `desqualificado`.
10. **Seções copiadas no Closer e na Assinatura**: as duas trazem "REGRAS DE ACIONAMENTO DE TOOLS" do SDR, com
    `periododegraca`, mas esses agentes não tinham essa tool no n8n. "acionar a Tool \`periododegraca\`" e "Após acionar a
    tool \`periododegraca\`" viraram "passar o lead para \`periododegraca\`", senão `ferramentas_do_prompt` abriria um
    destino que o n8n não tinha. O resto da seção ficou, com `closer` no lugar de `qualificado`.
11. **Descrições das tools do n8n**: o modelo do n8n via a descrição de cada tool junto com o prompt. Aqui as tools
    viraram ações do motor e as descrições não vão ao modelo. Quase tudo nelas repete o prompt (Sistema Notificação,
    `contrato`, `qualificado`). O que só existia nelas foi para o fim do prompt de `contratos`, num bloco "Regras da
    ferramenta \`zapsign\`": profissão "do lar" vira "Desempregado"; CPF, RG e CEP com pontuação; telefone com DDD;
    e-mail opcional; busca do CEP só 1 vez por atendimento. Repare que a lista "CAMPOS OBRIGATÓRIOS" do Contrato não
    cita profissão, mas a tool exigia (o prompt pergunta pela profissão só por causa da tool). No motor, a formatação de
    CPF, CEP e telefone é feita pelo sistema (`app/contrato/dados.py`) e a busca de CEP é automática.

**Sem conversão**:
- `dados_lead` e `salvar_dados_lead1`: no n8n não estavam ligados a nenhum agente. O equivalente aqui é o extrator, que
  grava os fatos.
- O Closer repete o prompt inteiro duas vezes, como no n8n.
- Os links de mídia (PTV.mp4, áudios .ogg, vídeos .mp4, imagem .jpeg) ficaram. `catalogo.separar_midias` manda um link
  sozinho no balão como arquivo, como o CLEAN_PARSER. Como estão no snapshot, contam como links do agente
  (`link_inventado` não acusa).

## Outros campos do snapshot

- `config.honorarios`: as regras do Closer em uma frase (5 salários do benefício, cada um não menor que o mínimo de
  R$ 1.621,00, mais 30% dos atrasados; o lead fica com 70%; nada antes, 12x no boleto). No catálogo o prompt não usa esse
  campo: ele serve às checagens (`honorario_divergente`) e ao juiz.
- `conhecimento.dados_escritorio`: os dados do escritório do prompt. `faq` e `objecoes` ficaram vazios, porque as
  objeções já estão nos prompts. Repetir aqui duplicaria tudo no sistema.
- `catalogo.regras: null`. As regras gerais da referência ("Não escreva links") contradizem o fluxo, que manda mídia por
  link.
- `boas_vindas: null`. A primeira mensagem (link do vídeo + apresentação + 1ª pergunta) está no próprio prompt do SDR.

## O que ficou diferente do n8n

- Modelo e temperatura (acima). No n8n a saída era texto livre, quebrado pelo CLEAN_PARSER. Aqui é JSON (`mensagens`,
  `transferir_para`, `ferramenta`, `notificacao`), e o motor acrescenta ao fim do sistema o bloco "FORMATO DA RESPOSTA
  (sistema)", as regras do zapsign (`FORMATO_FERRAMENTAS`) e, nos papéis com alerta, a regra do `analise_humana`.
- A troca de etapa pode vir pelo campo `transferir_para` **ou** pela frase exata. No n8n era só pela frase (ou pela
  chamada HTTP da tool).
- O lead entra em `assinatura` quando o contrato é gerado, não quando a IA diz "Perfeito! Estamos gerando o seu
  contrato.".
- Os avisos são decididos pelo extrator e pelo auditor, não pelo agente.
- **Todo aviso confirmado pausa a IA** (`turno.py`: estado `pausado`, motivo `sinal:x`) e o sistema manda a mensagem
  fixa. O prompt do escritório prevê **seguir** a conversa em pelo menos dois casos, e isso não roda no motor:
  - OBJ 11 (pedido de áudio): texto "Eu entendo, vou te enviar sobre isso." + o link `objecao_audio.ogg`;
  - "DÚVIDA CÓDIGO DE ASSINATURA": no n8n, "se a tool disser que o atendimento não foi desativado, continue ajudando
    normalmente".
  Também saiu, sem nada no lugar, a regra do Contrato "responda confirmando que a vídeo chamada é possível e pergunte o
  melhor horário" (quem responde é o sistema). Quais tipos desligam a IA quem decide é o subfluxo "Sistema Notificação"
  do n8n, que **não está no repositório** (só a descrição da tool, sem os ramos). Não deu para conferir. Por isso o
  `estado_final: "pausado"` do sc01 e do sc18 (`pede_audio`, `videochamada_prioridade`, `nao_sabe_ler`) mede a regra do
  MOTOR, não a do prompt; as descrições dos dois cenários dizem isso. Se o subfluxo mostrar que áudio e código não
  desligam a IA, o motor (ou o snapshot) precisa tratar esses sinais como aviso sem pausa.

## Decisões do fechamento (2026-11-25)

- **"Em alguns segundos você vai receber o link para assinatura!"** (mensagem obrigatória da ETAPA 3 do Contrato): a
  trava de promessa (`app/cerebro/travas.py`, `_VOCE_VAI_RECEBER`) **deixa passar** "você vai receber" quando o que chega
  é uma entrega do atendimento (link, contrato, documento, mensagem, código, e-mail, vídeo, áudio, arquivo, aviso,
  contato, ligação, retorno, visita ou atendimento da equipe...):
  é aviso de envio, não promessa de resultado. "Você vai receber o benefício / os atrasados / o valor" continua
  barrado. O texto do snapshot ficou igual ao do n8n. O `FORMATO_FERRAMENTAS` ainda sugere não dizer que o link "chega
  em instantes" (o sistema confere os dados antes); o modelo pode reescrever a frase, e nenhuma das duas formas reprova.
- **"100% online"** (Closer, etapa 3): `checagens.valores_de_honorario` ignora "100%/cem por cento" seguido de online,
  digital, virtual, remoto, pelo celular/WhatsApp/internet, a mesma exceção da trava de promessa. Antes isso acusava
  `honorario_divergente` (crítica) em toda resposta fiel ao prompt.
- **FAQ da Assinatura** ("Sim, é necessário imprimir todas as páginas..."): só o sc02 testa essa pergunta, e reprova de
  propósito até o escritório corrigir a linha (reprovação esperada pelo prompt do escritório). O sc10 não pergunta mais.

## Pontos para a rodada real (o prompt real contra o motor e os cenários)

1. (resolvido no fechamento: ver "Decisões do fechamento") "Em alguns segundos você vai receber o link".
2. (resolvido no fechamento) "100% online" e `honorario_divergente`.
3. **Cartão do lead nos cenários 01/04/05**: a pergunta do SDR "Só pra confirmar: você já tem um advogado atuando HOJE
   (...)?" casa primeiro com o assunto de confirmação ("confirm"), e o lead responde "isso, pode seguir". O oráculo então
   acusa `pulou_pergunta` (tem_advogado_no_caso). O teste offline usa a pergunta sem o "Só pra confirmar".
4. **Perguntas do Closer fora do cartão**: "Conseguiu entender certinho como funciona o benefício?", "Essas vantagens
   fariam diferença no seu dia a dia?", "Conseguiu entender certinho as condições dos honorários?" e o "Posso te explicar
   como funciona o Auxílio-Acidente?" do SDR não casam com nenhum assunto dos cartões atuais. Três respostas "padrão"
   seguidas deixam a rodada **inválida** ("lead sem assunto"). Os cenários do Sousa e Costa precisam desses assuntos.
5. **Desqualificação pelo Período de Graça**: o prompt manda só "informar de forma educada", sem a frase do SDR. A troca
   sai pelo `transferir_para`, mas nos cenários com `desqualificado` em `transferencias_com_frase` (02, 03) isso acusa
   `transferencia_sem_frase` (alta).
6. **Desqualificado pergunta**: o fluxo dele pede confirmação ("me avisa se algo mudou") e nota de 1 a 5. `sem_pergunta_em` vale
   `["desqualificado"]` por padrão em todos os cenários, então essas perguntas acusam `pergunta_no_encerramento` (alta).
7. **"# REGRAS DE DECISÃO"** do SDR conta como seção sensível na checagem de vazamento (o título tem "decisão"). Repetir
   ao lead trechos dessa seção acusa `vazamento`.

## Versão sugerida (25/11/2026)

`sousa_costa_sugerido.json` é este snapshot com as correções de prompt da rodada real; cada uma está, com o texto ANTES e
DEPOIS, em `sousa_costa_RECOMENDACOES.md`. O fiel continua sendo `sousa_costa.json`, que não foi editado. O resultado das
rodadas está em `docs/RELATORIO_NOITE_2026-11-25.md`.
