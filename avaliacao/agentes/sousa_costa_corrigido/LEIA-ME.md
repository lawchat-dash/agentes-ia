# Sousa e Costa: prompt corrigido (testes de 25/11/2026)

Prompt do escritório para o **nosso motor** (não para o n8n). A estrutura é a mesma do fiel: seções, etapas, tom, dados do
escritório, mídias, objeções e frases de troca. As mudanças são cirúrgicas, feitas a partir dos erros e
micro-alucinações das rodadas `2026-11-25_0317`, `_0426` e `_0523` (sugerido).

## Arquivos

| Arquivo | O que é |
|---|---|
| `../sousa_costa_corrigido.json` | Agente pronto para a avaliação (`agente-sousa-costa-corrigido`). É o `sousa_costa.json` com a instrução de cada papel trocada pelo `.md` abaixo. Modelos (gpt-4.1-mini, 0.5), destinos, ações, `mensagem_troca` e boas-vindas não mudam. |
| `sdr.md`, `periododegraca.md`, `closer.md`, `contratos.md`, `assinatura.md`, `desqualificado.md` | Instrução completa de cada papel (a fonte: edite aqui e remonte o JSON). |
| `MUDANCAS_<papel>.md` | ANTES/DEPOIS de cada troca, com o caso e o turno que a motivaram. |
| `../../../tests/test_avaliacao_sousa_costa_corrigido.py` | Provas estruturais (sem API). |

A pasta `n8n/` (rascunho no formato do n8n, com nomes de tools que não valem aqui) foi retirada.

Única troca de mídia: na 2ª cópia da ETAPA 4 do Closer, o áudio `Horonarios%20AuxAcidente.ogg` virou o vídeo
`video-honorarios-5salarios.mp4`, igual à 1ª cópia ("Obrigatório", com transcrição). Ver `MUDANCAS_closer.md`, item 8.
Decisão a confirmar com o escritório.

## Erro visto → onde foi corrigido

| Erro visto nos testes | Papel | Regra / seção |
|---|---|---|
| Pular a pergunta do ano do acidente | sdr | Pergunta 2 e "Tool `closer`": só passa com o mês/ano respondido |
| Repetir pergunta já respondida (CLT/MEI, número, complemento, "Conseguiu entender certinho...?") | sdr, periododegraca, closer, contratos | "Respostas que JÁ CONTAM" (sdr); FLUXO DE MENSAGENS: "nunca volte a uma etapa já feita" (closer); NÚMERO E COMPLEMENTO JUNTOS (contratos) |
| Ecoar a resposta como pergunta ("foi em 2014, certo?") + nova pergunta | sdr, periododegraca, closer, contratos | PERGUNTAS INICIAIS (sdr); REGRAS DE ATENDIMENTO (periododegraca); COMUNICAÇÃO (closer); Proibições Técnicas (contratos) |
| Opinião jurídica inventada ("não ter recebido auxílio-doença pode complicar") | todos | TRAVAS/CONDUTA (sdr), REGRAS DE ATENDIMENTO, PROIBIÇÕES ABSOLUTAS |
| CPF válido chamado de "incorreto" | contratos | "No caso do CPF": só a linha CONFERÊNCIA DO CPF (sistema) decide; pontuação nunca é erro |
| "Buscamos nos Correios e o seu endereço é..." sem busca | contratos | ENDEREÇO e REGRA DE REFORÇO, passo 2/3c: só com a linha BUSCA DE CEP "encontrado"; endereço digitado vira "Anotei seu endereço" |
| Prometer incluir lesão nova no processo | contratos, assinatura | LESÃO OU SEQUELA NOVA (contratos); DÚVIDA MUITO DIFÍCIL (assinatura) |
| "Garantir seu direito / benefício / o melhor resultado" | todos | LIMITES LEGAIS / PROIBIÇÕES ABSOLUTAS: nada de "garantir" ligado a resultado |
| Pedir documentos médicos / laudo fora do roteiro | contratos, periododegraca, desqualificado | LIMITES LEGAIS; DOCUMENTOS MÉDICOS, PRAZO E ASSINATURA; REGRAS DE ATENDIMENTO |
| Prazo inventado ("alguns dias", "5 dias úteis") | contratos, assinatura, periododegraca | LIMITES LEGAIS; FAQ de tempo sem prazo |
| Mandar imprimir / assinar à mão / enviar foto (FAQ errada) | assinatura, contratos, closer | DÚVIDAS FREQUENTES: "Não precisa imprimir nada"; PROIBIÇÕES (closer, OBJ 10) |
| Laço "conseguiu abrir o link?" quando o código não chega | assinatura | DÚVIDA CÓDIGO DE ASSINATURA e NÃO FICAR EM LAÇO (vai para "analise_humana") |
| Período de Graça presumindo data | periododegraca | PREMISSAS FIXAS (hoje nunca é a data do acidente nem da saída) e DECISÃO PELOS FATOS DO SISTEMA |
| Perguntar CLT 3x a quem disse "nunca" | periododegraca, sdr | PERGUNTAS OBRIGATÓRIAS: "NUNCA teve carteira" → desqualificado, sem perguntar de novo |
| Laço "mês e ano exatos" sem saída para "não sei" | periododegraca | PERGUNTAS OBRIGATÓRIAS: no 1º "não sei" pede aproximação uma vez; depois, "Análise da equipe" |
| "Agora vou calcular" e parar | periododegraca | PROIBIDO "vou calcular"/"aguarde": a resposta termina com a decisão ou a próxima pergunta |
| Confirmação final com 3 "?" / recapitulação como pergunta | periododegraca, contratos | "Após qualificação" (exemplo ERRADO); ETAPA 2 — CONFIRMAÇÃO FINAL |
| Closer pedindo o nome antes da hora (contratos 2x) | closer | ETAPA 5: "Não pedir nome antes da hora"; Passagem para `contratos` uma única vez, frase como último balão |
| Desqualificado com motivo errado | desqualificado, sdr | REGRAS DE DESQUALIFICAÇÃO (MOTIVO REAL pela tabela; pedido negado virou OBJ 9) |
| Vagas vazias (", ,"), confirmação + nota no mesmo balão, ano inventado | desqualificado | 1 - CONFIRMAÇÃO DAS INFORMAÇÕES: item que falta sai inteiro; conferência do balão; nunca cite número que o lead não disse |
| Responder dúvida sem retomar a condução | assinatura, periododegraca | "Retomada da condução" (assinatura); REGRAS DE ATENDIMENTO: responde e retoma a pergunta pendente |

