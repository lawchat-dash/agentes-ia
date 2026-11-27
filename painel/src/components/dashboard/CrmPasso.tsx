// Passo "Criar o CRM" do Início: mostra as etapas que a LawChat usa, manda criar o painel no CRM e, no "Já criei o
// CRM", lê os painéis da conta e faz a pessoa marcar qual coluna é cada etapa da IA (com sugestão pelo nome).
// Grava em PUT /api/integracoes/crm/etapas (o mesmo lugar que o CRM automático e as automações leem).
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2, ExternalLink, RefreshCw, Save } from "lucide-react";
import { api, enviar } from "@/api";
import { Alerta, Carregando, Modal, useAcao } from "@/componentes/ui";

interface Coluna { id: string; titulo: string }
interface PainelCrm { id: string; titulo: string; etapas: Coluna[] }

/** As 6 colunas fixas do CRM da IA (app/gestao/painel_crm_padrao.py), na ordem, com o momento de cada uma. */
export const ETAPAS_DA_IA: { tipo: string; titulo: string; momento: string; sinonimos: string[] }[] = [
  { tipo: "SDR", titulo: "📞 SDR", momento: "Quando o lead chega (primeiro contato)",
    sinonimos: ["sdr", "novolead", "novoslead", "entrada", "primeirocontato", "triagem", "lead", "novo"] },
  { tipo: "COMERCIAL", titulo: "🛒 Comercial", momento: "Quando o lead é qualificado",
    sinonimos: ["comercial", "qualificado", "qualificacao", "negociacao", "closer", "vendas"] },
  { tipo: "CONTRATO", titulo: "📄 Contrato em Elaboração", momento: "Quando o contrato está sendo preparado",
    sinonimos: ["contratoemelaboracao", "elaboracao", "documentacao", "coletadedados", "contrato"] },
  { tipo: "AGUARDANDO_ASSINATURA", titulo: "✍️ Aguardando Assinatura", momento: "Quando o contrato é enviado para assinar",
    sinonimos: ["aguardandoassinatura", "aguardando", "enviado", "assinatura"] },
  { tipo: "CONTRATO_ASSINADO", titulo: "✅ Contrato Assinado", momento: "Quando o cliente assina o contrato",
    sinonimos: ["contratoassinado", "assinado", "ganho", "fechado", "cliente"] },
  { tipo: "DESQUALIFICADO", titulo: "❌ Desqualificado", momento: "Quando o lead não tem direito",
    sinonimos: ["desqualificado", "naoqualificado", "semdireito", "perdido", "descartado"] },
];

/** "✍️ Aguardando Assinatura" -> "aguardandoassinatura" (sem emoji, acento, espaço e caixa). */
export function chaveDoTitulo(titulo: string): string {
  return (titulo || "").normalize("NFKD").replace(/[^A-Za-z0-9]/g, "").toLowerCase();
}

/** Sugestão: para cada etapa, a coluna de nome igual; senão, a primeira cujo nome contém um sinônimo. Sem repetir coluna. */
export function sugerirColunas(colunas: Coluna[]): Record<string, string> {
  const usadas = new Set<string>();
  const saida: Record<string, string> = {};
  const chaves = colunas.map((c) => ({ id: String(c.id), k: chaveDoTitulo(c.titulo) }));
  for (const etapa of ETAPAS_DA_IA) {
    const exata = chaves.find((c) => !usadas.has(c.id) && c.k === chaveDoTitulo(etapa.titulo));
    const parecida = exata ?? etapa.sinonimos.map((s) => chaves.find((c) => !usadas.has(c.id) && c.k.includes(s))).find(Boolean);
    if (parecida) { saida[etapa.tipo] = parecida.id; usadas.add(parecida.id); }
  }
  return saida;
}

const ESTILO = `
.crm-passo-etapas { display: grid; gap: 8px; margin: 10px 0 4px; }
.crm-passo-etapa { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 12px; align-items: center;
  padding: 10px 12px; border: 1px solid var(--line, #E2E9E4); border-radius: 12px; background: #fff; }
.crm-passo-etapa b { display: block; font-size: 13.5px; color: #101828; }
.crm-passo-etapa small { display: block; font-size: 12px; color: #667085; }
.crm-passo-dica { font-size: 12.5px; color: #475467; margin: 0; line-height: 1.5; }
@media (max-width: 640px) { .crm-passo-etapa { grid-template-columns: 1fr; gap: 6px; } }
`;

