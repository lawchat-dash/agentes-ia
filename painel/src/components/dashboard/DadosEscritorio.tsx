// Dados do escritório: informações da firma guardadas uma vez e aplicadas a todos os agentes
// (GET/PUT /api/escritorio/dados, app/gestao/rotas_dados_escritorio.py). Na ativação, cada campo preenche os {{...}}
// do prompt que pedem a mesma coisa. Abre pelo passo "Dados do escritório" do Início e por Ajustes › Dados do escritório.
import { useEffect, useState } from "react";
import { Building2, Save } from "lucide-react";
import { api, enviar } from "@/api";
import { Cabecalho, Carregando, Modal, useAcao } from "@/componentes/ui";

export interface CampoDados { chave: string; rotulo: string; ajuda: string; exemplo: string; preenche: string[] }
export interface RespostaDados { campos: CampoDados[]; valores: Record<string, string>; preenchido: boolean }

/** Lê os dados do escritório (para a ativação preencher os {{...}}). Falha = sem dados (a ativação segue normal). */
export async function lerDadosDoEscritorio(): Promise<RespostaDados | null> {
  try {
    return await api<RespostaDados>("/escritorio/dados");
  } catch {
    return null;
  }
}

function useDados() {
  const [dados, setDados] = useState<RespostaDados | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [valores, setValores] = useState<Record<string, string>>({});
  useEffect(() => {
    let vivo = true;
    api<RespostaDados>("/escritorio/dados")
      .then((r) => { if (vivo) { setDados(r); setValores(r.valores ?? {}); } })
      .catch((e) => { if (vivo) setErro((e as Error).message); });
    return () => { vivo = false; };
  }, []);
  return { dados, erro, valores, setValores };
}

function Campos({ campos, valores, mudar }: { campos: CampoDados[]; valores: Record<string, string>; mudar: (k: string, v: string) => void }) {
  return (
    <div className="dados-esc-lista">
      {campos.map((c) => (
        <label key={c.chave} className="dados-esc-linha" htmlFor={`dados-${c.chave}`}>
          <span className="dados-esc-rotulo">
            <b>{c.rotulo}{c.chave === "nome" && <em className="dados-esc-obrig"> obrigatório</em>}</b>
            <small>{c.ajuda}</small>
          </span>
          <input id={`dados-${c.chave}`} className="inp" value={valores[c.chave] ?? ""} placeholder={`Ex.: ${c.exemplo}`}
            maxLength={300} onChange={(e) => mudar(c.chave, e.target.value)} />
        </label>
      ))}
    </div>
  );
}

const ESTILO = `
.dados-esc-lista { display: flex; flex-direction: column; border: 1px solid var(--line, #E2E9E4); border-radius: 12px; overflow: hidden; }
.dados-esc-linha { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: 14px; align-items: center;
  padding: 10px 14px; border-top: 1px solid var(--line, #E2E9E4); background: #fff; }
.dados-esc-linha:first-child { border-top: 0; }
.dados-esc-rotulo { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.dados-esc-rotulo b { font-size: 13.5px; color: #101828; }
.dados-esc-rotulo small { font-size: 12px; color: #667085; }
.dados-esc-obrig { font-style: normal; font-weight: 600; font-size: 10.5px; color: #00852A; margin-left: 6px; text-transform: uppercase; letter-spacing: .04em; }
.dados-esc-intro { display: flex; gap: 10px; align-items: flex-start; padding: 12px 14px; border-radius: 12px; background: #F2FBF4;
  border: 1px solid #CDEFD6; color: #0B5E27; font-size: 13px; line-height: 1.5; margin-bottom: 12px; }
.dados-esc-intro svg { flex: none; margin-top: 2px; }
@media (max-width: 640px) { .dados-esc-linha { grid-template-columns: 1fr; gap: 6px; } }
`;

function Intro() {
  return (
    <div className="dados-esc-intro"><Building2 size={16} aria-hidden />
      <span>Preencha uma vez. Estes dados valem para <b>todos os agentes</b>: na ativação, o prompt já vem com eles e você não precisa digitar de novo.</span>
    </div>
  );
}

/** Pop-up (Início › Primeiros passos). */
export function ModalDadosEscritorio({ aoFechar, aoSalvar }: { aoFechar: () => void; aoSalvar?: () => void }) {
  const { dados, erro, valores, setValores } = useDados();
  const { ocupado, executar } = useAcao();
  const salvar = () => executar(async () => {
    await enviar("/escritorio/dados", { valores }, "PUT");
    aoSalvar?.();
    aoFechar();
  }, "Dados do escritório salvos.");
  return (
    <Modal titulo="Dados do escritório" texto="Informações da firma aplicadas a todos os agentes." aoFechar={aoFechar} largura={760}
      rodape={<><button type="button" className="btn" onClick={aoFechar}>Depois</button><span className="sp" />
        <button type="button" className="btn pri" disabled={ocupado || !dados || !(valores.nome ?? "").trim()} onClick={salvar}><Save />Salvar dados</button></>}>
      <style>{ESTILO}</style>
      <Intro />
      {!dados ? <Carregando erro={erro} /> : <Campos campos={dados.campos} valores={valores} mudar={(k, v) => setValores((x) => ({ ...x, [k]: v }))} />}
    </Modal>
  );
}

/** Tela de Ajustes › Dados do escritório (mesmo formulário). */
export function TelaDadosEscritorio() {
  const { dados, erro, valores, setValores } = useDados();
  const { ocupado, executar } = useAcao();
  return (
    <div className="stack">
      <style>{ESTILO}</style>
      <Cabecalho eyebrow="Ajustes" titulo="Dados do escritório" texto="Informações da firma aplicadas a todos os agentes." />
      <div className="panel" style={{ padding: 16 }}>
        <Intro />
        {!dados ? <Carregando erro={erro} /> : (
          <>
            <Campos campos={dados.campos} valores={valores} mudar={(k, v) => setValores((x) => ({ ...x, [k]: v }))} />
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
              <button type="button" className="btn pri" disabled={ocupado || !(valores.nome ?? "").trim()}
                onClick={() => executar(async () => { await enviar("/escritorio/dados", { valores }, "PUT"); }, "Dados do escritório salvos.")}>
                <Save />Salvar dados do escritório
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
