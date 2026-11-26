# LawChat IA — núcleo do atendimento em código

22/11/2026. Sistema novo, do zero, em Python. Recebe o webhook da Helena, junta as mensagens do lead, entende, decide a etapa, responde e registra tudo. Não lê nem altera as tabelas do Weaver.

## O que já funciona

| Parte | Onde | Situação |
|---|---|---|
| Regras do Auxílio-Acidente (qualificação, período de graça, troca de etapa) | `app/cerebro/auxilio_acidente.py` | Testado. **Falta a validação do advogado responsável** |
| Extrator de fatos, com conferência do trecho que prova | `app/cerebro/extrator.py` | Testado com IA de mentira |
| Agente da etapa (só escreve a mensagem) e instruções padrão | `app/cerebro/agente.py` | Testado com IA de mentira |
| Travas de saída e formatador | `app/cerebro/travas.py`, `formatador.py` | Testado |
| Camada de modelo (GPT por padrão, Claude opcional; saída estruturada, custo na hora) | `app/modelo.py` | Testado com cliente de mentira. **Nunca rodou com a IA de verdade** |
| Canal Helena (ler webhook, enviar) | `app/canal/helena.py` | Leitura testada. **Envio nunca rodou contra a Helena** |
| Pipeline (recepção, espera, turno, envio) | `app/pipeline.py` | Testado em memória e num Postgres local |
| Banco (tabelas `agentesia_*`) | `db/migracoes/`, `app/banco/postgres.py` | Testado num Postgres local. **Ainda não aplicado no Supabase** |
| Laboratório | `app/web/lab.html`, `/lab` | Abre e roda um turno com a IA de mentira |

## Como rodar

```bash
python -m venv .venv
```
```bash
.venv/Scripts/python -m pip install -r requirements.txt
```
Copie `.env.example` para `.env` e preencha. Depois:
```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```
Abra `http://localhost:8000/lab`.

- **Sem chave de IA:** ponha `AGENTESIA_MODELO_FALSO=1` para ver a página funcionando com respostas de mentira.
- **Com `OPENAI_API_KEY`:** o Laboratório conversa com o GPT de verdade (padrão: `gpt-4.1`). Cada turno faz duas chamadas (extrator e agente da etapa).
- **Modelo por agente:** o nome do modelo escolhe o provedor. `gpt-...` usa a OpenAI; `claude-...` usa a Anthropic e pede `ANTHROPIC_API_KEY`.
- **Com `AGENTESIA_BANCO_URL`:** o webhook de cada escritório passa a atender em `/webhook/helena/{id_escritorio}?segredo=...` (a URL e o segredo de cada escritório saem prontos na ativação pelo painel; o segredo é derivado de `AGENTESIA_WEBHOOK_SEGREDO`, que nunca vai numa URL). Não existe rota global (`/webhook/helena` sem o id foi removida): cada escritório só entra pela própria URL. Se a URL global antiga, com o segredo mestre, já foi usada em alguma conta, troque `AGENTESIA_WEBHOOK_SEGREDO` e refaça a assinatura de cada escritório pelo painel. Antes, rode `db/migracoes/001_agentesia_nucleo.sql` e cadastre o escritório com `db/exemplos/cadastrar_escritorio.sql`.

## O Laboratório

Você escreve como o lead. A cada resposta, o painel da direita mostra:
- **Este turno:** fatos que o extrator achou com o trecho que prova, fatos descartados pelo código, decisões das funções, próxima pergunta, travas (aprovada ou reprovada e por quê), eventos, chamadas de IA com tokens, tempo e custo.
- **Fatos:** tudo o que se sabe do lead até agora.
- **O que a IA recebeu:** instruções e conteúdo exatos enviados ao modelo, e o que ele devolveu.
- **Configuração:** nome, escritório, modelo, honorários e a instrução de cada etapa. Vale só no Laboratório.

Nada é enviado ao WhatsApp e nada é gravado no banco.

## Por que não há "tools"

No n8n a IA decide quando chamar cada ferramenta, e erra de três jeitos: esquece, chama a errada ou preenche errado. Aqui o GPT não chama ferramenta nenhuma. Ele devolve um JSON num formato fixo, que a OpenAI valida (saída estruturada em modo estrito), e o código faz o resto: troca etapa, pausa, encerra, avisa. É o mesmo ponto forte do GPT, usado de um jeito que não deixa a decisão na mão do modelo.

## Como um turno funciona