## O que ficou no motor (e não no prompt)

- **Frase de troca**: a troca de etapa é o campo `transferir_para`. Se a IA passar sem a `mensagem_troca` do destino, o
  motor insere a frase exata como 1º balão. O prompt só pede a frase junto da transferência, nunca sem ela.
- **CPF**: o sistema confere e manda "CONFERÊNCIA DO CPF (sistema): ... VÁLIDO/INVÁLIDO".
- **CEP**: o sistema busca sozinho no turno e manda "BUSCA DE CEP (sistema)".
- **Fatos e contas**: "DADOS JÁ INFORMADOS PELO LEAD" e "FATOS DO SISTEMA" (meses já calculados; o modelo não calcula).
- **Sinais** (videochamada, áudio, não sabe ler, dificuldade na assinatura, cliente antigo, muitas objeções): o sistema
  detecta, pausa e avisa a equipe. O prompt não aciona nada para eles.
- **Contrato**: a ferramenta `zapsign` gera o contrato e muda para Assinatura; a assinatura confirmada é detectada pelo
  sistema.
- **Travas de produção**: "garant…" ligado a resultado, "você tem direito", "100%" (exceto "100% online"), "você vai
  receber o benefício/atrasados" e endereço sem fonte são barrados e a IA refaz; repetido 2x, o lead é pausado.

## Como testar

Provas estruturais (sem API):

```
.venv/Scripts/python.exe -m pytest tests/test_avaliacao_sousa_costa_corrigido.py -q
```

Estimar o custo da bateria (o real sai em torno de 25% do estimado):

```
.venv/Scripts/python.exe -m app.avaliacao estimar --cenarios avaliacao/cenarios_sousa_costa --agente avaliacao/agentes/sousa_costa_corrigido.json --rodadas 1 --juiz
```

Para remontar o JSON depois de editar um `.md`: copie o texto do `.md` para `agente.etapas[codigo=<papel>].instrucao`
do `sousa_costa_corrigido.json` e rode o teste acima (ele confere que o JSON é igual aos `.md`).
