// Painel Inicial de quem ainda não tem IA no ar: faixa escura "Vamos colocar a sua IA para atender", lista dos
// 7 primeiros passos (marcam-se sozinhos: GET /api/inicio/primeiros-passos, os mesmos dados do PrimeirosPassos),
// linha do tempo "Do contrato à IA atendendo" e ajuda. Botões dos passos e "Tour do painel" usam o menu guiado.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, Clock, LifeBuoy, PlayCircle } from "lucide-react";
import { Modal, useCarregar } from "@/componentes/ui";
import { iniciarGuia, type PassoGuia } from "@/componentes/GuiaRealce";
import { useSessao } from "@/sessao";
import type { PassoInicial, PrimeirosPassosDados } from "./PrimeirosPassos";
import "./inicioNovo.css";

/** Texto de cada passo na tela (o servidor diz só se está pronto e para onde ir). */
const PASSOS: Record<string, { titulo: string; porque: string; fazer: string; min: number; acao?: string; opcional?: boolean }> = {
  conta: { titulo: "Conta liberada para a IA", porque: "É o que libera os agentes de IA na sua conta.", fazer: "A equipe LawChat libera quando o contrato é assinado. Este passo se marca sozinho.", min: 0 },
  whatsapp: { titulo: "Conectar o número de WhatsApp", porque: "O agente conversa com os leads pelo seu número.", fazer: "Leia o QR code com o celular do escritório. Leva 1 minuto.", min: 1, acao: "Conectar número" },
  produto: { titulo: "Ativar o primeiro agente", porque: "O agente responde os leads por você, a qualquer hora.", fazer: "Escolha um produto na Biblioteca e siga os passos da ativação.", min: 10, acao: "Escolher produto" },
  zapsign: { titulo: "Conectar a ZapSign", porque: "A IA manda o contrato para o cliente assinar pelo celular.", fazer: "Conecte a sua conta da ZapSign e escolha o modelo de contrato.", min: 3, acao: "Conectar ZapSign", opcional: true },
  followup: { titulo: "Ligar o follow-up", porque: "Chama de novo quem parou de responder, na hora certa.", fazer: "Abra o follow-up do agente, ligue e confira as mensagens.", min: 2, acao: "Abrir follow-up" },
  conversa: { titulo: "Fazer uma conversa de teste", porque: "É a prova de que tudo funciona de ponta a ponta.", fazer: "De outro celular, mande “oi” para o número do agente e veja a conversa chegar no Atendimento.", min: 2, acao: "Ver Atendimento" },
  saldo: { titulo: "Fazer a primeira recarga", porque: "Sem saldo, a IA para de responder os leads.", fazer: "Recarregue com Pix. O valor não expira.", min: 1, acao: "Recarregar" },
};
/** Nome do fluxo no balão do menu guiado ("ATIVAR AGENTE · 1 DE 2"). */
const FLUXO: Record<string, string> = { whatsapp: "Conectar número", produto: "Ativar agente", zapsign: "Contrato", followup: "Follow-up", conversa: "Teste", saldo: "Recarga" };
const ORDEM = ["conta", "whatsapp", "produto", "zapsign", "followup", "conversa", "saldo"];
const pronto = (p: PassoInicial) => p.situacao !== "pendente";

