// Entrada do painel.
//  - Tela principal (layout dividido): à esquerda o painel escuro com o que o LawChat faz; à direita o cartão
//    "Entrar no LawChat" com o código que a plataforma manda por e-mail ou SMS (POST /entrar/codigo e
//    /entrar/codigo/confirmar). "Entrar com senha" mostra o formulário de e-mail e senha (POST /entrar).
//  - Quem vem do botão dentro da plataforma (/entrar/helena no servidor) continua entrando sem senha; se a
//    plataforma recusar, o servidor volta com ?erro=... e mostramos o erro;
//  - /login (ou /acesso, ?equipe) → abre direto no formulário de senha;
//  - /superadmin → página própria do superadmin (só equipe LawChat; o servidor recusa quem é de escritório).
import { useEffect, useRef, useState, type ClipboardEvent, type CSSProperties, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import {
  AlertTriangle, ArrowLeft, ArrowRight, BarChart3, Bot, CalendarCheck, Eye, EyeOff, FileSignature, Loader2, Lock, Mail,
  MessageSquare, Repeat, ShieldCheck, Smartphone, Sparkles,
} from "lucide-react";
import Carousel, { type CarouselItem } from "@/components/reactbits/Carousel";
import BorderGlow from "@/components/reactbits/BorderGlow";
import BotaoBrilho from "@/components/reactbits/BotaoBrilho";
import LogoEscrita from "@/components/reactbits/LogoEscrita";
import { toast } from "sonner";
import { api } from "../api";
import { useSessao } from "../sessao";
import { Button } from "@/components/ui/button";
import { BlockedAccountDialog } from "@/components/auth/BlockedAccountDialog";
import logoMark from "@/assets/lawchat-logo.png";
import videoFundo from "@/assets/login-fundo.mp4";

const ERROS_DA_HELENA: Record<string, string> = {
  link_incompleto: "O link da LawChat veio incompleto. Abra a IA de novo pelo botão dentro da LawChat.",
  conta_sem_ia: "Esta conta da LawChat ainda não tem a IA da LawChat liberada. Fale com o suporte.",
  conta_suspensa: "A IA desta conta está suspensa. Fale com o suporte da LawChat.",
  helena_nao_conectada: "A conta ainda não está conectada à LawChat. A equipe LawChat precisa concluir o cadastro.",
  helena_indisponivel: "Não foi possível confirmar seu acesso com a LawChat agora. Tente de novo em instantes.",
  usuario_nao_encontrado: "Seu usuário não foi encontrado nesta conta da LawChat.",
  usuario_desativado: "Seu acesso foi desativado. Fale com o responsável do escritório.",
  assinatura_ausente: "O acesso precisa vir de dentro da LawChat.",
  assinatura_invalida: "O link de acesso não é válido. Abra de novo pela LawChat.",
  assinatura_expirada: "O link de acesso expirou. Abra de novo pela LawChat.",
  usuario_de_cliente: "Este e-mail é de um usuário de escritório cliente, não da equipe LawChat.",
};
const CHAVE_FORM = "agentesia_acesso_equipe";

function querFormulario(): boolean {
  const p = window.location.pathname;
  try {
    return p === "/login" || p === "/acesso" || new URLSearchParams(window.location.search).has("equipe")
      || sessionStorage.getItem(CHAVE_FORM) === "1";
  } catch {
    return p === "/login" || p === "/acesso";
  }
}

// ----- Estilo da landing (verde LawChat, dark, Space Grotesk) — copiado de pages/Auth.tsx -----
const brandStyle = `
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700;800&display=swap');
  .lcauth{--g1:#A7D7A4;--g2:#00BC33;--g3:#009926;--d9:#0B0D0F;--l0:#F8F9FB;--l2:#E2E5EA;--td:#111318;--tdm:#5F6570;--fs:'Space Grotesk',sans-serif;--fi:'Inter',sans-serif;
    position:relative;min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--d9);font-family:var(--fi);overflow:hidden}
  .lcauth-bg{position:absolute;inset:0;z-index:0;background:
    radial-gradient(ellipse 70% 50% at 50% 0%,rgba(0,188,51,.10) 0%,transparent 60%),
    radial-gradient(circle 500px at 18% 30%,rgba(0,188,51,.07),transparent 65%),
    radial-gradient(circle 520px at 82% 70%,rgba(167,215,164,.06),transparent 65%),var(--d9);
    animation:lcAmbient 12s ease-in-out infinite}
  .lcauth-grid{position:absolute;inset:0;z-index:0;
    background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
    background-size:60px 60px;mask-image:radial-gradient(ellipse 65% 55% at 50% 25%,black 20%,transparent 75%);
    -webkit-mask-image:radial-gradient(ellipse 65% 55% at 50% 25%,black 20%,transparent 75%);animation:lcDrift 24s linear infinite}
  .lcauth-orb{position:absolute;border-radius:50%;filter:blur(70px);pointer-events:none;z-index:0;animation:lcOrb 15s ease-in-out infinite}
  @keyframes lcAmbient{0%,100%{filter:brightness(1) saturate(1)}50%{filter:brightness(1.08) saturate(1.15)}}
  @keyframes lcDrift{from{background-position:0 0}to{background-position:60px 60px}}
  @keyframes lcOrb{0%,100%{transform:translate(0,0) scale(1);opacity:.55}33%{transform:translate(26px,-18px) scale(1.08);opacity:.8}66%{transform:translate(-18px,12px) scale(.96);opacity:.65}}
  @keyframes lcUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
  .lcauth-card{position:relative;z-index:1;width:100%;max-width:430px;animation:lcUp .5s cubic-bezier(.22,1,.36,1) both}
  .lcauth-panel{background:#fff;border:1px solid var(--l2);border-radius:24px;
    box-shadow:0 24px 60px -24px rgba(17,19,24,.18),0 2px 8px rgba(17,19,24,.04);padding:36px 32px}
  .lcauth-badge{display:inline-flex;align-items:center;gap:7px;padding:7px 15px;border-radius:100px;
    background:rgba(0,188,51,.08);border:1px solid rgba(0,188,51,.2);color:var(--g3);
    font-size:.74rem;font-weight:600;letter-spacing:.04em;box-shadow:0 2px 10px rgba(0,188,51,.1)}
  .lcauth-title{font-family:var(--fs);font-size:1.6rem;font-weight:700;color:var(--td);letter-spacing:-.02em;line-height:1.15}
  .lcauth-sub{color:var(--tdm);font-size:.9rem;line-height:1.6;margin-top:8px}
  .lcauth-label{font-size:.75rem;font-weight:600;color:#374151;letter-spacing:.01em}
  .lcauth-field{position:relative}
  .lcauth-ic{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:#9097A1;pointer-events:none}
  .lcauth-input{width:100%;height:48px;padding:0 44px;border-radius:14px;font-family:var(--fi);font-size:.92rem;
    color:var(--td);background:var(--l0);border:1px solid var(--l2);outline:none;
    transition:border-color .25s,box-shadow .25s,background .25s}
  .lcauth-input::placeholder{color:#A6ABB4}
  .lcauth-input:focus{border-color:rgba(0,188,51,.6);background:#fff;box-shadow:0 0 0 4px rgba(0,188,51,.12)}
  .lcauth-eye{position:absolute;right:10px;top:50%;transform:translateY(-50%);width:30px;height:30px;display:grid;place-items:center;
    color:#9097A1;background:none;border:none;cursor:pointer;border-radius:8px;transition:color .2s,background .2s}
  .lcauth-eye:hover{color:var(--td);background:rgba(17,19,24,.05)}
  .lcauth-btn{width:100%;height:48px;margin-top:6px;display:inline-flex;align-items:center;justify-content:center;gap:8px;
    border:none;cursor:pointer;border-radius:50px;font-family:var(--fs);font-size:.92rem;font-weight:600;color:#fff;
    background:linear-gradient(135deg,var(--g1),var(--g2));box-shadow:0 6px 20px rgba(0,188,51,.3),inset 0 1px 0 rgba(255,255,255,.25);
    transition:transform .35s cubic-bezier(.22,1,.36,1),box-shadow .35s,filter .25s}
  .lcauth-btn:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,188,51,.4),inset 0 1px 0 rgba(255,255,255,.3);filter:brightness(1.03)}
  .lcauth-btn:disabled{opacity:.7;cursor:default}
  .lcauth-link{color:var(--g3);font-weight:600;font-size:.78rem;text-decoration:none;transition:color .2s;background:none;border:none;padding:0;cursor:pointer;font-family:var(--fi)}
  .lcauth-link:hover{color:var(--g2);text-decoration:underline}
  .lcauth-nota{font-size:.78rem;line-height:1.55;color:var(--tdm);background:rgba(0,188,51,.06);border:1px solid rgba(0,188,51,.18);border-radius:12px;padding:10px 12px}
  .lcauth-foot{color:var(--tdm);font-size:.82rem;text-align:center;margin-top:22px;padding-top:18px;border-top:1px solid var(--l2)}
  .lcauth-trust{display:flex;align-items:center;justify-content:center;gap:18px;margin-top:18px;color:rgba(240,242,245,.5);font-size:.7rem;font-weight:500}
  .lcauth-trust span{display:inline-flex;align-items:center;gap:5px}
`;

const Background = () => (
  <>
    <div className="lcauth-bg" />
    <div className="lcauth-grid" />
    <div className="lcauth-orb" style={{ width: 320, height: 320, top: "-60px", left: "-40px", background: "rgba(0,188,51,.16)" }} />
    <div className="lcauth-orb" style={{ width: 280, height: 280, bottom: "-50px", right: "-30px", background: "rgba(167,215,164,.12)", animationDelay: "-6s" }} />
  </>
);

// ----- Layout dividido (tela principal de entrada) -----
const splitStyle = `
  .lcsplit{--g1:#A7D7A4;--g2:#00BC33;--g3:#009926;--d9:#0B0D0F;--l0:#F8F9FB;--l2:#E2E5EA;--td:#111318;--tdm:#5F6570;--fs:'Space Grotesk',sans-serif;--fi:'Inter',sans-serif;
    min-height:100vh;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);background:#F3F5F7;font-family:var(--fi);overflow-x:hidden}
  .lcsplit *{box-sizing:border-box}
  .lcsplit-esq{position:relative;margin:16px 0 16px 16px;border-radius:28px;overflow:hidden;background:var(--d9);color:#F0F2F5;
    display:flex;flex-direction:column;justify-content:space-between;padding:44px 48px;min-height:calc(100vh - 32px)}
  .lcsplit-esq>*{position:relative;z-index:1}
  .lcsplit-esq>.lcauth-bg,.lcsplit-esq>.lcauth-grid,.lcsplit-esq>.lcauth-orb{position:absolute;z-index:0}
  .lcsplit-esq>.lcsplit-video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0}
  .lcsplit-esq>.lcsplit-veu{position:absolute;inset:0;z-index:0;
    background:linear-gradient(180deg,rgba(2,12,7,0) 0%,rgba(2,12,7,.06) 22%,rgba(2,12,7,.42) 46%,rgba(2,12,7,.8) 66%,rgba(2,12,7,.95) 84%,#020c07 100%)}
  .lcsplit-baixo{margin-top:auto;display:flex;flex-direction:column}
  .lcsplit-texto{padding-top:32px}
  .lcsplit-marca{display:flex;align-items:center;gap:10px;font-family:var(--fs);font-weight:700;font-size:1.25rem;letter-spacing:-.01em}
  .lcsplit-marca img{height:30px;width:auto}
  .lcsplit-marca .le-logo{filter:drop-shadow(0 4px 14px rgba(0,0,0,.35))}
  .lcsplit-titulo{font-family:var(--fs);font-weight:700;font-size:clamp(2rem,3.4vw,3rem);line-height:1.08;letter-spacing:-.03em;max-width:15ch;margin:0}
  .lcsplit-titulo em{font-style:normal;background:linear-gradient(135deg,var(--g1),var(--g2));-webkit-background-clip:text;background-clip:text;color:transparent}
  .lcsplit-lista{list-style:none;padding:0;margin:26px 0 0;display:flex;flex-direction:column;gap:14px;max-width:440px}
  .lcsplit-lista li{display:flex;gap:12px;align-items:flex-start;font-size:.95rem;line-height:1.5;color:rgba(240,242,245,.78)}
  .lcsplit-lista b{color:#fff;font-weight:600}
  .lcsplit-carrossel{margin:20px 0 0 -10px;width:calc(100% + 20px);max-width:480px}
  .lcsplit-carrossel .carousel-icon{width:36px;height:36px;border-radius:11px;background:rgba(0,188,51,.16);border:1px solid rgba(0,188,51,.3);color:var(--g1)}
  .lcsplit-carrossel .carousel-title{font-family:var(--fs);font-size:1.02rem;font-weight:600}
  .lcsplit-carrossel .carousel-description{font-size:.86rem}
  .lcsplit-carrossel .carousel-stage{-webkit-backdrop-filter:none;backdrop-filter:none}
  .lcsplit-carrossel .carousel-bar-fill{background:#34e06b}
  .lcsplit-brilho{width:100%;max-width:420px;animation:lcUp .5s cubic-bezier(.22,1,.36,1) both}
  .lcsplit-brilho .lcsplit-card{border-color:transparent;box-shadow:none;animation:none}
  .lcsplit-brilho>.rb-glow-inner{overflow:visible}
  .lcsplit-ic{flex:none;width:34px;height:34px;border-radius:11px;display:grid;place-items:center;background:rgba(0,188,51,.14);border:1px solid rgba(0,188,51,.28);color:var(--g1)}
  .lcsplit-chat{display:flex;flex-direction:column;gap:10px;max-width:380px;margin-top:34px}
  .lcsplit-bolha{padding:11px 14px;border-radius:16px;font-size:.84rem;line-height:1.45;max-width:85%;animation:lcUp .6s cubic-bezier(.22,1,.36,1) both}
  .lcsplit-bolha.lead{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.08);border-bottom-left-radius:6px;align-self:flex-start}
  .lcsplit-bolha.ia{background:linear-gradient(135deg,rgba(0,188,51,.9),rgba(0,153,38,.9));color:#fff;border-bottom-right-radius:6px;align-self:flex-end}
  .lcsplit-rodape{font-size:.75rem;color:rgba(240,242,245,.55);display:flex;gap:16px;flex-wrap:wrap;margin-top:28px;padding-top:16px;border-top:1px solid rgba(255,255,255,.12)}
  .lcsplit-rodape span{display:inline-flex;align-items:center;gap:5px}
  .lcsplit-dir{display:grid;place-items:center;padding:32px 24px}
  .lcsplit-card{width:100%;max-width:420px;background:#fff;border:1px solid var(--l2);border-radius:24px;padding:36px 32px;
    box-shadow:0 24px 60px -28px rgba(17,19,24,.22),0 2px 8px rgba(17,19,24,.04);animation:lcUp .5s cubic-bezier(.22,1,.36,1) both}
  .lcsplit-abas{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px;background:var(--l0);border:1px solid var(--l2);border-radius:14px;margin-bottom:18px}
  .lcsplit-aba{height:38px;border:none;border-radius:10px;background:transparent;color:var(--tdm);font-family:var(--fi);font-size:.82rem;font-weight:600;
    display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;transition:background .2s,color .2s,box-shadow .2s}
  .lcsplit-aba[aria-selected="true"]{background:#fff;color:var(--td);box-shadow:0 1px 3px rgba(17,19,24,.1)}
  .lcsplit-otp{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}
  .lcsplit-otp input{width:100%;height:54px;text-align:center;font-family:var(--fs);font-size:1.35rem;font-weight:600;color:var(--td);
    background:var(--l0);border:1px solid var(--l2);border-radius:14px;outline:none;transition:border-color .2s,box-shadow .2s,background .2s}
  .lcsplit-otp input:focus{border-color:rgba(0,188,51,.6);background:#fff;box-shadow:0 0 0 4px rgba(0,188,51,.12)}
  .lcsplit-linha{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:14px;font-size:.8rem;color:var(--tdm)}
  .lcsplit-sep{display:flex;align-items:center;gap:12px;color:#A6ABB4;font-size:.75rem;margin:20px 0 14px}
  .lcsplit-sep::before,.lcsplit-sep::after{content:"";flex:1;height:1px;background:var(--l2)}
  .lcsplit-erro{font-size:.8rem;line-height:1.5;color:#B42318;background:#FEF3F2;border:1px solid #FECDCA;border-radius:12px;padding:10px 12px}
  @media (max-width: 900px){
    .lcsplit{grid-template-columns:minmax(0,1fr)}
    .lcsplit-esq{margin:12px 12px 0;min-height:auto;padding:28px 24px;border-radius:22px}
    .lcsplit-titulo{font-size:1.75rem}
    .lcsplit-chat,.lcsplit-rodape{display:none}
    .lcsplit-texto{padding-top:120px}
    .lcsplit-esq>.lcsplit-veu{background:linear-gradient(180deg,rgba(2,12,7,.1) 0%,rgba(2,12,7,.35) 28%,rgba(2,12,7,.78) 50%,rgba(2,12,7,.94) 70%,#020c07 100%)}
    .lcsplit-lista{margin-top:18px;gap:10px}
    .lcsplit-lista li{font-size:.86rem}
    .lcsplit-carrossel{margin-top:18px}
    .lcsplit-dir{padding:16px 16px 32px}
    .lcsplit-card{padding:28px 20px}
  }
  @media (max-height: 940px){ .lcsplit-chat{display:none} }
  @media (max-width: 380px){ .lcsplit-otp{gap:5px} .lcsplit-otp input{height:46px;font-size:1.15rem} }
`;

/** O que o LawChat faz (carrossel do painel escuro da entrada). */
const DESTAQUES: CarouselItem[] = [
  { id: "whatsapp", icon: <MessageSquare />, title: "Responde no WhatsApp na hora",
    description: "24 horas, com o jeito e as regras do seu escritório." },
  { id: "qualifica", icon: <CalendarCheck />, title: "Qualifica cada contato",
    description: "E passa para a equipe só quem tem caso, no momento certo." },
  { id: "contrato", icon: <FileSignature />, title: "Coleta os dados e envia o contrato",
    description: "Para assinar, e acompanha até a assinatura." },
  { id: "followup", icon: <Repeat />, title: "Retoma quem parou de responder",
    description: "Follow-up automático no tempo certo, sem a equipe precisar lembrar." },
  { id: "relatorios", icon: <BarChart3 />, title: "Mostra o que dá resultado",
    description: "Leads, contratos e custo da IA por campanha e por agente, em tempo real." },
];

/** Cartões do carrossel como vidro escuro sobre o vídeo, com o verde LawChat nos ícones e nas barras. */
const ESTILO_CARROSSEL = {
  "--carousel-frame": "transparent",
  "--carousel-frame-edge": "transparent",
  "--carousel-frame-highlight": "transparent",
  "--carousel-frame-shadow": "none",
  "--carousel-tile": "linear-gradient(160deg, rgba(255,255,255,.10) 0%, rgba(255,255,255,.04) 100%)",
  "--carousel-tile-edge": "rgba(255,255,255,.12)",
  "--carousel-tile-highlight": "rgba(255,255,255,.14)",
  "--carousel-tile-shadow": "0 10px 30px -18px rgba(0,0,0,.7)",
  "--carousel-ink": "#ffffff",
  "--carousel-muted": "rgba(240,242,245,.72)",
  "--carousel-faint": "rgba(255,255,255,.18)",
  "--carousel-soft": "#34e06b",
  "--carousel-badge": "rgba(0,188,51,.16)",
  width: "100%",
} as CSSProperties;

const CHAVE_DISPOSITIVO = "agentesia_dispositivo";
const ESPERA_REENVIO_S = 60;

/** Id deste navegador para a plataforma (internalDeviceId): um UUID guardado no aparelho. */
function idDoDispositivo(): string | undefined {
  try {
    let id = localStorage.getItem(CHAVE_DISPOSITIVO);
    if (!id) {
      if (typeof crypto === "undefined" || !("randomUUID" in crypto)) return undefined;
      id = crypto.randomUUID();
      localStorage.setItem(CHAVE_DISPOSITIVO, id);
    }
    return id || undefined;
  } catch {
    return undefined;   // sem armazenamento: o servidor deriva um
  }
}

function mensagemDe(falha: unknown, padrao: string): string {
  const f = falha as { status?: number; message?: string };
  return f?.status && f.message ? f.message : padrao;
}

/** Sem sessão: decide entre o erro da plataforma, a tela de entrada e o superadmin. */
export function Entrar() {
  const [senha] = useState(querFormulario());
  const [erroHelena] = useState(() => new URLSearchParams(window.location.search).get("erro"));
  // Página própria do superadmin: formulário direto, só para a equipe LawChat.
  if (window.location.pathname.startsWith("/superadmin")) return <LoginEquipe superadmin />;
  if (erroHelena && !senha) return <ErroDeEntrada codigo={erroHelena} />;
  return <TelaEntrada comSenha={senha} />;
}

type Meio = "email" | "telefone";

function formatarTelefone(bruto: string): string {
  const d = bruto.replace(/\D/g, "").replace(/^55(?=\d{10,11}$)/, "").slice(0, 11);
  if (d.length <= 2) return d;
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
}

/** Celular: o carrossel fica mais alto para caber o texto do cartão. */
function useTelaEstreita(limite = 560) {
  const consulta = `(max-width: ${limite}px)`;
  const [estreito, setEstreito] = useState(() => typeof window !== "undefined" && window.matchMedia?.(consulta).matches);
  useEffect(() => {
    const m = window.matchMedia?.(consulta);
    if (!m) return;
    const mudar = () => setEstreito(m.matches);
    m.addEventListener?.("change", mudar);
    return () => m.removeEventListener?.("change", mudar);
  }, [consulta]);
  return Boolean(estreito);
}

/** Tela principal: layout dividido com o login por código (e o por senha num clique). */
function TelaEntrada({ comSenha }: { comSenha: boolean }) {
  const [modo, setModo] = useState<"codigo" | "senha">(comSenha ? "senha" : "codigo");
  const estreito = useTelaEstreita();
  return (
    <>
      <style>{brandStyle}</style>
      <style>{splitStyle}</style>
      <div className="lcsplit">
        <aside className="lcsplit-esq">
          {/* Fundo em vídeo (mudo, em loop), com um véu escuro por cima para o texto ficar legível. */}
          <video className="lcsplit-video" src={videoFundo} autoPlay muted loop playsInline preload="auto" aria-hidden />
          <div className="lcsplit-veu" aria-hidden />
          {/* Logo que se escreve (contorno das letras e depois o preenchimento). */}
          <div className="lcsplit-marca"><LogoEscrita altura={30} /></div>
          {/* Texto embaixo, sobre o degradê escuro; a linha do rodapé fecha o painel. */}
          <div className="lcsplit-baixo">
            <div className="lcsplit-texto">
              <h1 className="lcsplit-titulo">Atendimento com IA para o <em>seu escritório.</em></h1>
              {/* O que o LawChat faz, em carrossel (React Bits): passa sozinho, para com o mouse em cima. */}
              <div className="lcsplit-carrossel">
                <Carousel items={DESTAQUES} baseWidth="100%" aspectRatio={estreito ? 2.1 : 3.1} frame effect="slide" indicator="bars"
                          autoplay autoplayDelay={4200} pauseOnHover loop radius={18} gap={14} theme="dark" style={ESTILO_CARROSSEL} />
              </div>
              <div className="lcsplit-chat" aria-hidden>
                <div className="lcsplit-bolha lead">Oi, sofri um acidente no trabalho e fiquei com sequela. Tenho direito?</div>
                <div className="lcsplit-bolha ia" style={{ animationDelay: ".25s" }}>Sinto muito pelo acidente. Vou te ajudar a entender: o acidente aconteceu há quanto tempo?</div>
              </div>
            </div>
            <div className="lcsplit-rodape">
              <span><Bot className="size-3.5" /> Agentes de IA</span>
              <span><Sparkles className="size-3.5" /> Modelos de ponta</span>
              <span><ShieldCheck className="size-3.5" /> Dados protegidos</span>
            </div>
          </div>
        </aside>

        <main className="lcsplit-dir">
          <BorderGlow className="lcsplit-brilho" backgroundColor="#ffffff" borderRadius={24} glowColor="140 70 45" glowIntensity={0.7}
                      glowRadius={28} coneSpread={22} edgeSensitivity={26} fillOpacity={0.25} colors={["#00bc33", "#34d399", "#a7f3d0"]}>
          <div className="lcsplit-card">
            <img src={logoMark} alt="LawChat" style={{ height: 34, objectFit: "contain", marginBottom: 20 }} />
            <h2 className="lcauth-title" style={{ fontSize: "1.5rem" }}>Entrar no LawChat</h2>
            {modo === "codigo" ? (
              <>
                <p className="lcauth-sub" style={{ marginBottom: 20 }}>
                  Use o mesmo e-mail ou celular da sua conta de atendimento. Enviamos um código, sem senha.
                </p>
                <FormCodigo />
                <div className="lcsplit-sep">ou</div>
                <button type="button" className="lcauth-link" style={{ width: "100%", textAlign: "center" }}
                        onClick={() => setModo("senha")}>
                  <Lock className="size-3.5" style={{ display: "inline", marginRight: 6, verticalAlign: "-2px" }} />
                  Entrar com senha
                </button>
              </>
            ) : (
              <>
                <p className="lcauth-sub" style={{ marginBottom: 20 }}>Entre com o e-mail e a senha do painel.</p>
                <FormSenha />
                <div className="lcsplit-sep">ou</div>
                <button type="button" className="lcauth-link" style={{ width: "100%", textAlign: "center" }}
                        onClick={() => setModo("codigo")}>
                  <Mail className="size-3.5" style={{ display: "inline", marginRight: 6, verticalAlign: "-2px" }} />
                  Entrar com código (sem senha)
                </button>
              </>
            )}
          </div>
          </BorderGlow>
        </main>
      </div>
    </>
  );
}

/** E-mail ou celular → código de 6 dígitos → entrar. */
function FormCodigo() {
  const { recarregar, trocarVisao } = useSessao();
  const [meio, setMeio] = useState<Meio>("email");
  const [email, setEmail] = useState("");
  const [telefone, setTelefone] = useState("");
  const [etapa, setEtapa] = useState<"pedir" | "codigo">("pedir");
  const [digitos, setDigitos] = useState<string[]>(Array(6).fill(""));
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [espera, setEspera] = useState(0);
  const caixas = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (espera <= 0) return;
    const id = setTimeout(() => setEspera((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [espera]);

  const identificador = () => (meio === "email" ? { email: email.trim() } : { telefone: telefone.replace(/\D/g, "") });
  const valido = meio === "email"
    ? /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) && email.length <= 255
    : /^\d{10,11}$/.test(telefone.replace(/\D/g, ""));

  async function pedir(e?: FormEvent) {
    e?.preventDefault();
    setErro(null);
    if (!valido) { setErro(meio === "email" ? "Digite um e-mail válido." : "Digite o celular com DDD."); return; }
    setOcupado(true);
    try {
      await api("/entrar/codigo", { corpo: identificador() });
      setEtapa("codigo");
      setDigitos(Array(6).fill(""));
      setEspera(ESPERA_REENVIO_S);
      toast.success(meio === "email" ? "Se o e-mail tiver acesso, o código chega em instantes." : "Se o celular tiver acesso, o código chega em instantes.");
      setTimeout(() => caixas.current[0]?.focus(), 50);
    } catch (falha) {
      setErro(mensagemDe(falha, "Não foi possível pedir o código. Tente de novo."));
    } finally {
      setOcupado(false);
    }
  }

  async function confirmar(codigo: string) {
    if (ocupado) return;
    setErro(null);
    setOcupado(true);
    try {
      const r = await api<{ destino?: string }>("/entrar/codigo/confirmar", {
        corpo: { ...identificador(), codigo, dispositivo: idDoDispositivo() },
      });
      trocarVisao("lawchat");
      // A rota /login leva a equipe LawChat para /admin/escritorios; escritório vai para /.
      window.history.replaceState(null, "", r?.destino === "/admin/escritorios" ? "/login" : "/");
      await recarregar();
      toast.success("Bem-vindo!");
    } catch (falha) {
      setErro(mensagemDe(falha, "Não foi possível conectar ao login."));
      setDigitos(Array(6).fill(""));
      setTimeout(() => caixas.current[0]?.focus(), 50);
    } finally {
      setOcupado(false);
    }
  }

  function digitar(i: number, valor: string) {
    const d = valor.replace(/\D/g, "");
    if (d.length > 1) { colar(d, i); return; }
    const novos = [...digitos];
    novos[i] = d;
    setDigitos(novos);
    if (d && i < 5) caixas.current[i + 1]?.focus();
    if (novos.every(Boolean)) void confirmar(novos.join(""));
  }

  function colar(texto: string, inicio = 0) {
    const d = texto.replace(/\D/g, "").slice(0, 6 - inicio);
    if (!d) return;
    const novos = [...digitos];
    d.split("").forEach((c, k) => { novos[inicio + k] = c; });
    setDigitos(novos);
    caixas.current[Math.min(inicio + d.length, 5)]?.focus();
    if (novos.every(Boolean)) void confirmar(novos.join(""));
  }

  function tecla(i: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digitos[i] && i > 0) caixas.current[i - 1]?.focus();
    if (e.key === "ArrowLeft" && i > 0) caixas.current[i - 1]?.focus();
    if (e.key === "ArrowRight" && i < 5) caixas.current[i + 1]?.focus();
  }

  if (etapa === "codigo") {
    const destino = meio === "email" ? email.trim() : formatarTelefone(telefone);
    return (
      <form onSubmit={(e) => { e.preventDefault(); if (digitos.every(Boolean)) void confirmar(digitos.join("")); }}
            noValidate style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <p style={{ fontSize: ".85rem", color: "var(--tdm)", margin: 0, overflowWrap: "anywhere" }}>
          Digite o código de 6 dígitos enviado para <b style={{ color: "var(--td)" }}>{destino}</b>.
        </p>
        <div className="lcsplit-otp" role="group" aria-label="Código de 6 dígitos">
          {digitos.map((d, i) => (
            <input key={i} ref={(el) => { caixas.current[i] = el; }} value={d} inputMode="numeric" maxLength={6}
                   autoComplete={i === 0 ? "one-time-code" : "off"} aria-label={`Dígito ${i + 1}`}
                   onChange={(e) => digitar(i, e.target.value)} onKeyDown={(e) => tecla(i, e)}
                   onPaste={(e: ClipboardEvent<HTMLInputElement>) => { e.preventDefault(); colar(e.clipboardData.getData("text"), i); }}
                   disabled={ocupado} />
          ))}
        </div>
        {erro && <div className="lcsplit-erro" role="alert">{erro}</div>}
        <BotaoBrilho type="submit" disabled={ocupado || !digitos.every(Boolean)} size="lg" radius={50} cheio style={{ marginTop: 6, fontFamily: "var(--fs)" }}>
          {ocupado ? <Loader2 className="size-4 animate-spin" /> : <>Entrar<ArrowRight className="size-4" /></>}
        </BotaoBrilho>
        <div className="lcsplit-linha" style={{ marginTop: 2 }}>
          <button type="button" className="lcauth-link" onClick={() => { setEtapa("pedir"); setErro(null); }}>
            <ArrowLeft className="size-3.5" style={{ display: "inline", marginRight: 4, verticalAlign: "-2px" }} />
            {meio === "email" ? "Usar outro e-mail" : "Usar outro celular"}
          </button>
          {espera > 0
            ? <span>Reenviar código em {espera}s</span>
            : <button type="button" className="lcauth-link" disabled={ocupado} onClick={() => void pedir()}>Reenviar código</button>}
        </div>
      </form>
    );
  }

  return (
    <form onSubmit={pedir} noValidate style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="lcsplit-abas" role="tablist" style={{ marginBottom: 2 }}>
        <button type="button" role="tab" aria-selected={meio === "email"} className="lcsplit-aba"
                onClick={() => { setMeio("email"); setErro(null); }}>
          <Mail className="size-3.5" /> Entrar com e-mail
        </button>
        <button type="button" role="tab" aria-selected={meio === "telefone"} className="lcsplit-aba"
                onClick={() => { setMeio("telefone"); setErro(null); }}>
          <Smartphone className="size-3.5" /> Entrar com telefone
        </button>
      </div>
      {meio === "email" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          <label htmlFor="email-codigo" className="lcauth-label">E-mail</label>
          <div className="lcauth-field">
            <Mail className="size-4 lcauth-ic" />
            <input id="email-codigo" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                   placeholder="seu@escritorio.com.br" className="lcauth-input" autoComplete="email" maxLength={255} autoFocus />
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          <label htmlFor="telefone-codigo" className="lcauth-label">Celular com DDD</label>
          <div className="lcauth-field">
            <Smartphone className="size-4 lcauth-ic" />
            <input id="telefone-codigo" type="tel" value={telefone} onChange={(e) => setTelefone(formatarTelefone(e.target.value))}
                   placeholder="(31) 98693-6492" className="lcauth-input" autoComplete="tel-national" inputMode="tel" autoFocus />
          </div>
        </div>
      )}
      {erro && <div className="lcsplit-erro" role="alert">{erro}</div>}
      <BotaoBrilho type="submit" disabled={ocupado} size="lg" radius={50} cheio style={{ marginTop: 6, fontFamily: "var(--fs)" }}>
        {ocupado ? <Loader2 className="size-4 animate-spin" /> : <>Receber código<ArrowRight className="size-4" /></>}
      </BotaoBrilho>
    </form>
  );
}

