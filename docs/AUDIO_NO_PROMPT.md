# Áudio no prompt

Este guia trata dos áudios gravados pelo escritório que o roteiro manda enviar: o "como funciona", o áudio do
endereço, os áudios das objeções. Vídeo e imagem seguem as mesmas regras. Quando o lead pede "manda por áudio",
a IA não grava a própria voz: esse caso está no fim da tabela.

## 1. Como colocar um áudio no prompt (painel)

1. **Suba o arquivo na biblioteca de mídia.** No editor do agente, digite `@` e abra a Biblioteca, ou use a tela da
   biblioteca. Formatos aceitos para áudio: **.ogg / .opus / .oga** (chegam como mensagem de voz), **.mp3** e
   **.m4a** (chegam como arquivo de áudio). O limite é **16 MB** por arquivo, que é o do WhatsApp. A biblioteca
   recusa .wav, .flac e .aac e explica o motivo. O espaço total é de 200 MB por escritório.
2. **Ponha o áudio no lugar certo do roteiro.** Há três jeitos, e todos deixam no prompt o **link puro** do arquivo:
   - digite `@` no editor e escolha o áudio da lista. O link entra no texto e aparece como um chip `@nome`;
   - no produto em modo mídia, use o botão 🎵, que insere `[[midia:nome]]`. Depois, em **Edição rápida de mídias**,
     escolha o arquivo de cada marcador: o painel troca o marcador pelo link em todos os textos do produto;
   - cole um link que você já tem, por exemplo do bucket antigo
     (`https://...supabase.co/storage/v1/object/public/midia/Como%20Funciona.ogg`). O link precisa terminar na
     extensão do arquivo (.ogg, .mp3, ...) e não pode ter espaços: use `%20` no lugar deles.
3. **Escreva a instrução junto do link**, como no Sousa e Costa (`avaliacao/agentes/sousa_costa_enxuto/closer.md`):

   ```
   ETAPA 1 — Educação
   https://...supabase.co/storage/v1/object/public/midia/Como%20Funciona%20o%20Auxilio%20Acidente.ogg
   "Conseguiu entender certinho como funciona o benefício?"

   - Endereço: sozinho https://.../enderecosemfalar.ogg e "Conseguiu entender direitinho?"
   ```

   Áudios de objeção podem ficar na lista de objeções, e valem do mesmo jeito.

**Apagar um áudio da biblioteca:** o painel não deixa apagar um arquivo que algum roteiro, regra ou objeção ainda
cita. Ele responde "Este arquivo ainda é usado no roteiro de ..."; tire o link do roteiro antes de apagar.

**Marcador esquecido:** um `[[audio:Nome]]` que ficou sem arquivo não chega à IA, porque o motor o tira do prompt.
Sem link, nesse ponto a IA só responde por texto. A Edição rápida de mídias mostra quantos marcadores estão pendentes.

## 2. O que o motor faz

1. **Regra fixa.** Quando o roteiro do papel (ou as regras, as objeções ou a base) tem link de mídia, o motor junta
   às regras do sistema o bloco "Áudios e mídias do roteiro" (`REGRA_MIDIA` em `app/cerebro/catalogo.py`). O bloco
   diz à IA para:
   - mandar só o link, copiado sem mudar nada, sozinho num balão, sem anunciar "segue o áudio";
   - enviar quando o roteiro mandar: na etapa, na objeção ou na dúvida que pede aquele áudio, na ordem do roteiro;
   - usar só links do roteiro, das objeções e da base, e nunca montar um link;
   - não repetir um áudio que já está na conversa, salvo quando o lead pede de novo;
   - mandar no máximo 2 áudios por resposta.
2. **Separação.** A resposta da IA é dividida em balões. Cada link de mídia vira uma parte "mídia", mesmo que tenha
   vindo no meio de uma frase, entre `< >`, entre crases ou como `[texto](link)`. O texto antes e o texto depois
   viram balões próprios (`separar_midias`).
3. **Conferências do turno** (`app/cerebro/turno.py`):
   - **Link fora do roteiro:** a IA recebe uma correção. Se insistir, a mídia sai da resposta e o resto segue.
     Uma resposta que só tinha essa mídia vira a mensagem "Vou confirmar uma informação com a equipe...". O lead
     não é pausado, e fica registrado o evento `midia_desconhecida`.
   - **Áudio repetido:** a IA recebe uma correção. Se insistir, o áudio sai e o texto segue (evento
     `midia_repetida`). Quando o lead pede de novo ("manda de novo", "não chegou"), o reenvio vale. Se a resposta
     só tinha o áudio repetido, ele vai assim mesmo, para o lead não ficar sem resposta.
   - **Mais de 2 áudios:** vão os 2 primeiros e o resto sai (evento `audios_demais`).
