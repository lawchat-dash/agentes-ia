# Recomendações para o agente de referência (catalogo_referencia.json)

Este arquivo registra mudanças propostas no prompt do agente de catálogo de referência. O snapshot original
(`catalogo_referencia.json`) **não foi alterado**. A versão com as mudanças aplicadas está em
`catalogo_referencia_sugerido.json`. Ela é uma cópia idêntica, exceto pela `instrucao` da etapa `et-periododegraca`,
e pode ser testada com `--agente avaliacao/agentes/catalogo_referencia_sugerido.json` sem mexer no original.

---

## [0] Período de Graça pergunta de novo a sequela ("além dessa")

**Caso:** `03_periodo_de_graca[extrator_sozinho]`, rodada `avaliacao/resultados/2026-11-25_0146_agente-referencia`
**Falha:** `pergunta_repetida` · classe `agente_prompt` · etapa `periododegraca` · gravidade **média** (a checagem marcou alta)

### O que aconteceu (transcrição, turnos 3 a 5)

- t3 [sdr]: a IA pergunta "Depois do acidente, você ficou com alguma sequela ou limitação?" e, no mesmo turno, passa o
  lead para o `periododegraca`.
- t4: a lead responde "fiquei mancando, a perna direita não firma". O Período de Graça responde "Você ficou com alguma
  sequela além dessa limitação na perna direita?".
- t5: a lead reclama ("como eu falei, fiquei mancando...") e só então a IA segue para o seguro-desemprego.

### Causa

1. **Primária (fora desta área):** o SDR transferiu cedo. Perguntou a sequela e passou o lead no mesmo turno, então a
   resposta chegou a um agente que não fez a pergunta.
2. **Prompt (esta correção):** o §3 dizia "confirme sequela, aposentadoria e advogado no caso, se ainda faltarem". O verbo
   "confirme" convida a perguntar de novo. Além disso, a regra fica só na DECISÃO e não na ordem das perguntas do §2. O
   §2 mandava ir direto à pergunta 2 (seguro), porque a data da demissão já tinha sido dada, mas não dizia o que fazer
   quando a mensagem nova responde a uma pergunta do atendimento anterior.
3. **Motor (fora desta área):** o extrator do catálogo não captura `sequela`. Ele só pega os dados do contrato, o nome
   e as datas do período (`app/cerebro/catalogo.py`, `esquema_extrator` e `guia_do_extrator`). Por isso a sequela não
   aparece em "DADOS JÁ INFORMADOS PELO LEAD (não pergunte de novo)" (`app/cerebro/turno.py`).

**Ceticismo:** o modelo sabia da sequela, porque citou "dessa limitação". A ambiguidade de "confirme" é uma hipótese
plausível, não comprovada. A pergunta foi "além dessa" e não um pedido do mesmo fato, por isso a gravidade é média. Mesmo
assim, a pergunta era desnecessária e a lead a percebeu como repetida. O reforço é barato e só afeta o agente de referência.

### Mudança proposta: `et-periododegraca`, campo `instrucao`

**§2 OBJETIVO: antes** (fim da lista de perguntas)

```
1. Quando saiu do último emprego de carteira assinada ou quando pagou o INSS pela última vez (mês e ano, pode ser aproximado).
2. Se recebeu seguro-desemprego quando saiu do emprego.
3. Se pagou o INSS por conta própria depois disso (carnê ou MEI).
Regra interna, que nunca deve ser dita ao lead: ...
```

**§2 OBJETIVO: depois**

```
1. Quando saiu do último emprego de carteira assinada ou quando pagou o INSS pela última vez (mês e ano, pode ser aproximado).
2. Se recebeu seguro-desemprego quando saiu do emprego.
3. Se pagou o INSS por conta própria depois disso (carnê ou MEI).
4. Sequela, aposentadoria e advogado no caso: pergunte só o que NÃO aparece na conversa nem nos DADOS JÁ INFORMADOS. Nunca peça de novo, nem pergunte "além disso" ou "mais alguma", o que a pessoa já respondeu.
Se a mensagem nova da pessoa responde a uma pergunta feita antes (inclusive pelo atendimento anterior, como a da sequela), agradeça em poucas palavras e siga para a próxima pergunta que ainda falta.
Regra interna, que nunca deve ser dita ao lead: ...
```

**§3 DECISÃO, 1º item: antes**

```
- Estava coberto na data do acidente: antes de acionar tool `closer`, confirme sequela, aposentadoria e advogado no caso, se ainda faltarem (uma pergunta por vez). ...
```

**§3 DECISÃO, 1º item: depois**

```
- Estava coberto na data do acidente: antes de acionar tool `closer`, pergunte o que ainda faltar sobre sequela, aposentadoria e advogado no caso (uma pergunta por vez; o que já foi respondido não se pergunta de novo). ...
```

O resto do prompt não muda: §1, a regra "vá direto para a pergunta 2", a regra interna dos 12/24 meses, os demais itens
do §3, as duas frases exatas ("Pelo que você me contou, vale a pena..." e "Infelizmente, pelo que você me contou...") e o §4.

### Verificação feita (sem API)

- Comparação campo a campo: entre o original e o sugerido, a única diferença é `/agente/etapas/1/instrucao`.
- `catalogo.ferramentas_do_prompt` lê os mesmos destinos nas duas versões (`['closer', 'desqualificado']`, sem ações).
  O texto novo mantém "acionar tool `closer`".
- As duas frases exatas, que `transferencia_pela_frase` e a checagem `transferencia_sem_frase` usam, estão intactas.
- `python -m app.avaliacao rodar --falso --cenario 03 --agente avaliacao/agentes/catalogo_referencia_sugerido.json`:
  as 3 variantes (com_seguro, sem_seguro, extrator_sozinho) deram `ok`. O modo falso usa um modelo roteirizado, então
  isso só prova que o snapshot carrega e roda no motor. **Não prova** que o gpt-4.1-mini deixa de repetir a pergunta.

### Como validar de verdade (pendente: exige modo real, não feito aqui)

```
python -m app.avaliacao comparar --agente-a avaliacao/agentes/catalogo_referencia.json \
  --agente-b avaliacao/agentes/catalogo_referencia_sugerido.json --cenario 03 --teto-usd 1
```

Espera-se que, em `03_periodo_de_graca[extrator_sozinho]`, o turno 4 siga direto para o seguro-desemprego, sem
`pergunta_repetida`. Se a mudança se confirmar, copie a nova `instrucao` para o `catalogo_referencia.json`, ou troque o
arquivo inteiro.

### Ligado a outras áreas (não corrigido aqui)

- **SDR transferindo cedo** (causa primária): o SDR não deve perguntar e transferir no mesmo turno. Se transferir,
  quem recebe precisa saber que a última pergunta foi dele.
- **Extrator do catálogo sem fatos de qualificação** (`app/cerebro/catalogo.py`): se ele capturar `sequela`,
  `sequela_descricao`, `aposentado` e `advogado_no_caso`, esses fatos passam a aparecer em "DADOS JÁ INFORMADOS". Isso
  resolve a falha pela raiz e vale para todos os escritórios.
- No mesmo caso, o turno 7 mostra `transferencia_sem_frase`: a IA disse a frase de desqualificação com "infelizmente"
  fora do lugar. É outro achado, não tratado aqui.
