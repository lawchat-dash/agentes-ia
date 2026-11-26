import { useEffect } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import type { CampoDef, Definicao, EtapaDef, RegraDef } from "../api";
import { Alerta, Painel } from "../componentes/ui";

/** 'Situação de trabalho' -> 'situacao_de_trabalho' (igual ao servidor). */
export function chaveDe(texto: string): string {
  const sem = texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  if (!sem) return "campo";
  return (/^[a-z]/.test(sem) ? sem : "c_" + sem).slice(0, 40);
}

const TIPOS_CAMPO: Record<CampoDef["tipo"], string> = {
  texto: "Texto", sim_nao: "Sim ou não", escolha: "Escolha", numero: "Número", data: "Data (mês/ano)",
};
const OPERADORES: Record<string, string> = { igual: "é", diferente: "não é", maior: "é maior que", menor: "é menor que", respondido: "foi respondido" };
const RESERVADAS = new Set(["pediu_humano", "pediu_para_parar", "engano", "fatos", "sinais", "intencoes"]);

/** Confere a definição antes de enviar (o servidor confere de novo). */
export function problemasDa(d: Definicao): string[] {
  const problemas: string[] = [];
  const etapas = d.etapas.map((e) => e.codigo);
  const campos = d.campos.map((c) => c.chave);
  if (!d.etapas.length) problemas.push("Crie pelo menos uma etapa.");
  if (d.etapas[0]?.tipo === "terminal") problemas.push("A primeira etapa precisa ser de conversa.");
  if (new Set(etapas).size !== etapas.length) problemas.push("Há duas etapas com o mesmo nome.");
  if (new Set(campos).size !== campos.length) problemas.push("Há dois campos com o mesmo nome.");
  d.campos.forEach((c) => {
    if (RESERVADAS.has(c.chave)) problemas.push(`O nome do campo "${c.nome}" é reservado.`);
    if (c.tipo === "escolha" && c.opcoes.filter((o) => o.trim()).length < 2) problemas.push(`O campo "${c.nome}" precisa de pelo menos duas opções.`);
  });
  d.regras.forEach((r, i) => {
    if (!etapas.includes(r.ir_para)) problemas.push(`A regra ${i + 1} leva para uma etapa que não existe.`);
    if (r.quando.tipo === "campo" && !campos.includes(r.quando.campo ?? "")) problemas.push(`A regra ${i + 1} usa um campo que não existe.`);
  });
  return problemas;
}