/** E-mail e senha (POST /entrar), na tela principal e na do superadmin. */
function FormSenha({ superadmin = false }: { superadmin?: boolean }) {
  const { recarregar, trocarVisao } = useSessao();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [verSenha, setVerSenha] = useState(false);
  const [esqueci, setEsqueci] = useState(false);
  const [ocupado, setOcupado] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) || email.length > 255) { toast.error("E-mail inválido."); return; }
    if (senha.length < 6) { toast.error("A senha tem pelo menos 6 caracteres."); return; }
    setOcupado(true);
    try {
      await api("/entrar", { corpo: { email: email.trim(), senha, superadmin } });
      trocarVisao("lawchat");
      // Fica em /login (ou /superadmin): a rota leva a equipe LawChat para /admin/escritorios (e o escritório para /).
      if (!superadmin && window.location.pathname !== "/login") window.history.replaceState(null, "", "/login");
      await recarregar();
      toast.success("Bem-vindo de volta!");
    } catch (falha) {
      const status = (falha as { status?: number }).status;
      toast.error(status === 401 ? "E-mail ou senha incorretos." : status ? (falha as Error).message : "Não foi possível conectar ao login.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <form onSubmit={enviar} noValidate style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <label htmlFor="email" className="lcauth-label">E-mail</label>
        <div className="lcauth-field">
          <Mail className="size-4 lcauth-ic" />
          <input
            id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder={superadmin ? "voce@lawchat.com.br" : "seu@escritorio.com.br"} className="lcauth-input" required
            autoComplete="username" maxLength={255}
          />
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <label htmlFor="senha" className="lcauth-label">Senha</label>
          <button type="button" onClick={() => setEsqueci((v) => !v)} className="lcauth-link">Esqueci minha senha</button>
        </div>
        <div className="lcauth-field">
          <Lock className="size-4 lcauth-ic" />
          <input
            id="senha" type={verSenha ? "text" : "password"} value={senha}
            onChange={(e) => setSenha(e.target.value)} placeholder="••••••••"
            className="lcauth-input" required maxLength={72} autoComplete="current-password"
          />
          <button
            type="button" onClick={() => setVerSenha((v) => !v)} tabIndex={-1}
            className="lcauth-eye" aria-label={verSenha ? "Ocultar senha" : "Mostrar senha"}
          >
            {verSenha ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </div>

      {esqueci && (
        <div className="lcauth-nota" role="status">
          {superadmin
            ? "Peça uma senha provisória ao dono da LawChat (equipe)."
            : "Entre com o código (sem senha), usando o e-mail da sua conta de atendimento. Ou peça uma senha provisória ao gestor do seu escritório."}
        </div>
      )}

      <BotaoBrilho type="submit" disabled={ocupado} size="lg" radius={50} cheio style={{ marginTop: 6, fontFamily: "var(--fs)" }}>
        {ocupado ? <Loader2 className="size-4 animate-spin" /> : <>{superadmin ? "Entrar como superadmin" : "Entrar"}<ArrowRight className="size-4" /></>}
      </BotaoBrilho>
    </form>
  );
}

/** Página do superadmin (/superadmin): só e-mail e senha, só equipe LawChat. */
function LoginEquipe({ superadmin = false }: { superadmin?: boolean }) {
  return (
    <>
      <style>{brandStyle}</style>
      <div className="lcauth">
        <Background />
        <div className="lcauth-card">
          <div className="lcauth-panel">
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, marginBottom: 26 }}>
              <img src={logoMark} alt="LawChat" style={{ height: 40, objectFit: "contain" }} />
              <span className="lcauth-badge">
                <ShieldCheck className="size-3.5" /> {superadmin ? "Superadmin · área restrita" : "Plataforma LawChat"}
              </span>
            </div>
            <div style={{ textAlign: "center", marginBottom: 24 }}>
              <h1 className="lcauth-title">{superadmin ? "Acesso do superadmin" : "Acesse sua conta"}</h1>
              <p className="lcauth-sub">{superadmin
                ? "Só para a equipe LawChat. Dá acesso a todas as contas, produtos, planos, recargas e erros da plataforma."
                : "Entre na plataforma LawChat para gerenciar os agentes de IA."}</p>
            </div>
            <FormSenha superadmin={superadmin} />
            <div className="lcauth-foot">
              É de um escritório?{" "}
              <span style={{ color: "#009926", fontWeight: 600 }}>Este acesso não é para você: entre pela página inicial, com o código.</span>
            </div>
          </div>
          <div className="lcauth-trust">
            <span><Bot className="size-3.5" /> Agentes de IA</span>
            <span><Sparkles className="size-3.5" /> Modelos de ponta</span>
            <span><ShieldCheck className="size-3.5" /> Dados protegidos</span>
          </div>
        </div>
      </div>
    </>
  );
}