4. **Envio** (`app/pipeline.py`):
   - cada parte vai para a Helena na ordem dos balões: o texto em `text`, o áudio em `fileUrl`;
   - antes de cada parte há a pausa de digitação. Depois de um áudio, o envio espera 3 s antes da parte seguinte,
     para o texto não chegar antes do áudio. Depois de um vídeo a espera é de 8 s, e de 10 s no vídeo de
     apresentação;
   - antes de mandar a mídia, um HEAD rápido confere o link (`app/midia/link.py`, com o resultado guardado por
     10 min). Se o link não abre, a mídia não vai: a equipe recebe uma nota na conversa, o cadastro recebe o evento
     `midia_quebrada` e o texto da resposta segue. Isso vale para 404 ou 410, para o 400 que o Supabase dá quando o
     arquivo não existe, para link que abre uma página em vez do arquivo e para arquivo maior que 16 MB. Se o
     servidor não deixa conferir ou está fora do ar, a mídia vai assim mesmo;
   - o histórico guarda `[mídia enviada: <link>]`, e é assim que o motor sabe que o áudio já foi;
   - um minuto depois, a fila confere a entrega na Helena e marca como falha o que voltar FAILED.

## 3. Limites

| Item | Valor |
|---|---|
| Formatos de áudio | .ogg, .opus, .oga (voz), .mp3, .m4a (arquivo de áudio) |
| Tamanho máximo do áudio | 16 MB (o limite do WhatsApp; a documentação da Helena não fixa outro) |
| Áudios por resposta | 2 |
| Reenvio do mesmo áudio | só quando o lead pede |
| Espera depois do áudio | 3 s |
| Conferência do link | HEAD de até 5 s, resultado guardado por 10 min |
| Espaço da biblioteca | 200 MB por escritório |

A Helena recebe o áudio pelo `fileUrl` (`POST chat/v1/session/{id}/message`, em `docs/HELENA_API.md`). A
documentação dela não dá o tamanho máximo do arquivo (veja "O que a documentação não responde" em
`docs/HELENA_CAPACIDADES.md`), por isso vale o limite do WhatsApp.

## 4. Casos e testes

Os testes ficam em `tests/test_audio_no_prompt.py`, salvo onde a tabela indica outro arquivo.

| Caso | Resultado | Teste |
|---|---|---|
| Roteiro com áudio | O bloco "Áudios e mídias do roteiro" entra nas regras do papel | `test_regra_fixa_das_midias_so_entra_no_papel_cujo_roteiro_tem_midia` |
| `[[audio:Nome]]` sem arquivo | O marcador sai do prompt e a IA responde por texto | `test_marcador_de_audio_sem_arquivo_nao_chega_a_ia` |
| "Envie o áudio X e depois pergunte Y" | Sai o áudio, depois a pergunta, cada um no seu balão | `test_audio_e_depois_a_pergunta_saem_na_ordem_do_roteiro` |
| Envio do áudio e do texto | A Helena recebe o áudio, depois de 3 s recebe o texto | `test_pipeline_envia_o_audio_espera_e_depois_o_texto` |
| Áudio já enviado, a IA manda de novo | Correção para a IA; se ela insistir, o áudio sai e o texto segue | `test_audio_ja_enviado_nao_vai_de_novo_mesmo_se_a_ia_insistir` |
| O lead pede "manda de novo" | O áudio vai de novo | `test_audio_ja_enviado_vai_de_novo_quando_o_lead_pede` |
| Só o áudio repetido na resposta | Vai, para o lead não ficar sem resposta | `test_audio_repetido_sozinho_na_resposta_ainda_vai` |
| Link do bucket do Supabase, com ou sem `?query` | É reconhecido como áudio e enviado como arquivo | `test_url_do_bucket_e_audio_com_ou_sem_query` |
| Link colado com `%20` (Sousa e Costa) | É reconhecido como áudio do roteiro | `test_link_colado_do_sousa_e_costa_com_porcento_20_e_audio` |
| Áudio que não está no roteiro (link inventado) | Barrado, com o evento `midia_desconhecida` | `test_audio_do_mesmo_bucket_que_nao_esta_no_roteiro_e_barrado` e os testes de `tests/test_midia_correcoes.py` |
| Mídia apagada ou link quebrado (404 no HEAD) | Não vai; a equipe recebe nota, o cadastro recebe o evento e o texto segue | `test_audio_com_link_quebrado_nao_vai_avisa_a_equipe_e_o_texto_segue` |
| HEAD: 404, 410, 400 do Storage, página HTML, mais de 16 MB | Não vai | `test_head_decide_se_o_audio_vai` |
| HEAD: 405, 503 ou rede fora | Vai assim mesmo | `test_head_decide_se_o_audio_vai` e `test_head_fora_do_ar_envia_e_resultado_fica_guardado` |
| Falha interna da conferência | Vai assim mesmo | `test_falha_na_conferencia_nunca_barra_o_envio` |
| 3 áudios numa resposta | Vão os 2 primeiros, com o evento `audios_demais` | `test_no_maximo_dois_audios_por_resposta` |
| O lead pede "manda por áudio" (sinal `quer_audio`) | Aviso à equipe e pausa; nenhum áudio é enviado | `test_lead_pede_para_falar_por_audio_avisa_e_pausa_sem_mandar_audio` |
| Formatos e tamanho | Os mesmos na biblioteca e no envio (16 MB) | `test_formatos_e_tamanho_do_audio_iguais_na_biblioteca_e_no_envio` |
| Apagar um áudio que o roteiro usa | O painel recusa | `test_biblioteca_formatos_limites_url_publica_e_apagar_em_uso` (`tests/test_midia_correcoes.py`, precisa de Postgres) |
