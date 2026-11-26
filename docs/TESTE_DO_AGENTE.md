# Teste do agente

Simula conversas inteiras com o agente (do webhook ao envio, com o pipeline de verdade) e confere o resultado.
O plano completo está em `docs/PLANO_TESTE_AGENTE.md`.

## Duas perguntas, dois modos

| Pergunta | Modo | Custo |
|---|---|---|
| O código em volta da IA está certo? (etapa, frase de troca, contrato, CEP, parada) | **offline**: modelo roteirizado ou cassete, no `pytest` | zero |
| O modelo e o prompt atendem bem? | **real**: modelo de verdade, N rodadas | pago, só com `--real` e teto |

**Sem `--real`, nada chama a API.** O modo real exige `--teto-usd` e a chave (`OPENAI_API_KEY` no ambiente ou no `.env`)
e para antes de passar do teto.

## Comandos

```
python -m app.avaliacao listar                         # cenários, trajetória esperada e se há cassete
python -m app.avaliacao estimar --rodadas 3 --juiz     # quanto o modo real custaria (não chama a API)
python -m app.avaliacao rodar --falso                  # modelo roteirizado: prova o motor (de graça)
python -m app.avaliacao rodar                          # toca os cassetes gravados (de graça)
python -m app.avaliacao rodar --real --rodadas 3 --teto-usd 2 [--cenario 01,04] [--lead ia] [--juiz]
python -m app.avaliacao gravar 01 04 --teto-usd 1      # grava cassete + transcrição com o modelo real
python -m app.avaliacao estabilidade 01 --rodadas 10 --teto-usd 2
python -m app.avaliacao comparar --agente-a a.json --agente-b b.json --cenario 01 --teto-usd 1
python -m app.avaliacao exportar-agente <id_agente> --escritorio <id> --saida avaliacao/agentes/meu.json
```

Outra bateria: `--cenarios <pasta>` (em `listar`, `estimar`, `rodar`, `gravar`, `estabilidade` e `comparar`) lê os
cenários de outra pasta, e `--agente <snapshot.json>` troca o agente de todos os casos. A do Sousa e Costa:

```
python -m app.avaliacao listar  --cenarios avaliacao/cenarios_sousa_costa
python -m app.avaliacao estimar --cenarios avaliacao/cenarios_sousa_costa --rodadas 1 --juiz
python -m app.avaliacao rodar   --real --cenarios avaliacao/cenarios_sousa_costa --rodadas 1 --juiz --teto-usd 3
```

Os cenários dessa pasta já apontam para `avaliacao/agentes/sousa_costa.json`; não há roteiro do modelo falso nem
cassete para eles, então o `estimar` usa a conta sem roteiro (2 chamadas por turno, prompt do tamanho do snapshot) e
`rodar` sem `--real` dá PULADO (sem cassete; para gravar, `gravar <id> --cenarios avaliacao/cenarios_sousa_costa
--teto-usd 1`). A prova de graça deles está nos testes `tests/test_avaliacao_sousa_costa*.py`.

No pytest: `pytest` roda o motor e os cassetes (pula o que não foi gravado). O modo real:
`pytest -m ia --real --teto-usd 2 [--rodadas 3] [--regravar]`.

Referência de custo (gpt-4.1-mini, US$ 0,40/1,60 por milhão): cerca de US$ 0,02 a 0,04 por conversa; os 6 cenários
com 3 rodadas e juiz ficam perto de US$ 0,60. Rode `estimar` antes: ele mede o tamanho real dos pedidos.

## Onde fica cada coisa

- `app/avaliacao/`: o motor (cenário, montagem, relógio, efeitos falsos, leads, cassete, simulador, checagens,
  oráculo, juiz, custo, relatório, executar, CLI). O painel vai usar o mesmo `executar.rodar_bateria`.
- `avaliacao/agentes/catalogo_referencia.json`: snapshot **sintético** do agente do catálogo (Auxílio-Acidente).
  Troque pelo export real (`exportar-agente`) para avaliar o prompt de um escritório.