/** Passos do menu guiado para resolver um passo (navega e realça o lugar certo, quando dá para apontar). */
function guiaDoPasso(p: PassoInicial, destino: string): PassoGuia[] | null {
  const rota = destino.split("?")[0];
  if (p.codigo === "produto" && rota === "/biblioteca") {
    return [
      { rota: "/biblioteca", ir: destino, seletores: ['a[href^="/biblioteca/"]'], titulo: "Escolha um produto",
        texto: "Cada produto já vem com o funil de agentes pronto. Abra o que o escritório mais atende.", acao: "Abrir este", clicar: true },
      { rota: "/biblioteca/", seletores: ['[aria-label="Ativar produto"]'], titulo: "Ative o agente",
        texto: "Clique em “Ativar produto” e siga os passos. Dá para testar antes de ligar para os leads.", acao: "Ativar este", clicar: true },
    ];
  }
  if (rota.startsWith("/agentes/") && rota.includes("/ativacao")) {
    return [{ rota, ir: destino, seletores: [".ativ-assistente .stepper", ".ativ-assistente", ".page .btn.pri"], titulo: "Siga estes passos", texto: "Vá até o fim da ativação para ligar o agente." }];
  }
  if (rota === "/meus-produtos") {
    return [{ rota, ir: destino, seletores: ['a[href^="/agentes/"]', 'a[href^="/meus-produtos/"]'], titulo: "Abra o agente aqui", texto: "O agente já existe. Abra e ligue." }];
  }
  if (/\/followup/.test(rota)) {
    return [{ rota, ir: destino, seletores: [".page .sw-t", '.page [role="switch"]'], titulo: "Ligue o follow-up aqui", texto: "A cadência padrão já vem escrita. Confira as mensagens e ligue." }];
  }
  if (rota === "/consumo") {
    return [{ rota, ir: destino, seletores: [".cr-botao-verde"], titulo: "Recarregue aqui", texto: "Pix cai em segundos. O valor da recarga não expira." }];
  }
  return null;
}

/** Tour do painel (1 min): o menu lateral e a lista de passos. Itens que não estão na tela são pulados. */
function tourDoPainel(podeGerir: boolean): PassoGuia[] {
  const item = (para: string) => [`a.lc-item[href="${para}"]`, `a.lc-mt-item[href="${para}"]`];
  const passos: PassoGuia[] = [
    { seletores: item("/"), titulo: "Painel Inicial", texto: "Aqui você vê o dia: conversas, leads qualificados, contratos e saldo." },
    { seletores: item("/atendimento"), titulo: "Atendimento", texto: "As conversas com os leads chegam aqui. Dá para assumir uma conversa quando quiser." },
    { seletores: item("/crm/paineis"), titulo: "CRM", texto: "Os leads andam pelas etapas sozinhos, do primeiro contato ao contrato assinado." },
    { seletores: item("/meus-produtos"), titulo: "Apps", texto: "Seus agentes de IA e a Biblioteca de produtos para ativar um novo." },
  ];
  if (podeGerir) passos.push({ seletores: item("/relatorios/dashboard"), titulo: "Relatórios", texto: "Leads, contratos, custo da IA e os horários em que os leads chegam." });
  passos.push({ seletores: ["#lc-ob-passos"], titulo: "Seus primeiros passos", texto: "Siga um por vez. Cada passo se marca sozinho quando fica pronto.", acao: "Começar" });
  return passos;
}

