// Passo "Criar o CRM" do Início: mostra as etapas que a LawChat usa, manda criar o painel no CRM e, no "Já criei o
// CRM", lê os painéis da conta e faz a pessoa marcar qual coluna é cada etapa da IA (com sugestão pelo nome).
// Grava em PUT /api/integracoes/crm/etapas (o mesmo lugar que o CRM automático e as automações leem).
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowLeft, ArrowRight, Ban, Check, CheckCircle2, ExternalLink, Info, RefreshCw, Save } from "lucide-react";
import { api, enviar } from "@/api";
import { Alerta, Carregando, Modal, useAcao } from "@/componentes/ui";

interface Coluna { id: string; titulo: string }
interface PainelCrm { id: string; titulo: string; etapas: Coluna[] }

/** As 6 colunas fixas do CRM da IA (app/gestao/painel_crm_padrao.py), na ordem, com o momento de cada uma. */
export const ETAPAS_DA_IA: { tipo: string; titulo: string; momento: string; faz: string; sinonimos: string[] }[] = [
  { tipo: "SDR", titulo: "📞 SDR", momento: "Quando o lead chega (primeiro contato)",
    faz: "A IA coloca aqui todo lead novo enquanto faz as perguntas iniciais.",
    sinonimos: ["sdr", "novolead", "novoslead", "entrada", "primeirocontato", "triagem", "lead", "novo"] },
  { tipo: "COMERCIAL", titulo: "🛒 Comercial", momento: "Quando o lead é qualificado",
    faz: "A IA move para cá quem tem direito e está pronto para fechar.",
    sinonimos: ["comercial", "qualificado", "qualificacao", "negociacao", "closer", "vendas"] },
  { tipo: "CONTRATO", titulo: "📄 Contrato em Elaboração", momento: "Quando o contrato está sendo preparado",
    faz: "A IA move para cá enquanto junta os dados e gera o contrato.",
    sinonimos: ["contratoemelaboracao", "elaboracao", "documentacao", "coletadedados", "contrato"] },
  { tipo: "AGUARDANDO_ASSINATURA", titulo: "✍️ Aguardando Assinatura", momento: "Quando o contrato é enviado para assinar",
    faz: "A IA move para cá assim que manda o link de assinatura.",
    sinonimos: ["aguardandoassinatura", "aguardando", "enviado", "assinatura"] },
  { tipo: "CONTRATO_ASSINADO", titulo: "✅ Contrato Assinado", momento: "Quando o cliente assina o contrato",
    faz: "A IA move para cá quando a assinatura é confirmada.",
    sinonimos: ["contratoassinado", "assinado", "ganho", "fechado", "cliente"] },
  { tipo: "DESQUALIFICADO", titulo: "❌ Desqualificado", momento: "Quando o lead não tem direito",
    faz: "A IA move para cá quem não tem direito ou desistiu.",
    sinonimos: ["desqualificado", "naoqualificado", "semdireito", "perdido", "descartado"] },
];

/** Valor do select para "Não uso esta etapa" (o escritório não tem essa coluna no CRM). */
const SEM_USO = "__sem_uso__";

