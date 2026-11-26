import { useState, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bell, FileText, Library, Lock, Mic, Send } from "lucide-react";
import type { Agente } from "../api";
import { Cabecalho, Carregando, Modal, Vazio, useCarregar } from "../componentes/ui";
import { MediaLibrary } from "@/components/agent/MediaLibrary";
import "../estilo-ferramentas.css";

/** Ferramentas: recursos extras dos agentes num lugar só. */
export function TelaFerramentas() {
  const navegar = useNavigate();
  const [followup, setFollowup] = useState(false);
  const [midia, setMidia] = useState(false);
  return (
    <>
      <Cabecalho eyebrow="Recursos extras" titulo="Ferramentas"
        texto="Recursos extras para potencializar seus agentes: follow-up, avisos, mídias, roteiros de áudio e contratos num só lugar." />
      <div className="fer-grade">
        <Cartao icone={<Send />} cor="#DB2777" titulo="Follow-Up" onClick={() => setFollowup(true)}
          texto="Cadências automáticas de reengajamento por etapa do funil: recupere leads parados sem esforço manual." />
        <Cartao icone={<Bell />} cor="#2563EB" titulo="Avisos no WhatsApp" onClick={() => navegar("/avisos")}
          texto="Seja avisado no WhatsApp quando algo importante acontecer com um cliente: novos leads, contratos assinados e mais." />
        <Cartao icone={<Library />} cor="#7C3AED" titulo="Biblioteca de Mídia" onClick={() => setMidia(true)}
          texto="Áudios, vídeos e imagens num só lugar, prontos para inserir nos prompts dos agentes." />
        <Cartao icone={<Mic />} cor="#0891B2" titulo="Roteiros" novo onClick={() => navegar("/ferramentas/roteiros")}
          texto="Escreva o texto que a equipe vai gravar, grave direto pelo navegador e use o áudio nos prompts." />
        <Cartao icone={<FileText />} cor="#B26B00" titulo="Resumo de Contratos" emBreve
          texto="Visão consolidada dos contratos: status de assinatura e o resumo da conversa de cada cliente." />
      </div>
      {followup && <EscolherAgenteFollowup aoFechar={() => setFollowup(false)} />}
      <MediaLibrary open={midia} onOpenChange={setMidia} />
    </>
  );
}

function Cartao({ icone, cor, titulo, texto, emBreve = false, novo = false, onClick }: {
  icone: ReactNode; cor: string; titulo: string; texto: string; emBreve?: boolean; novo?: boolean; onClick?: () => void;
}) {
  return (
    <button type="button" className="fer-card" disabled={emBreve} onClick={onClick} style={{ "--fer-cor": cor } as CSSProperties}>
      <div className="fer-topo">
        <span className="fer-ic" aria-hidden>{icone}</span>
        {emBreve ? <span className="chip"><Lock size={11} /> Em breve</span>
          : novo ? <span className="chip fer-novo">Novo</span>
          : <span className="chip ok"><span className="d" /> Disponível</span>}
      </div>
      <b>{titulo}</b>
      <p>{texto}</p>
      <span className="fer-rodape">
        {emBreve ? "Em breve" : "Abrir"}
        {!emBreve && <ArrowRight aria-hidden />}
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
          <tr key={a.id} className="click" onClick={() => navegar(`/agentes/${a.id}/followup`)}>
            <td className="t">{a.nome}</td>
            <td className="s">{a.situacao === "ativo" ? "ativo" : "pausado"}</td>
            <td style={{ textAlign: "right" }}><ArrowRight size={15} /></td>
          </tr>
        ))}</tbody></table></div>
      )}
    </Modal>
  );
}