- `avaliacao/cenarios/*.json`: os 6 cenários. Tudo sintético, com CPFs válidos gerados; nunca dado real de lead.
- `avaliacao/cassetes/` e `avaliacao/transcricoes/`: gerados pelo `gravar`, versionados.
- `avaliacao/resultados/`: saída das rodadas (no `.gitignore`): `resultado.json`, `relatorio.md` e uma transcrição por rodada.

## Como o teste se comporta (ajustes da rodada real de 2026-11-25)

Detalhes em `docs/DIAGNOSTICO_RODADA_REAL_2026-11-25.md`, seção 3.

- **Auditor ligado**, como em produção. O snapshot fixa `config.modelos.auditor` em `gpt-4.1-mini` (o padrão de
  produção pode ser um modelo sem preço cadastrado, e aí o `estimar` recusa). Só a variante
  `03_periodo_de_graca[extrator_sozinho]` desliga o auditor (`sobrescrever_config` da variante): ela mede o escritório
  que usa só o extrator, onde uma reclamação ("já te falei") não pode virar pausa.
- **Lead do cartão**: responde ao que está nas frases com "?" (e só lê o balão inteiro se nenhuma pergunta casar).
  Pergunta já respondida: repete a resposta ("como eu falei, ..."), não um "já te falei isso" seco. Depois de 3
  respostas "padrão" seguidas, a rodada fica **inválida** ("lead sem assunto para: ...") e não reprova o agente: o
  cartão é que não cobre a pergunta. Um gatilho sem pergunta ("pode perguntar") não engole a pergunta do mesmo balão;
  um gatilho de objeção ("como vou saber que não é golpe?") vem antes e a IA pergunta de novo.
- **Assunto de aceite**: o assunto com `"aceite": true` é o sim do lead. A checagem `aceite_antes_de_contratos` (alta)
  acusa quem entra em contratos sem que a última fala do lead seja esse sim ("não sei" não é aceite).
- **Dado fora de hora**: "nome completo" também conta. Só fica isento o turno que entra na etapa dos dados com a frase
  de troca.
- **Vazamento**: só as linhas sensíveis do prompt contam (seção `# 3. DECISÃO`, "Regra interna", "acionar tool",
  "nunca deve ser dita", prazo em meses). Nome do escritório e do agente são permitidos.
- **Promessa**: "garantir", "com certeza" e "100%" só contam ligados a resultado. "O que posso garantir é que cuidamos
  do pedido", "claro, com certeza!" e "atendimento 100% online" passam; "benefício garantido" e "100% de chance", não.
- **Sem passar por contratos**, `cep` e `fato_nao_capturado` dos dados do contrato não acusam (só inflavam a lista).
- **Roteiro (06)**: parar antes da última fala acusa `parou_antes_do_roteiro`, com ou sem `espera` na fala.
- **Texto barrado**: quando a trava refaz a resposta, o turno grava cada tentativa reprovada em
  `saida.contexto["tentativas"]` (`[{"texto", "reprovacoes": [motivo, ...]}]`). A transcrição mostra o texto riscado,
  antes da resposta enviada, e a checagem `refeito_pela_trava` cita o texto. Sem isso gravado, tudo sai como antes.
- **Estimativa**: soma 1 chamada do auditor por conversa (ele só roda quando o extrator marca um sinal), pelo preço do
  modelo dele.

## Como ler o resultado

- Aprova quem não tem falha **crítica** nem **alta**. As **médias** (várias perguntas, mensagem longa, número
  sem origem, resposta refeita pela trava) são métrica.
- No modo real, por cenário: falha crítica em qualquer rodada reprova; falha alta tolera no máximo 1 em 3 rodadas.
- O **juiz** de IA é só sinal: nota por critério, com evidência conferida na transcrição. Violação de fidelidade ou
  OAB sem checagem que confirme vai para "revisar manualmente".
- A **trava sombra** conta quantas respostas as travas completas teriam barrado (para decidir se valem no catálogo).

## Regras do time

1. Gravar cassete custa (cerca de US$ 0,25 os 6). Quem decide e roda é o usuário, não o agente de código.
2. PR que muda cassete mostra o diff da transcrição em `avaliacao/transcricoes/`. Leia antes de aprovar: o verde no
   cassete só diz que o código em volta da IA continua igual.
3. Cassete que falha com `cassete_falta` quer dizer que o prompt ou o código mudou: regrave e revise.