/** A coluna escolhida tem nome parecido com a etapa? (só para avisar "confira", nunca bloqueia) */
function nomeCombina(etapa: (typeof ETAPAS_DA_IA)[number], titulo: string): boolean {
  const k = chaveDoTitulo(titulo);
  return k === chaveDoTitulo(etapa.titulo) || etapa.sinonimos.some((s) => k.includes(s));
}

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
.crm-passo-aviso { display: flex; gap: 12px; align-items: flex-start; padding: 12px 14px; border-radius: 12px;
  background: #F0FAF3; border: 1px solid #CDEBD6; color: #14532D; font-size: 13px; line-height: 1.5; margin-bottom: 4px; }
.crm-passo-aviso b { display: block; font-size: 13.5px; margin-bottom: 2px; }
.crm-passo-aviso svg { flex-shrink: 0; margin-top: 2px; color: #16A34A; }
.crm-marcar { display: grid; gap: 10px; margin: 12px 0 4px; }
.crm-marcar-linha { display: grid; grid-template-columns: 28px minmax(0, 1fr) 22px minmax(0, 1fr); gap: 12px; align-items: center;
  padding: 12px 14px; border: 1px solid var(--line, #E2E9E4); border-radius: 14px; background: #fff; transition: border-color .15s, background .15s; }
.crm-marcar-linha.is-ok { border-color: #BBE5C8; background: #FAFEFB; }
.crm-marcar-linha.is-falta { border-color: #F5D9A8; background: #FFFCF5; }
.crm-marcar-linha.is-sem-uso { background: #F9FAFB; border-style: dashed; }
.crm-marcar-linha.is-sem-uso .crm-marcar-momento { opacity: .7; }
.crm-marcar-n { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; font-size: 12.5px; font-weight: 700;
  background: #F2F4F7; color: #475467; }
.crm-marcar-linha.is-ok .crm-marcar-n { background: #DCFCE7; color: #15803D; }
.crm-marcar-momento b { display: block; font-size: 13.5px; color: #101828; line-height: 1.35; }
.crm-marcar-momento small { display: block; font-size: 12px; color: #667085; margin-top: 2px; line-height: 1.4; }
.crm-marcar-seta { color: #98A2B3; }
.crm-marcar-escolha label { display: block; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
  color: #667085; margin-bottom: 4px; }
.crm-marcar-escolha select { width: 100%; }
.crm-marcar-estado { display: flex; align-items: center; gap: 4px; font-size: 11.5px; margin-top: 4px; }
.crm-marcar-estado.ok { color: #15803D; } .crm-marcar-estado.conferir { color: #B45309; } .crm-marcar-estado.falta { color: #B45309; }
@media (max-width: 640px) {
  .crm-passo-etapa { grid-template-columns: 1fr; gap: 6px; }
  .crm-marcar-linha { grid-template-columns: 28px minmax(0, 1fr); }
  .crm-marcar-seta { display: none; }
  .crm-marcar-escolha { grid-column: 1 / -1; }
}
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
  const colunasEscolhidas = Object.values(mapa).filter((c) => c && c !== SEM_USO);
  const repetida = new Set(colunasEscolhidas).size !== colunasEscolhidas.length;

  const salvar = () => executar(async () => {
    if (!painel) return;
    const etapas_por_tipo = Object.fromEntries(Object.entries(mapa).filter(([, c]) => c && c !== SEM_USO));
    const etapas_sem_uso = Object.entries(mapa).filter(([, c]) => c === SEM_USO).map(([t]) => t);
    await enviar("/integracoes/crm/etapas", { id_painel: String(painel.id), titulo_painel: painel.titulo, etapas_por_tipo, etapas_sem_uso }, "PUT");
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
    <Modal titulo="Ligar as etapas da IA ao seu CRM" largura={800} aoFechar={aoFechar}
      texto="Para cada momento do atendimento, escolha a coluna do seu CRM onde o lead deve ficar."
      rodape={<><button type="button" className="btn" onClick={() => setVista("criar")}><ArrowLeft />Voltar</button><span className="sp" />
        <button type="button" className="btn pri" disabled={ocupado || !painel || !completo || repetida} onClick={salvar}><Save />Salvar etapas</button></>}>
      <style>{ESTILO}</style>
      {erro ? <Alerta tipo="bad">{erro}</Alerta> : paineis === null ? <Carregando /> : paineis.length === 0 ? (
        <Alerta tipo="warn">Nenhum painel encontrado no CRM. Crie o painel e clique em “Ler de novo”.</Alerta>
      ) : (
        <div className="form">
          <div className="crm-passo-aviso">
            <Info size={18} aria-hidden />
            <div><b>É assim que a IA conduz cada lead</b>
              Ao longo da conversa, a IA move o lead sozinha para a coluna que você escolher abaixo. Se marcar a coluna
              errada, o lead vai parar no lugar errado do CRM e a sua equipe perde o controle de quem está em cada fase.
              Confira com calma: deixamos sugerido pelo nome. Não tem alguma dessas colunas? Escolha “Não uso esta etapa” (só a SDR é obrigatória).</div>
          </div>
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
            <div className="crm-marcar">
              {ETAPAS_DA_IA.map((e, i) => {
                const escolhida = painel.etapas.find((c) => String(c.id) === mapa[e.tipo]);
                const semUso = mapa[e.tipo] === SEM_USO;
                const estado = semUso ? "sem_uso" : !escolhida ? "falta" : nomeCombina(e, escolhida.titulo) ? "ok" : "conferir";
                return (
                  <div key={e.tipo} className={`crm-marcar-linha ${estado === "falta" ? "is-falta" : estado === "sem_uso" ? "is-sem-uso" : "is-ok"}`}>
                    <span className="crm-marcar-n">{estado === "falta" ? i + 1 : estado === "sem_uso" ? <Ban size={14} /> : <Check size={14} />}</span>
                    <div className="crm-marcar-momento"><b>{e.momento}</b><small>{e.faz}</small></div>
                    <ArrowRight size={18} className="crm-marcar-seta" aria-hidden />
                    <div className="crm-marcar-escolha">
                      <label htmlFor={`crm-${e.tipo}`}>Coluna no seu CRM</label>
                      <select id={`crm-${e.tipo}`} value={mapa[e.tipo] ?? ""} onChange={(ev) => setMapa((m) => ({ ...m, [e.tipo]: ev.target.value }))}>
                        <option value="">Escolha a coluna…</option>
                        {painel.etapas.map((c) => <option key={c.id} value={String(c.id)}>{c.titulo}</option>)}
                        {e.tipo !== "SDR" && <option value={SEM_USO}>🚫 Não uso esta etapa</option>}
                      </select>
                      {estado === "sem_uso" && <span className="crm-marcar-estado">A IA não move o lead neste momento (o card fica onde está).</span>}
                      {estado === "falta" && <span className="crm-marcar-estado falta"><AlertTriangle size={12} />Escolha onde o lead fica neste momento</span>}
                      {estado === "conferir" && <span className="crm-marcar-estado conferir"><AlertTriangle size={12} />O nome é diferente da etapa: confira se é esta mesma</span>}
                      {estado === "ok" && <span className="crm-marcar-estado ok"><Check size={12} />Combina com a etapa {e.titulo}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {repetida && <Alerta tipo="warn">Cada etapa precisa de uma coluna diferente.</Alerta>}
          {!completo && painel && <p className="crm-passo-dica">Falta marcar {ETAPAS_DA_IA.filter((e) => !mapa[e.tipo]).length} etapa(s). Não tem a coluna? Crie no CRM e clique em “Ler de novo”, ou escolha “Não uso esta etapa”. <ArrowRight size={12} style={{ verticalAlign: -2 }} /></p>}
        </div>
      )}
    </Modal>
  );
}