export function OnboardingInicial({ dados }: { dados: PrimeirosPassosDados }) {
  const navegar = useNavigate();
  const { escritorio, podeGerir } = useSessao();
  const [ajuda, setAjuda] = useState(false);
  const porCodigo = Object.fromEntries(dados.passos.map((p) => [p.codigo, p]));
  const passos = ORDEM.map((c) => porCodigo[c]).filter(Boolean) as PassoInicial[];
  const total = passos.length;
  const feitos = passos.filter(pronto).length;
  const faltam = total - feitos;
  const proximo = passos.find((p) => p.codigo === dados.proximo) ?? passos.find((p) => !pronto(p)) ?? null;
  const minutos = passos.filter((p) => !pronto(p)).reduce((s, p) => s + (PASSOS[p.codigo]?.min ?? 0), 0);

  // Agente criado mas desligado: o botão leva direto à ativação dele (como no PrimeirosPassos).
  const passoProduto = porCodigo.produto as PassoInicial | undefined;
  const precisaAgente = passoProduto?.situacao === "pendente" && passoProduto.para === "/meus-produtos";
  const agentes = useCarregar<{ id: string; nome: string; situacao?: string }[]>(precisaAgente && escritorio ? "/agentes" : null, [escritorio, precisaAgente]);
  const destinoDe = (p: PassoInicial): string | null => {
    if (p.codigo === "produto" && precisaAgente) {
      const nome = p.detalhe.replace(/ criado, mas ainda desligado$/, "");
      const ag = (agentes.dados ?? []).find((a) => a.nome === nome) ?? (agentes.dados ?? []).find((a) => a.situacao !== "ativo");
      if (ag) return `/agentes/${ag.id}/ativacao`;
    }
    if (p.codigo === "conversa") return "/atendimento";
    return p.para;
  };
  const resolver = (p: PassoInicial) => {
    const destino = destinoDe(p);
    if (!destino) return;
    navegar(destino);                                  // sem tour guiado (pedido do dono): vai direto à tela
  };

  const C = 2 * Math.PI * 54;
  const linhaDoTempo = [
    { t: "Contratou", d: "A equipe libera a conta", feito: true },
    { t: "Recebeu o login", d: "Você está aqui", feito: true, aqui: true },
    { t: "Ativou o agente", d: "Número, escritório e contrato", feito: passoProduto?.situacao === "feito" },
    { t: "IA atendendo", d: "Leads 24 horas por dia", feito: false },
  ];

  return (
    <div className="lc-ob">
      <section className="lc-ob-hero" aria-label="Boas-vindas">
        <div className="lc-hero__brilho" aria-hidden />
        <div className="lc-ob-hero__texto">
          <span className="lc-hero__data">Boas-vindas à LawChat</span>
          <h1 className="lc-hero__titulo">
            {proximo ? <>Vamos colocar a sua IA para atender. Faltam <span className="lc-hero__hl">{faltam} {faltam === 1 ? "passo" : "passos"}</span>.</> : "Tudo pronto. Falta só ligar um agente."}
          </h1>
          <p className="lc-ob-hero__sub">
            {proximo ? `Dá para fazer tudo por aqui, em uns ${Math.max(1, minutos)} minutos. Cada passo explica o porquê e leva você ao lugar certo.` : "Abra Meus agentes e ligue o agente para a IA começar a atender."}
          </p>
          <div className="lc-ob-hero__botoes">
            {proximo && (
              <button type="button" className="lc-ob-btn lc-ob-btn--verde" onClick={() => resolver(proximo)} disabled={!destinoDe(proximo)}>
                Próximo passo: {PASSOS[proximo.codigo]?.titulo ?? proximo.titulo} <ArrowRight aria-hidden />
              </button>
            )}
          </div>
        </div>
        <div className="lc-ob-anel" role="img" aria-label={`${feitos} de ${total} passos prontos`}>
          <svg viewBox="0 0 120 120" aria-hidden>
            <circle className="fundo" cx="60" cy="60" r="54" />
            <circle className="frente" cx="60" cy="60" r="54" strokeDasharray={C}
              style={{ strokeDashoffset: C * (1 - feitos / Math.max(1, total)), ["--c" as string]: C }} />
          </svg>
          <b>{feitos}/{total}<small>prontos</small></b>
        </div>
      </section>

      <div className="lc-ob-grade">
        <section id="lc-ob-passos" className="lc-ob-cartao" aria-label="Primeiros passos">
          <header className="lc-ob-cartao__cab">
            <div>
              <h3>Primeiros passos</h3>
              <p>Um por vez. Cada um se marca sozinho quando fica pronto.</p>
            </div>
            <span className="lc-ob-tag">{feitos} de {total}</span>
          </header>
          <ol className="lc-ob-lista">
            {passos.map((p, i) => {
              const info = PASSOS[p.codigo] ?? { titulo: p.titulo, porque: "", fazer: p.detalhe, min: 0 };
              const feito = pronto(p);
              const atual = proximo?.codigo === p.codigo;
              const destino = destinoDe(p);
              const comEquipe = p.codigo === "conta";
              const fazer = p.codigo === "produto" && precisaAgente
                ? `O agente ${p.detalhe.replace(/ criado, mas ainda desligado$/, "")} já existe, mas está desligado. Abra a ativação e siga até ligar.`
                : p.codigo === "followup" && !feito && p.detalhe.startsWith("ligue um produto")
                  ? "Primeiro, ligue um agente (passo 3). Depois, volte aqui para ligar o follow-up."
                  : info.fazer;
              return (
                <li key={p.codigo} className={`lc-ob-passo${feito ? " is-feito" : ""}${atual ? " is-atual" : ""}`} style={{ ["--n" as string]: i }}>
                  <span className="lc-ob-passo__n" aria-hidden>{feito ? <Check /> : i + 1}</span>
                  <div className="lc-ob-passo__corpo">
                    <b>{info.titulo}{info.opcional && <span className="lc-ob-opcional">opcional</span>}</b>
                    <p className="lc-ob-passo__porque">
                      {feito ? (p.situacao === "nao_se_aplica" ? `Não é preciso na sua conta: ${p.detalhe}.` : `Tudo certo: ${p.detalhe}.`) : info.porque}
                    </p>
                    {atual && <p className="lc-ob-passo__fazer"><b>O que fazer:</b> {fazer}</p>}
                    {!feito && info.min > 0 && <span className="lc-ob-tempo"><Clock aria-hidden /> {info.min} min</span>}
                  </div>
                  <div className="lc-ob-passo__acao">
                    {feito ? <span className="lc-ob-selo is-ok">{p.situacao === "nao_se_aplica" ? "Não se aplica" : "Pronto"}</span>
                      : comEquipe ? <span className="lc-ob-selo">Com a equipe</span>
                        : destino ? (
                          <button type="button" className={`lc-ob-btn lc-ob-btn--pequeno${atual ? " lc-ob-btn--verde" : ""}`} onClick={() => resolver(p)}>
                            {p.codigo === "produto" && precisaAgente ? "Abrir a ativação" : info.acao ?? p.acao} {atual && <ArrowRight aria-hidden />}
                          </button>
                        ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>

        <div className="lc-ob-lateral">
          <section className="lc-ob-cartao" aria-label="Do contrato à IA atendendo">
            <header className="lc-ob-cartao__cab">
              <div><h3>Do contrato à IA atendendo</h3><p>O caminho de quem acabou de entrar</p></div>
            </header>
            <ol className="lc-ob-tempo-linha">
              {linhaDoTempo.map((x) => (
                <li key={x.t} className={x.feito ? "is-feito" : undefined}>
                  <span className="ponto" aria-hidden />
                  <div><b>{x.t}</b><p className={x.aqui ? "is-aqui" : undefined}>{x.d}</p></div>
                </li>
              ))}
            </ol>
          </section>
          <section className="lc-ob-cartao lc-ob-ajuda" aria-label="Ajuda">
            <b>Travou em algum passo?</b>
            <p>A equipe LawChat acompanha a sua ativação e responde em horário comercial.</p>
            <button type="button" className="lc-ob-btn lc-ob-btn--borda" onClick={() => setAjuda(true)}><LifeBuoy aria-hidden /> Falar com o suporte</button>
          </section>
        </div>
      </div>

      <section className="lc-ob-cartao lc-ob-fantasma" aria-label="O seu dia vai aparecer aqui">
        <div><h3>O seu dia vai aparecer aqui</h3><p>Depois que um agente estiver no ar, estes números se enchem sozinhos.</p></div>
        <dl>{["Conversas hoje", "Leads qualificados", "Contratos no mês", "Resposta média"].map((l) => <div key={l}><dt>{l}</dt><dd>—</dd></div>)}</dl>
      </section>

      {ajuda && (
        <Modal titulo="Falar com o suporte" aoFechar={() => setAjuda(false)}
          rodape={<><span className="sp" /><button type="button" className="btn pri" onClick={() => setAjuda(false)}>Entendi</button></>}>
          <div className="form">
            <p className="sec" style={{ margin: 0 }}>Fale com a equipe LawChat pelo mesmo WhatsApp de sempre, em horário comercial. Diga em qual passo travou: a equipe vê a sua conta e ajuda a terminar.</p>
            <p className="sec" style={{ margin: 0 }}>Para colocar um agente no ar: <b>Apps</b> → <b>Biblioteca</b> → escolha o produto → <b>Ativar</b>. As conversas ficam no <b>Atendimento</b>.</p>
            <p className="sec" style={{ margin: 0 }}><b>Ctrl K</b> abre a busca de telas. <b>Ctrl B</b> recolhe o menu lateral.</p>
          </div>
        </Modal>
      )}
    </div>
  );
}