export function EditorDefinicao({ valor, aoMudar, aoErro }: { valor: Definicao; aoMudar: (d: Definicao) => void; aoErro?: (e: string | null) => void }) {
  const d = valor;
  const problemas = problemasDa(d);
  useEffect(() => { aoErro?.(problemas[0] ?? null); }, [problemas.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const mudar = (parcial: Partial<Definicao>) => aoMudar({ ...d, ...parcial });
  const mudarCampo = (i: number, parcial: Partial<CampoDef>) =>
    mudar({ campos: d.campos.map((c, j) => (j === i ? { ...c, ...parcial } : c)) });
  const mudarEtapa = (i: number, parcial: Partial<EtapaDef>) => {
    const antiga = d.etapas[i].codigo;
    const etapas = d.etapas.map((e, j) => (j === i ? { ...e, ...parcial } : e));
    const nova = etapas[i].codigo;
    // renomear a etapa atualiza campos e regras que apontam para ela
    mudar({
      etapas,
      campos: nova === antiga ? d.campos : d.campos.map((c) => (c.etapa === antiga ? { ...c, etapa: nova } : c)),
      regras: nova === antiga ? d.regras : d.regras.map((r) => ({ ...r, de: r.de === antiga ? nova : r.de, ir_para: r.ir_para === antiga ? nova : r.ir_para })),
    });
  };
  const mudarRegra = (i: number, parcial: Partial<RegraDef>) => mudar({ regras: d.regras.map((r, j) => (j === i ? { ...r, ...parcial } : r)) });
  const mover = <T,>(lista: T[], i: number, delta: number): T[] => {
    const nova = [...lista];
    const [item] = nova.splice(i, 1);
    nova.splice(Math.max(0, Math.min(nova.length, i + delta)), 0, item);
    return nova;
  };
  const nomeEtapa = (codigo: string | null) => d.etapas.find((e) => e.codigo === codigo)?.nome ?? codigo ?? "qualquer etapa";

  return (
    <div className="stack">
      <Painel titulo="Objetivo do agente">
        <div className="form">
          <label className="field"><span className="lbl">O que este agente faz</span>
            <input value={d.objetivo} maxLength={500} onChange={(e) => mudar({ objetivo: e.target.value })} placeholder="Ex.: Entender o caso trabalhista e marcar uma consulta" /></label>
          <label className="field"><span className="lbl">Quem é a pessoa do outro lado</span>
            <input value={d.contexto} maxLength={200} onChange={(e) => mudar({ contexto: e.target.value })} placeholder="Ex.: uma pessoa demitida com dúvida sobre os direitos" />
            <span className="ajuda">Ajuda a IA a entender o que extrair da conversa.</span></label>
        </div>
      </Painel>

      <Painel titulo="Etapas" acoes={<button className="btn sm" onClick={() => mudar({ etapas: [...d.etapas, { codigo: chaveDe("Etapa " + (d.etapas.length + 1)), nome: "Etapa " + (d.etapas.length + 1), tipo: "conversa", instrucao: "" }] })}><Plus />Etapa</button>}>
        <p className="sec" style={{ marginTop: 0 }}>A conversa começa na primeira. Etapa de <b>encerramento</b> manda a mensagem final e a IA sai da conversa.</p>
        <div className="stack">
          {d.etapas.map((e, i) => (
            <div key={i} className="panel" style={{ padding: 12 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span className="chip num">{i + 1}</span>
                <input className="inp" style={{ flex: 1, minWidth: 160 }} aria-label="Nome da etapa" value={e.nome}
                  onChange={(ev) => mudarEtapa(i, { nome: ev.target.value, codigo: chaveDe(ev.target.value) })} />
                <select className="inp" style={{ width: "auto" }} aria-label="Tipo da etapa" value={e.tipo} onChange={(ev) => mudarEtapa(i, { tipo: ev.target.value as EtapaDef["tipo"] })}>
                  <option value="conversa">Conversa</option><option value="terminal">Encerramento</option>
                </select>
                <button className="btn ghost sm" aria-label="Subir" disabled={i === 0} onClick={() => mudar({ etapas: mover(d.etapas, i, -1) })}><ArrowUp /></button>
                <button className="btn ghost sm" aria-label="Descer" disabled={i === d.etapas.length - 1} onClick={() => mudar({ etapas: mover(d.etapas, i, 1) })}><ArrowDown /></button>
                <button className="btn ghost sm bad" aria-label="Excluir etapa" disabled={d.etapas.length === 1} onClick={() => mudar({ etapas: d.etapas.filter((_, j) => j !== i) })}><Trash2 /></button>
              </div>
              <textarea className="inp codigo" rows={3} style={{ marginTop: 8 }} placeholder="Instrução da etapa: o objetivo e como a IA deve conduzir"
                value={e.instrucao} onChange={(ev) => mudarEtapa(i, { instrucao: ev.target.value })} />
              <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 8, fontSize: 13 }}>
                <label className="check"><input type="checkbox" checked={Boolean(e.fala_valores)} onChange={(ev) => mudarEtapa(i, { fala_valores: ev.target.checked })} />Pode citar honorários e valores</label>
                <label className="check"><input type="checkbox" checked={Boolean(e.pede_dados_pessoais)} onChange={(ev) => mudarEtapa(i, { pede_dados_pessoais: ev.target.checked })} />Pode pedir CPF, RG e endereço</label>
              </div>
            </div>
          ))}
        </div>
      </Painel>

      <Painel titulo="Campos que a IA precisa descobrir" acoes={<button className="btn sm" onClick={() => mudar({ campos: [...d.campos, { chave: chaveDe("Campo " + (d.campos.length + 1)), nome: "Campo " + (d.campos.length + 1), tipo: "texto", opcoes: [], descricao: "", etapa: d.etapas[0]?.codigo ?? null }] })}><Plus />Campo</button>}>
        <p className="sec" style={{ marginTop: 0 }}>A IA pergunta um campo por vez, na ordem, na etapa escolhida. Cada resposta só vale com o trecho que o lead escreveu.</p>
        {d.campos.length === 0 ? <p className="muted">Nenhum campo. Sem campos, o agente só conversa e segue as regras de intenção.</p> : (
          <div className="lst"><table>
            <thead><tr><th>Campo</th><th>Tipo</th><th>Etapa</th><th>Como perguntar</th><th /></tr></thead>
            <tbody>
              {d.campos.map((c, i) => (
                <tr key={i}>
                  <td style={{ minWidth: 160 }}><input className="inp" aria-label="Nome do campo" value={c.nome} onChange={(e) => mudarCampo(i, { nome: e.target.value, chave: chaveDe(e.target.value) })} />
                    <div className="s mono">{c.chave}</div></td>
                  <td style={{ minWidth: 150 }}>
                    <select className="inp" aria-label="Tipo do campo" value={c.tipo} onChange={(e) => mudarCampo(i, { tipo: e.target.value as CampoDef["tipo"] })}>
                      {Object.entries(TIPOS_CAMPO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                    {c.tipo === "escolha" && <input className="inp" style={{ marginTop: 6 }} placeholder="opções, separadas por vírgula" aria-label="Opções"
                      value={c.opcoes.join(", ")} onChange={(e) => mudarCampo(i, { opcoes: e.target.value.split(",").map((o) => o.trimStart()) })} />}
                  </td>
                  <td style={{ minWidth: 140 }}>
                    <select className="inp" aria-label="Etapa do campo" value={c.etapa ?? ""} onChange={(e) => mudarCampo(i, { etapa: e.target.value || null })}>
                      <option value="">Não perguntar</option>
                      {d.etapas.filter((e) => e.tipo === "conversa").map((e) => <option key={e.codigo} value={e.codigo}>{e.nome}</option>)}
                    </select>
                  </td>
                  <td style={{ minWidth: 220 }}><input className="inp" aria-label="Como perguntar" value={c.descricao} maxLength={500} onChange={(e) => mudarCampo(i, { descricao: e.target.value })} placeholder="Ex.: se tinha carteira assinada na época" /></td>
                  <td><button className="btn ghost sm bad" aria-label="Excluir campo" onClick={() => mudar({ campos: d.campos.filter((_, j) => j !== i) })}><Trash2 /></button></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </Painel>

      <Painel titulo="Intenções próprias" acoes={<button className="btn sm" onClick={() => mudar({ intencoes: [...d.intencoes, { chave: chaveDe("intencao " + (d.intencoes.length + 1)), descricao: "" }] })}><Plus />Intenção</button>}>
        <p className="sec" style={{ marginTop: 0 }}>Algo que o lead pode pedir a qualquer momento ("quer agendar", "perguntou o preço"). Pedir uma pessoa, parar e engano já existem.</p>
        {d.intencoes.map((it, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <input className="inp" style={{ maxWidth: 200 }} aria-label="Nome da intenção" value={it.chave} onChange={(e) => mudar({ intencoes: d.intencoes.map((x, j) => (j === i ? { ...x, chave: chaveDe(e.target.value) } : x)) })} />
            <input className="inp" aria-label="Quando marcar" placeholder="Quando o lead..." value={it.descricao} onChange={(e) => mudar({ intencoes: d.intencoes.map((x, j) => (j === i ? { ...x, descricao: e.target.value } : x)) })} />
            <button className="btn ghost sm bad" aria-label="Excluir intenção" onClick={() => mudar({ intencoes: d.intencoes.filter((_, j) => j !== i) })}><Trash2 /></button>
          </div>
        ))}
      </Painel>

      <Painel titulo="Regras de passagem" sem_corpo acoes={<button className="btn sm" onClick={() => mudar({ regras: [...d.regras, { de: d.etapas[0]?.codigo ?? null, quando: { tipo: "etapa_completa" }, ir_para: d.etapas[1]?.codigo ?? d.etapas[0]?.codigo ?? "", motivo: "" }] })}><Plus />Regra</button>}>
        <p className="sec" style={{ margin: "0 16px 10px" }}>O código confere na ordem e a primeira que valer decide. Sem regra válida, o lead fica na etapa e a IA pergunta o próximo campo.</p>
        {d.regras.length === 0 && <p className="muted" style={{ margin: "0 16px 16px" }}>Nenhuma regra: o lead fica sempre na primeira etapa.</p>}
        {d.regras.map((r, i) => (
          <div key={i} className="regra" style={{ gridTemplateColumns: "auto minmax(0,1fr) auto" }}>
            <span className="chip num">{i + 1}</span>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", fontSize: 13 }}>
              <span>Na etapa</span>
              <select className="inp" style={{ width: "auto" }} aria-label="Etapa de origem" value={r.de ?? ""} onChange={(e) => mudarRegra(i, { de: e.target.value || null })}>
                <option value="">qualquer</option>
                {d.etapas.filter((e) => e.tipo === "conversa").map((e) => <option key={e.codigo} value={e.codigo}>{e.nome}</option>)}
              </select>
              <span>quando</span>
              <select className="inp" style={{ width: "auto" }} aria-label="Tipo de condição" value={r.quando.tipo} onChange={(e) => mudarRegra(i, { quando: { tipo: e.target.value as RegraDef["quando"]["tipo"], operador: e.target.value === "campo" ? "igual" : null } })}>
                <option value="etapa_completa">todos os campos da etapa forem respondidos</option>
                <option value="campo">um campo</option>
                <option value="intencao">o lead tiver a intenção</option>
              </select>
              {r.quando.tipo === "campo" && (<>
                <select className="inp" style={{ width: "auto" }} aria-label="Campo" value={r.quando.campo ?? ""} onChange={(e) => mudarRegra(i, { quando: { ...r.quando, campo: e.target.value } })}>
                  <option value="">escolher campo</option>
                  {d.campos.map((c) => <option key={c.chave} value={c.chave}>{c.nome}</option>)}
                </select>
                <select className="inp" style={{ width: "auto" }} aria-label="Comparação" value={r.quando.operador ?? "igual"} onChange={(e) => mudarRegra(i, { quando: { ...r.quando, operador: e.target.value } })}>
                  {Object.entries(OPERADORES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                {r.quando.operador !== "respondido" && (() => {
                  const campo = d.campos.find((c) => c.chave === r.quando.campo);
                  if (campo?.tipo === "escolha" || campo?.tipo === "sim_nao") {
                    const opcoes = campo.tipo === "sim_nao" ? ["sim", "nao"] : campo.opcoes.map(chaveDe);
                    return <select className="inp" style={{ width: "auto" }} aria-label="Valor" value={String(r.quando.valor ?? "")} onChange={(e) => mudarRegra(i, { quando: { ...r.quando, valor: e.target.value } })}>
                      <option value="">escolher</option>{opcoes.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>;
                  }
                  return <input className="inp" style={{ width: 140 }} aria-label="Valor" value={String(r.quando.valor ?? "")} onChange={(e) => mudarRegra(i, { quando: { ...r.quando, valor: e.target.value } })} />;
                })()}
              </>)}
              {r.quando.tipo === "intencao" && (
                <select className="inp" style={{ width: "auto" }} aria-label="Intenção" value={r.quando.intencao ?? ""} onChange={(e) => mudarRegra(i, { quando: { ...r.quando, intencao: e.target.value } })}>
                  <option value="">escolher</option>
                  {[...d.intencoes.map((x) => x.chave), "pediu_humano", "pediu_para_parar"].map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
              )}
              <em className="entao">ir para</em>
              <select className="inp" style={{ width: "auto" }} aria-label="Etapa de destino" value={r.ir_para} onChange={(e) => mudarRegra(i, { ir_para: e.target.value })}>
                {d.etapas.map((e) => <option key={e.codigo} value={e.codigo}>{e.nome}</option>)}
              </select>
              <input className="inp" style={{ flex: 1, minWidth: 160 }} aria-label="Motivo" placeholder="Motivo (aparece no histórico e na mensagem de encerramento)" value={r.motivo} onChange={(e) => mudarRegra(i, { motivo: e.target.value })} />
            </div>
            <div style={{ display: "flex", gap: 2 }}>
              <button className="btn ghost sm" aria-label="Subir regra" disabled={i === 0} onClick={() => mudar({ regras: mover(d.regras, i, -1) })}><ArrowUp /></button>
              <button className="btn ghost sm bad" aria-label="Excluir regra" onClick={() => mudar({ regras: d.regras.filter((_, j) => j !== i) })}><Trash2 /></button>
            </div>
          </div>
        ))}
        {d.regras.length > 0 && <p className="muted" style={{ margin: "8px 16px 14px", fontSize: 12 }}>Leitura: {d.regras.map((r) => `${nomeEtapa(r.de)} → ${nomeEtapa(r.ir_para)}`).join(" · ")}</p>}
      </Painel>

      <Painel titulo="Limites">
        <div className="grid2">
          <label className="field"><span className="lbl">O que a IA nunca deve fazer</span>
            <textarea rows={4} value={d.nunca.join("\n")} onChange={(e) => mudar({ nunca: e.target.value.split("\n") })} placeholder={"Um por linha. Ex.:\nprometer resultado\nfalar de valores antes da proposta"} />
            <span className="ajuda">Vai para as instruções da IA.</span></label>
          <label className="field"><span className="lbl">Palavras proibidas</span>
            <textarea rows={4} value={d.expressoes_proibidas.join("\n")} onChange={(e) => mudar({ expressoes_proibidas: e.target.value.split("\n") })} placeholder={"Uma por linha. Ex.:\ngarantido\nsem risco"} />
            <span className="ajuda">Se a resposta tiver alguma delas, a trava barra e a IA reescreve.</span></label>
        </div>
      </Painel>

      {problemas.length > 0 && <Alerta tipo="warn"><b>Ajuste antes de salvar:</b> {problemas.join(" ")}</Alerta>}
    </div>
  );
}
