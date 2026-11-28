// Passo "Roteiro gravado" do Início: antes de ir gravar, a pessoa escolhe COMO quer os áudios do agente.
// - Gravar com a voz da equipe  -> /roteiros (roteiro de gravação por produto)
// - Usar áudios prontos (IA)    -> /roteiros/vozes (escolhe a voz e em qual produto usar)
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, Mic, Sparkles } from "lucide-react";
import { Modal } from "@/componentes/ui";

const OPCOES = [
  {
    chave: "equipe",
    para: "/roteiros",
    icone: Mic,
    cor: ["#12c94a", "#00852a"],
    titulo: "Gravar com a voz da sua equipe",
    texto: "Você grava cada parte do roteiro pelo próprio painel, no celular ou no computador.",
    beneficios: [
      "Atendimento com a voz de quem é do escritório",
      "Pode falar o nome do escritório, do advogado e os seus honorários",
      "Passa mais confiança e costuma converter mais",
    ],
    cta: "Gravar o roteiro",
  },
  {
    chave: "ia",
    para: "/roteiros/vozes",
    icone: Sparkles,
    cor: ["#7c6cff", "#4b3fd1"],
    titulo: "Usar áudios prontos gerados por IA",
    texto: "Você escolhe uma voz e os áudios de todo o roteiro já entram no produto.",
    beneficios: [
      "Ativação na hora, sem gravar nada",
      "Roteiro completo, com todas as partes, pronto para usar",
      "Você pode trocar por gravações próprias quando quiser",
    ],
    cta: "Ver as vozes prontas",
  },
] as const;

export function ModalEscolhaAudios({ aoFechar }: { aoFechar: () => void }) {
  const navegar = useNavigate();
  return (
    <Modal titulo="Como você quer os áudios do agente?" largura={760} aoFechar={aoFechar}
      texto="O agente manda áudios em cada parte do atendimento (como funciona, honorários, contrato...). Escolha um caminho: dá para mudar depois."
      rodape={<button type="button" className="btn" onClick={aoFechar}>Agora não</button>}>
      <style>{ESTILO}</style>
      <div className="esc-aud-grade">
        {OPCOES.map((o) => {
          const Icone = o.icone;
          return (
            <button key={o.chave} type="button" className="esc-aud-op" data-autofocus={o.chave === "equipe" ? true : undefined}
              style={{ ["--c1" as string]: o.cor[0], ["--c2" as string]: o.cor[1] }}
              onClick={() => { aoFechar(); navegar(o.para); }}>
              <span className="esc-aud-icone"><Icone className="size-5" /></span>
              <b className="esc-aud-titulo">{o.titulo}</b>
              <span className="esc-aud-texto">{o.texto}</span>
              <ul className="esc-aud-lista">
                {o.beneficios.map((b) => <li key={b}><Check className="size-3.5" />{b}</li>)}
              </ul>
              <span className="esc-aud-cta">{o.cta} <ArrowRight className="size-4" /></span>
            </button>
          );
        })}
      </div>
    </Modal>
  );
}

const ESTILO = `
.esc-aud-grade { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
@media (max-width: 640px) { .esc-aud-grade { grid-template-columns: 1fr; } }
.esc-aud-op { text-align: left; display: flex; flex-direction: column; gap: 8px; padding: 18px; border-radius: 16px;
  border: 1px solid var(--line, #E2E9E4); background: #fff; cursor: pointer; transition: border-color .18s, box-shadow .18s, transform .18s; }
.esc-aud-op:hover, .esc-aud-op:focus-visible { border-color: var(--c1); box-shadow: 0 14px 30px -18px var(--c2); transform: translateY(-2px); outline: none; }
.esc-aud-icone { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; color: #fff;
  background-image: linear-gradient(135deg, var(--c1), var(--c2)); box-shadow: inset 0 1px 0 rgba(255,255,255,.4), 0 8px 16px -10px var(--c2); }
.esc-aud-titulo { font-size: 15px; color: #101828; line-height: 1.3; }
.esc-aud-texto { font-size: 13px; color: #475467; line-height: 1.45; }
.esc-aud-lista { list-style: none; margin: 2px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.esc-aud-lista li { display: flex; gap: 7px; align-items: flex-start; font-size: 12.5px; color: #344054; line-height: 1.4; }
.esc-aud-lista svg { color: var(--c2); flex-shrink: 0; margin-top: 2px; }
.esc-aud-cta { margin-top: auto; padding-top: 10px; display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--c2); }
@media (prefers-reduced-motion: reduce) { .esc-aud-op { transition: none; } .esc-aud-op:hover { transform: none; } }
`;
