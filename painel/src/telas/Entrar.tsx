// Entrada do painel no visual do agents-lawchat-main (pages/Auth.tsx e pages/EntryGate.tsx).
// Comportamento e rotas da API são os nossos:
//  - cliente entra pela Helena (/entrar/helena no servidor, sem senha) → enquanto a sessão carrega,
//    mostra a tela "Validando seu acesso"; se a Helena recusar, o servidor volta com ?erro=...;
//  - sem sessão e sem vir da Helena → "Acesso restrito" (com um link discreto para a equipe);
//  - /login (ou /acesso, ?equipe) → login da equipe LawChat com e-mail e senha (POST /entrar);
//  - /superadmin → página própria do superadmin (só equipe LawChat; o servidor recusa quem é de escritório).
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, Bot, Eye, EyeOff, Loader2, Lock, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api";
import { useSessao } from "../sessao";
import { Button } from "@/components/ui/button";
import { BlockedAccountDialog } from "@/components/auth/BlockedAccountDialog";
import logoMark from "@/assets/lawchat-logo.png";

const ERROS_DA_HELENA: Record<string, string> = {
  link_incompleto: "O link da Helena veio incompleto. Abra a IA de novo pelo botão dentro da Helena.",
  conta_sem_ia: "Esta conta da Helena ainda não tem a IA da LawChat liberada. Fale com o suporte.",
  conta_suspensa: "A IA desta conta está suspensa. Fale com o suporte da LawChat.",
  helena_nao_conectada: "A conta ainda não está conectada à Helena. A equipe LawChat precisa concluir o cadastro.",
  helena_indisponivel: "Não foi possível confirmar seu acesso com a Helena agora. Tente de novo em instantes.",
  usuario_nao_encontrado: "Seu usuário não foi encontrado nesta conta da Helena.",
  usuario_desativado: "Seu acesso foi desativado. Fale com o responsável do escritório.",
  assinatura_ausente: "O acesso precisa vir de dentro da Helena.",
  assinatura_invalida: "O link de acesso não é válido. Abra de novo pela Helena.",
  assinatura_expirada: "O link de acesso expirou. Abra de novo pela Helena.",
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

/** Sem sessão: decide entre o erro da Helena, o "Acesso restrito" e o login da equipe. */
export function Entrar() {
  const [formulario, setFormulario] = useState(querFormulario());
  // Página própria do superadmin: formulário direto, só para a equipe LawChat.
  if (window.location.pathname.startsWith("/superadmin")) return <LoginEquipe superadmin />;
  const [erroHelena] = useState(() => new URLSearchParams(window.location.search).get("erro"));
  if (erroHelena && !formulario) return <ErroDeEntrada codigo={erroHelena} />;
  if (!formulario) {
    return <AcessoRestrito aoAbrirEquipe={() => {
      try { sessionStorage.setItem(CHAVE_FORM, "1"); } catch { /* sem armazenamento: só nesta tela */ }
      window.history.replaceState(null, "", "/login");
      setFormulario(true);
    }} />;
  }
  return <LoginEquipe />;
}

/** Tela pública (pages/Auth.tsx sem ?admin): acesso somente pela Helena. */
function AcessoRestrito({ aoAbrirEquipe }: { aoAbrirEquipe: () => void }) {
  return (
    <>
      <style>{brandStyle}</style>
      <div className="lcauth">
        <Background />
        <div className="lcauth-card" style={{ maxWidth: 420, textAlign: "center" }}>
          <div className="lcauth-panel">
            <img src={logoMark} alt="LawChat" style={{ height: 38, objectFit: "contain", margin: "0 auto 22px", display: "block" }} />
            <div style={{ width: 56, height: 56, margin: "0 auto 18px", borderRadius: 18, display: "grid", placeItems: "center", background: "rgba(0,188,51,.1)", border: "1px solid rgba(0,188,51,.2)" }}>
              <Lock className="size-7" style={{ color: "#009926" }} />
            </div>
            <h1 className="lcauth-title" style={{ fontSize: "1.4rem" }}>Acesso restrito</h1>
            <p className="lcauth-sub">
              O acesso à IA da LawChat é feito automaticamente pelo botão dentro da Helena.
              Abra a Helena e entre por lá, sem senha.
            </p>
            <div className="lcauth-foot">
              Não consegue acessar? Fale com o time comercial.
            </div>
            <div style={{ marginTop: 14 }}>
              <button type="button" onClick={aoAbrirEquipe} className="lcauth-link">Acesso da equipe</button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

/** Login da equipe LawChat (pages/Auth.tsx mode="login"), com o nosso POST /entrar. */
function LoginEquipe({ superadmin = false }: { superadmin?: boolean }) {
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
    <>
      <style>{brandStyle}</style>
      <div className="lcauth">
        <Background />
        <div className="lcauth-card">
          <div className="lcauth-panel">
            {/* Logo + badge */}
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
                  Peça uma senha provisória ao dono da LawChat (equipe) ou ao gestor do seu escritório. Quem é de escritório também pode entrar pela Helena, sem senha.
                </div>
              )}

              <button type="submit" disabled={ocupado} className="lcauth-btn">
                {ocupado ? <Loader2 className="size-4 animate-spin" /> : <>{superadmin ? "Entrar como superadmin" : "Entrar"}<ArrowRight className="size-4" /></>}
              </button>
            </form>

            <div className="lcauth-foot">
              É de um escritório?{" "}
              <span style={{ color: "#009926", fontWeight: 600 }}>{superadmin ? "Este acesso não é para você: entre pela sua conta." : "Entre pelo botão dentro da Helena."}</span>
            </div>
          </div>

          {/* Selos de confiança */}
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

/** Enquanto a sessão carrega (por exemplo logo depois do botão da Helena): "Validando seu acesso". */
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

/** A Helena recusou a entrada (?erro=...): bloqueado, não encontrado ou erro (pages/EntryGate.tsx). */
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
        <p className="text-muted-foreground text-sm break-words">{ERROS_DA_HELENA[codigo] ?? "Não foi possível entrar pela Helena."}</p>
        <Button onClick={irParaInicio} variant="outline">Ir para o login</Button>
      </div>
    </MolduraEntrada>
  );
}
