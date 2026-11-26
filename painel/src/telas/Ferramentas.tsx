import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bell, FileText, Library, Lock, Send } from "lucide-react";
import type { Agente } from "../api";
import { Cabecalho, Carregando, Modal, Vazio, useCarregar } from "../componentes/ui";
import { MediaLibrary } from "@/components/agent/MediaLibrary";

/** Ferramentas: recursos extras dos agentes num lugar só (como no painel antigo). */
export function TelaFerramentas() {
  const navegar = useNavigate();
  const [followup, setFollowup] = useState(false);
  const [midia, setMidia] = useState(false);
  return (
    <>
      <Cabecalho eyebrow="Recursos extras" titulo="Ferramentas"
        texto="Recursos extras para potencializar seus agentes: follow-up, avisos, mídias e contratos num só lugar." />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
        <Cartao icone={<Send />} titulo="Follow-Up" disponivel onClick={() => setFollowup(true)}
          texto="Cadências automáticas de reengajamento por etapa do funil: recupere leads parados sem esforço manual." />
        <Cartao icone={<Bell />} titulo="Avisos no WhatsApp" disponivel onClick={() => navegar("/avisos")}
          texto="Seja avisado no WhatsApp quando algo importante acontecer com um cliente: novos leads, contratos assinados e mais." />
        <Cartao icone={<Library />} titulo="Biblioteca de Mídia" disponivel onClick={() => setMidia(true)}
          texto="Áudios, vídeos, documentos e imagens num só lugar, para usar nos roteiros dos agentes." />
        <Cartao icone={<FileText />} titulo="Resumo de Contratos"
          texto="Visão consolidada dos contratos: status de assinatura e o resumo da conversa de cada cliente." />
      </div>
      {followup && <EscolherAgenteFollowup aoFechar={() => setFollowup(false)} />}
      <MediaLibrary open={midia} onOpenChange={setMidia} />
    </>
  );
}

function Cartao({ icone, titulo, texto, disponivel = false, onClick }: { icone: ReactNode; titulo: string; texto: string; disponivel?: boolean; onClick?: () => void }) {
  return (
    <button type="button" className="panel" disabled={!disponivel} onClick={onClick}
      style={{ textAlign: "left", padding: 20, display: "flex", flexDirection: "column", gap: 10, cursor: disponivel ? "pointer" : "default", opacity: disponivel ? 1 : 0.6, minHeight: 200 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ width: 42, height: 42, borderRadius: 12, display: "grid", placeItems: "center", border: "1px solid #eef1f5", background: "#fafbfc" }}>{icone}</span>
        {disponivel
          ? <span className="chip ac">● Disponível</span>
          : <span className="chip"><Lock size={11} /> Em breve</span>}
      </div>
      <b style={{ fontSize: 15 }}>{titulo}</b>
      <span className="muted" style={{ fontSize: 13, lineHeight: 1.5, flex: 1 }}>{texto}</span>
      <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, fontWeight: 600 }}>
        {disponivel ? "Abrir" : "Em breve"}{disponivel && <ArrowRight size={15} />}
      </span>
    </button>
  );
}

/** O follow-up é de cada agente: escolhe o agente e abre a aba de follow-up dele. */
function EscolherAgenteFollowup({ aoFechar }: { aoFechar: () => void }) {
  const navegar = useNavigate();
  const { dados, erro } = useCarregar<Agente[]>("/agentes");
  return (
    <Modal titulo="Follow-up" texto="Escolha o agente para ver e ajustar a cadência de follow-up." aoFechar={aoFechar}
      rodape={<><span className="sp" /><button className="btn" onClick={aoFechar}>Fechar</button></>}>
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? <Vazio>Nenhum agente ainda. Ative um produto na Biblioteca.</Vazio> : (
        <div className="lst"><table><tbody>{dados.map((a) => (
          <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => navegar(`/agentes/${a.id}/followup`)}>
            <td className="t">{a.nome}</td>
            <td className="s">{a.situacao === "ativo" ? "ativo" : "pausado"}</td>
            <td style={{ textAlign: "right" }}><ArrowRight size={15} /></td>
          </tr>
        ))}</tbody></table></div>
      )}
    </Modal>
  );
}