export function ModalCrmPasso({ aoFechar, aoSalvar }: { aoFechar: () => void; aoSalvar?: () => void }) {
  const navegar = useNavigate();
  const [vista, setVista] = useState<"criar" | "marcar">("criar");
  const [paineis, setPaineis] = useState<PainelCrm[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [idPainel, setIdPainel] = useState("");
  const [mapa, setMapa] = useState<Record<string, string>>({});
  const { ocupado, executar } = useAcao();

  const ler = () => {
    setPaineis(null); setErro(null);
    api<{ paineis: PainelCrm[] }>("/integracoes/helena/paineis")
      .then((r) => {
        const lista = r.paineis ?? [];
        setPaineis(lista);
        // Painel sugerido: o que tem mais colunas parecidas com as etapas da IA.
        const melhor = [...lista].sort((a, b) => Object.keys(sugerirColunas(b.etapas)).length - Object.keys(sugerirColunas(a.etapas)).length)[0];
        if (melhor) { setIdPainel(String(melhor.id)); setMapa(sugerirColunas(melhor.etapas)); }
      })
      .catch((e) => setErro((e as Error).message));
  };
  useEffect(() => { if (vista === "marcar" && paineis === null && !erro) ler(); }, [vista]); // eslint-disable-line react-hooks/exhaustive-deps

  const painel = useMemo(() => (paineis ?? []).find((p) => String(p.id) === idPainel) ?? null, [paineis, idPainel]);
  const completo = ETAPAS_DA_IA.every((e) => mapa[e.tipo]);
  const repetida = new Set(Object.values(mapa)).size !== Object.values(mapa).filter(Boolean).length;

  const salvar = () => executar(async () => {
    if (!painel) return;
    await enviar("/integracoes/crm/etapas", { id_painel: String(painel.id), titulo_painel: painel.titulo, etapas_por_tipo: mapa }, "PUT");
    aoSalvar?.();
    aoFechar();
  }, "Etapas do CRM salvas. A IA já move os leads por elas.");

  if (vista === "criar") {
    return (
      <Modal titulo="Criar o CRM" largura={720} aoFechar={aoFechar}
        texto="Crie no CRM um painel com estas etapas. É por elas que a IA move cada lead sozinha."
        rodape={<><button type="button" className="btn" onClick={() => { aoFechar(); navegar("/crm"); }}><ExternalLink />Abrir o CRM</button><span className="sp" />
          <button type="button" className="btn pri" onClick={() => setVista("marcar")}><CheckCircle2 />Já criei o CRM</button></>}>
        <style>{ESTILO}</style>
        <p className="crm-passo-dica">Sugestão da LawChat: um painel com as 6 colunas abaixo, nesta ordem. Pode usar outros nomes; no próximo passo você marca qual coluna é cada etapa.</p>
        <div className="crm-passo-etapas">
          {ETAPAS_DA_IA.map((e, i) => (
            <div key={e.tipo} className="crm-passo-etapa">
              <span><b>{i + 1}. {e.titulo}</b></span>
              <small>{e.momento}</small>
            </div>
          ))}
        </div>
      </Modal>
    );
  }

  return (
    <Modal titulo="Marcar as etapas do CRM" largura={760} aoFechar={aoFechar}
      texto="Escolha o painel e diga, para cada momento, em qual coluna o lead deve ficar. Já vem sugerido pelo nome."
      rodape={<><button type="button" className="btn" onClick={() => setVista("criar")}><ArrowLeft />Voltar</button><span className="sp" />
        <button type="button" className="btn pri" disabled={ocupado || !painel || !completo || repetida} onClick={salvar}><Save />Salvar etapas</button></>}>
      <style>{ESTILO}</style>
      {erro ? <Alerta tipo="bad">{erro}</Alerta> : paineis === null ? <Carregando /> : paineis.length === 0 ? (
        <Alerta tipo="warn">Nenhum painel encontrado no CRM. Crie o painel e clique em “Ler de novo”.</Alerta>
      ) : (
        <div className="form">
          <div className="field">
            <label htmlFor="crm-painel">Painel</label>
            <div style={{ display: "flex", gap: 8 }}>
              <select id="crm-painel" value={idPainel} onChange={(e) => {
                setIdPainel(e.target.value);
                const p = paineis.find((x) => String(x.id) === e.target.value);
                setMapa(p ? sugerirColunas(p.etapas) : {});
              }}>
                {paineis.map((p) => <option key={p.id} value={String(p.id)}>{p.titulo} ({p.etapas.length} colunas)</option>)}
              </select>
              <button type="button" className="btn" onClick={ler}><RefreshCw />Ler de novo</button>
            </div>
          </div>
          {painel && (
            <div className="crm-passo-etapas">
              {ETAPAS_DA_IA.map((e) => (
                <label key={e.tipo} className="crm-passo-etapa" htmlFor={`crm-${e.tipo}`}>
                  <span><b>{e.momento}</b><small>Etapa da IA: {e.titulo}</small></span>
                  <select id={`crm-${e.tipo}`} value={mapa[e.tipo] ?? ""} onChange={(ev) => setMapa((m) => ({ ...m, [e.tipo]: ev.target.value }))}>
                    <option value="">Escolha a coluna…</option>
                    {painel.etapas.map((c) => <option key={c.id} value={String(c.id)}>{c.titulo}</option>)}
                  </select>
                </label>
              ))}
            </div>
          )}
          {repetida && <Alerta tipo="warn">Cada etapa precisa de uma coluna diferente.</Alerta>}
          {!completo && painel && <p className="crm-passo-dica">Falta marcar {ETAPAS_DA_IA.filter((e) => !mapa[e.tipo]).length} etapa(s). Não tem a coluna? Crie no CRM e clique em “Ler de novo”. <ArrowRight size={12} style={{ verticalAlign: -2 }} /></p>}
        </div>
      )}
    </Modal>
  );
}