/** Moldura da tela de entrada (pages/EntryGate.tsx). */
function MolduraEntrada({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen grid place-items-center bg-gradient-to-br from-background via-background to-primary/5 p-6">
      <div className="w-full max-w-md text-center space-y-6">{children}</div>
    </div>
  );
}

/** Enquanto a sessão carrega (por exemplo logo depois do botão da LawChat): "Validando seu acesso". */
export function CarregandoEntrada() {
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("Conectando com o LawChat");

  // Progresso simulado — sobe suave até 92% (a tela sai quando a sessão termina de carregar)
  useEffect(() => {
    const messages = [
      { at: 0, text: "Conectando com o LawChat" },
      { at: 25, text: "Verificando sua identidade" },
      { at: 55, text: "Carregando seu workspace" },
      { at: 80, text: "Preparando seus agentes" },
    ];
    const id = setInterval(() => {
      setProgress((p) => {
        const next = p + (p < 60 ? 4 : p < 85 ? 1.5 : 0.4);
        const capped = Math.min(next, 92);
        const msg = [...messages].reverse().find((m) => capped >= m.at);
        if (msg) setStatusMsg(msg.text);
        return capped;
      });
    }, 180);
    return () => clearInterval(id);
  }, []);

  return (
    <MolduraEntrada>
      <div className="relative bg-card/80 backdrop-blur-sm border border-border/60 rounded-3xl shadow-xl shadow-primary/5 px-8 py-10 overflow-hidden">
        {/* Glow decorativo */}
        <div className="absolute -top-16 -right-16 size-40 rounded-full bg-primary/20 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-16 -left-16 size-40 rounded-full bg-primary/10 blur-3xl pointer-events-none" />

        <div className="relative flex flex-col items-center gap-5">
          <div className="relative grid size-24 place-items-center">
            <svg viewBox="0 0 96 96" className="absolute size-24 animate-spin" style={{ animationDuration: "0.95s" }} aria-hidden>
              <circle cx="48" cy="48" r="43" fill="none" stroke="hsl(var(--muted))" strokeWidth="4" />
              <circle cx="48" cy="48" r="43" fill="none" stroke="hsl(var(--primary))" strokeWidth="4" strokeLinecap="round" strokeDasharray="58 214" />
            </svg>
            <div className="relative grid size-[68px] place-items-center rounded-full border border-[#eef1f5] bg-card" style={{ boxShadow: "0 12px 30px -12px rgba(15,23,42,0.28)" }}>
              <img src={logoMark} alt="LawChat" className="size-10 object-contain" draggable={false} />
            </div>
          </div>

          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              Validando seu acesso
            </h1>
            <p className="text-sm text-muted-foreground flex items-center justify-center gap-1.5">
              <Loader2 className="size-3.5 animate-spin" />
              {statusMsg}…
            </p>
          </div>

          {/* Barra de progresso */}
          <div className="w-full space-y-2">
            <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-primary/70 via-primary to-primary/70 rounded-full transition-all duration-300 ease-out shadow-[0_0_10px_hsl(var(--primary)/0.4)]"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground inline-flex items-center gap-1">
                <ShieldCheck className="size-3" /> conexão segura
              </span>
              <span className="font-mono font-semibold text-primary tabular-nums">
                {Math.round(progress)}%
              </span>
            </div>
          </div>
        </div>
      </div>
    </MolduraEntrada>
  );
}