1. **Recepção.** Descarta repetido, acha o escritório pela conta e o canal pelo número, acha ou cria o lead, grava a mensagem. Mensagem de atendente pausa a IA; eco da própria IA é ignorado pelo id.
2. **Espera.** Meio segundo por letra, entre 15 e 90 segundos; mensagem nova reinicia o relógio e nunca interrompe um turno em andamento.
3. **Primeira conferência.** A IA só atende com escritório ligado, agente ativo, lead ativo e, em modo `teste`, número de teste. Senão, grava e fica em silêncio.
4. **Extrator.** Devolve fatos com trecho. O código confere o trecho nas mensagens do lead e descarta o que não tiver prova.
5. **Decisão.** Funções em código decidem a etapa. A IA não troca etapa.
6. **Agente da etapa nova.** Recebe o que já se sabe e a única pergunta a fazer.
7. **Travas.** Promessa, link, termo técnico, dado pessoal fora de hora, valor fora dos honorários, mais de uma pergunta, texto interno. Reprovou: refaz uma vez. Reprovou de novo: mensagem segura e passa para a equipe.
8. **Segunda conferência.** Chegou mensagem nova ou o atendente assumiu? Descarta e refaz, ou cala.
9. **Envio e registro.** Três tentativas por parte; parte que falha vira evento e não derruba as outras.

## Testes

```bash
.venv/Scripts/python -m pytest -q
```
89 testes: regras, turno do cérebro, pipeline, camada de modelo (OpenAI e Anthropic). Mais 2 que gravam num Postgres local:
```bash
node db/testes/servidor_local.mjs 55433
```
```bash
AGENTESIA_TESTE_PG_URL=postgresql://postgres:postgres@127.0.0.1:55433/postgres .venv/Scripts/python -m pytest -q tests/test_postgres.py
```
O teste das migrações fica em `db/testes` (`npm install`, `npm run testar`).

## O que ainda não existe

| Falta | Enquanto isso |
|---|---|
| Transcrição própria de áudio e descrição de imagem | Usa a transcrição que a Helena manda; sem ela, a IA pede para o lead escrever |
| Follow-up | Não há lembrete |
| Card e tags no CRM, contrato, avisos à equipe pelo WhatsApp | Os eventos ficam em `agentesia_eventos`; ninguém é avisado sozinho |
| Abertura com vídeo e regra de horário comercial | A IA começa pelo SDR, só com texto |
| Triagem de vários produtos e leitura de anúncio | Só Auxílio-Acidente |
| Volta automática da pausa sem mensagem do lead | A IA religa quando o lead escreve depois do prazo |
| Fila durável | A espera fica na memória do servidor: se ele reiniciar no meio, a mensagem fica gravada, mas sem resposta até o lead escrever de novo. Rodar com um processo só |
| Painel de gestão | Configuração editada direto nas tabelas |

## Antes de ligar para um escritório de verdade

1. Rodar o Laboratório com a IA de verdade e ajustar instruções e travas.
2. Validar as regras de qualificação com o advogado.
3. Aplicar a migração no Supabase e cadastrar o escritório em modo `teste`.
4. Testar com o seu número: conferir o formato real do webhook e do envio da Helena.
5. Só então passar o agente para `producao`.

### Biblioteca de mídia (áudios, vídeos e imagens dos roteiros)

- `AGENTESIA_URL_PUBLICA` (com `https://`) precisa estar configurada **antes** de subir mídia: sem ela o upload é
  recusado (409), porque a URL gravada ficaria relativa e a Helena não conseguiria baixar o arquivo.
- Os arquivos ficam em disco, em `dados/midia` (ou na pasta de `AGENTESIA_PASTA_MIDIA`). Essa pasta precisa de
  **volume persistente**: num container sem volume, um reinício apaga os áudios e a Helena passa a receber 404. Com mais
  de uma réplica, todas precisam enxergar o mesmo volume.
- Formatos aceitos (o que o WhatsApp entrega): áudio `.ogg`/`.opus`/`.oga` (chega como mensagem de voz), `.mp3` e `.m4a`
  (chegam como arquivo de áudio), vídeo `.mp4` até 16 MB, imagem `.jpg`/`.png` até 5 MB. Áudio e vídeo até 16 MB.
- Um arquivo citado no roteiro de algum agente não pode ser apagado (409) até o link sair do roteiro.
- Vídeo de apresentação: o arquivo terminado em `ptv.mp4` (ou com `so_horario_comercial` em `config.midias`) só é
  enviado das 8h às 20h, no fuso do escritório; depois dele a IA espera 10 s antes da parte seguinte.
