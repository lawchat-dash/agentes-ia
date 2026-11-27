import { type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bell, FileText, Library, Lock, Mic, Send } from "lucide-react";
import { Cabecalho } from "../componentes/ui";
import SpotlightCard from "@/components/reactbits/SpotlightCard";
import "../estilo-ferramentas.css";

/** Ferramentas: recursos extras dos agentes num lugar só. */
export function TelaFerramentas() {
  const navegar = useNavigate();
  return (
    <>
      <Cabecalho eyebrow="Recursos extras" titulo="Ferramentas"
        texto="Recursos extras para potencializar seus agentes: follow-up, avisos, mídias, roteiros de áudio e contratos num só lugar." />
      <div className="fer-grade">
        <Cartao icone={<Send />} cor="#DB2777" titulo="Follow-Up" onClick={() => navegar("/ferramentas/followup")}
          texto="Cadências automáticas de reengajamento por etapa do funil: recupere leads parados sem esforço manual." />
        <Cartao icone={<Bell />} cor="#2563EB" titulo="Avisos no WhatsApp" onClick={() => navegar("/avisos")}
          texto="Seja avisado no WhatsApp quando algo importante acontecer com um cliente: novos leads, contratos assinados e mais." />
        <Cartao icone={<Library />} cor="#7C3AED" titulo="Biblioteca de Mídia" onClick={() => navegar("/ferramentas/midia")}
          texto="Áudios, vídeos e imagens num só lugar, prontos para inserir nos prompts dos agentes." />
        <Cartao icone={<Mic />} cor="#0891B2" titulo="Roteiros de gravação" novo onClick={() => navegar("/roteiros")}
          texto="Grave os áudios e vídeos de cada produto pelo navegador. Eles vão para a Biblioteca e entram no prompt na ativação." />
        <Cartao icone={<FileText />} cor="#B26B00" titulo="Resumo de contrato" novo onClick={() => navegar("/ferramentas/resumo-contrato")}
          texto="Quando o contrato é assinado, a IA escreve o resumo do caso para a equipe. Ajuste o prompt, o modelo e veja o consumo por agente." />
      </div>
    </>
  );
}

function Cartao({ icone, cor, titulo, texto, emBreve = false, novo = false, onClick }: {
  icone: ReactNode; cor: string; titulo: string; texto: string; emBreve?: boolean; novo?: boolean; onClick?: () => void;
}) {
  return (
    // Luz que segue o cursor dentro do cartão (SpotlightCard do React Bits), em verde bem suave.
    <SpotlightCard theme="light" className="fer-spot" spotlightColor="rgba(0, 188, 51, 0.55)" intensity={0.5} spotlightSize={260}
      borderGlow={0.5} flare={false}>
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
    </SpotlightCard>
  );
}