/** A LawChat recusou a entrada (?erro=...): bloqueado, não encontrado ou erro (pages/EntryGate.tsx). */
function ErroDeEntrada({ codigo }: { codigo: string }) {
  const limpou = useRef(false);
  const irParaInicio = () => { window.location.replace("/"); };
  // Tira o código da URL (não fica no histórico); o estado já foi lido.
  useEffect(() => {
    if (limpou.current) return;
    limpou.current = true;
    try { window.history.replaceState(null, "", window.location.pathname); } catch { /* ignora */ }
  }, []);

  if (codigo === "conta_sem_ia") {
    return (
      <MolduraEntrada>
        <BlockedAccountDialog open account={null} onClose={irParaInicio} />
      </MolduraEntrada>
    );
  }

  if (codigo === "usuario_nao_encontrado" || codigo === "link_incompleto") {
    return (
      <MolduraEntrada>
        <div className="space-y-4">
          <AlertTriangle className="size-10 text-destructive mx-auto" />
          <h1 className="text-2xl font-bold">Conta não encontrada</h1>
          <p className="text-muted-foreground text-sm">{ERROS_DA_HELENA[codigo]}</p>
          <Button onClick={irParaInicio}>Ir para o login</Button>
        </div>
      </MolduraEntrada>
    );
  }

  return (
    <MolduraEntrada>
      <div className="space-y-4">
        <AlertTriangle className="size-10 text-destructive mx-auto" />
        <h1 className="text-2xl font-bold">Erro ao validar acesso</h1>
        <p className="text-muted-foreground text-sm break-words">{ERROS_DA_HELENA[codigo] ?? "Não foi possível entrar pela LawChat."}</p>
        <Button onClick={irParaInicio} variant="outline">Ir para o login</Button>
      </div>
    </MolduraEntrada>
  );
}
