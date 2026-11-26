import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, BookOpen, Building2, Check, CheckCircle2, CircleDashed, FileText, MessageCircleQuestion, Plus,
  RefreshCw, RotateCcw, ShieldQuestion, Sparkles, Wand2, X, XCircle,
} from "lucide-react";
import { api, enviar, formatarTelefone, type Agente, type Canal, type Definicao } from "../api";
import { Alerta, Cabecalho, Carregando, Interruptor, Painel, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { EditorDefinicao } from "./EditorDefinicao";

const PASSOS = ["Modelo", "Identidade", "Comportamento", "Conteúdo", "Integrações", "Revisão"];
const ESPERAS = [5, 10, 15, 20, 30, 45];
const PAUSAS: [string, number | null][] = [["15 min", 15], ["30 min", 30], ["1 hora", 60], ["2 horas", 120], ["Só a equipe religa", null]];
const NOMES_SUGERIDOS = ["Júlia", "Sofia", "Laura", "LawChat", "Ana", "Clara"];

interface EtapaPrevia { codigo: string; nome: string; tipo: string; instrucao_padrao: string }
interface Faq { pergunta: string; resposta: string }
interface Objecao { objecao: string; resposta: string }
interface Integ { situacao: string; config?: Record<string, any> }

/** Assistente de criação, no molde do app de referência: Modelo → Identidade → Comportamento → Conteúdo → Integrações → Revisão. */
export function TelaAgenteNovo() {
  const { catalogo, escritorio } = useSessao();
  const navegar = useNavigate();
  const { ocupado, executar } = useAcao();
  const integracoes = useCarregar<{ integracoes: Record<string, Integ>; canais: Canal[] }>("/integracoes", [escritorio]);
  const biblioteca = useCarregar<{ id: string; nome: string; descricao: string; produto: string }[]>("/modelos");
  const [passo, setPasso] = useState(0);
  // Modelo
  const [produto, setProduto] = useState("auxilio_acidente");
  const [idModelo, setIdModelo] = useState<string | null>(null);
  // Identidade
  const [nome, setNome] = useState("");
  const [idCanal, setIdCanal] = useState("");
  // Comportamento
  const [espera, setEspera] = useState(10);
  const [pausa, setPausa] = useState<number | null>(30);
  const [modelo, setModelo] = useState("gpt-4.1");
  // Conteúdo
  const [definicao, setDefinicao] = useState<Definicao | null>(null);
  const [erroDefinicao, setErroDefinicao] = useState<string | null>(null);
  const [instrucoes, setInstrucoes] = useState<Record<string, string>>({});
  const [faq, setFaq] = useState<Faq[]>([]);
  const [objecoes, setObjecoes] = useState<Objecao[]>([]);
  const [dadosEscritorio, setDadosEscritorio] = useState("");
  const [honorarios, setHonorarios] = useState("");
  // Integrações
  const [funcoes, setFuncoes] = useState<Record<string, boolean>>({ crm: true, transferir_humano: true, avisos: true, buscar_cep: true });
  // Revisão
  const [numerosTeste, setNumerosTeste] = useState("");
  const [ativarJa, setAtivarJa] = useState(true);

  const proprioDoZero = produto === "proprio" && !idModelo;
  const etapasPrevia = useCarregar<EtapaPrevia[]>(produto !== "proprio" ? `/produtos/${produto}/etapas?contrato=${Boolean(funcoes.contrato_zapsign)}` : null,
    [produto, funcoes.contrato_zapsign]);

  useEffect(() => {
    if (produto === "proprio" && !definicao) api<Definicao>("/modelo-inicial-proprio").then(setDefinicao).catch(() => undefined);
  }, [produto, definicao]);

  const dados = integracoes.dados;
  const canais = useMemo(() => (dados?.canais ?? []).filter((c) => c.ativo && /whats|oficial|nao_oficial/i.test(c.tipo || "whats")), [dados]);
  useEffect(() => {
    if (!idCanal && canais.length) setIdCanal(canais.find((c) => !c.id_agente)?.id ?? "");
  }, [canais, idCanal]);

  if (!dados) return <Carregando erro={integracoes.erro} />;
  const integ = dados.integracoes;
  const helenaOk = integ.helena?.situacao === "ok";
  const zapsignPronta = integ.zapsign?.situacao === "ok" && (integ.zapsign?.config?.modelos ?? []).length > 0;
  const crmPronto = Boolean(integ.crm?.config?.id_painel);
  const atual = PASSOS[passo];
  const etapas: { codigo: string; nome: string; instrucao_padrao: string }[] = proprioDoZero || produto === "proprio"
    ? (definicao?.etapas ?? []).map((e) => ({ codigo: e.codigo, nome: e.nome, instrucao_padrao: e.instrucao ?? "" }))
    : etapasPrevia.dados ?? [];
  const numerosLista = numerosTeste.split(/[\n,;]/).map((n) => n.trim()).filter(Boolean);

  const sincronizar = () => executar(async () => { await api("/integracoes/helena/canais", { metodo: "POST" }); await integracoes.recarregar(); },
    "Números sincronizados com a LawChat.");

  const checklist: { item: string; ok: boolean; obrigatorio: boolean; detalhe: string }[] = [
    { item: "Identidade", ok: nome.trim().length >= 2 && Boolean(idCanal), obrigatorio: true, detalhe: nome && idCanal ? `${nome} no ${formatarTelefone(canais.find((c) => c.id === idCanal)?.numero_normalizado)}` : "nome e número" },
    { item: "LawChat conectada", ok: helenaOk, obrigatorio: true, detalhe: helenaOk ? "token aceito" : "conecte em Integrações" },
    { item: "Contrato na ZapSign", ok: !funcoes.contrato_zapsign || zapsignPronta, obrigatorio: Boolean(funcoes.contrato_zapsign), detalhe: !funcoes.contrato_zapsign ? "função desligada" : zapsignPronta ? "token e modelo prontos" : "falta token ou modelo em Integrações" },
    { item: "CRM", ok: !funcoes.crm || crmPronto, obrigatorio: false, detalhe: !funcoes.crm ? "função desligada" : crmPronto ? "painel escolhido" : "escolha o painel em Integrações (dá para fazer depois)" },
    { item: "Números de teste", ok: numerosLista.length > 0, obrigatorio: ativarJa, detalhe: numerosLista.length ? `${numerosLista.length} número(s)` : "para ativar em teste agora" },
    { item: "Perguntas frequentes e objeções", ok: faq.length + objecoes.length > 0, obrigatorio: false, detalhe: "opcional" },
  ];
  const pendencias = checklist.filter((c) => c.obrigatorio && !c.ok);

  const podeAvancar = atual === "Modelo" ? Boolean(produto)
    : atual === "Identidade" ? nome.trim().length >= 2 && Boolean(idCanal)
    : atual === "Conteúdo" ? !(proprioDoZero && (!definicao || erroDefinicao)) : true;
  const motivoParado = atual === "Identidade" && nome.trim().length < 2 ? "Informe o nome do agente para continuar"
    : atual === "Identidade" && !idCanal ? "Selecione um número de WhatsApp" : null;

  const criar = () => executar(async () => {
    const agente = await enviar<Agente>("/agentes", {
      nome: nome.trim(), id_canal: idCanal, produto, modelo, id_modelo: idModelo,
      definicao: proprioDoZero ? definicao : undefined,
      espera_s: espera, minutos_pausa_humano: pausa ?? 30, pausa_sem_volta: pausa === null,
      conhecimento: { faq, objecoes, dados_escritorio: dadosEscritorio }, instrucoes, funcoes,
      honorarios: honorarios || undefined, numeros_teste: numerosLista,
    });
    if (ativarJa) {
      try {
        await enviar(`/agentes/${agente.id}/ativacao`, { situacao: "ativo", modo: "teste" });
      } catch {
        /* a tela do agente mostra a lista do que falta */
      }
    }
    navegar(`/agentes/${agente.id}?criado=1`);
  }, ativarJa ? "🎉 Agente criado. A ativação em teste foi tentada: confira a lista." : "Agente criado como rascunho (pausado).");

  return (
    <>
      <Link className="btn ghost sm" to="/agentes" style={{ marginBottom: 10 }}><ArrowLeft />Agentes</Link>
      <Cabecalho eyebrow="Novo agente" titulo="Criar agente" texto="Escolha o modelo, dê identidade, ajuste o comportamento e o conteúdo, ligue as integrações e revise antes de ativar." />
      <div className="passos">
        {PASSOS.map((p, i) => (
          <button key={p} className={`passo ${i === passo ? "on" : i < passo ? "feito" : ""}`} disabled={i > passo} onClick={() => i < passo && setPasso(i)}>
            <i>{i < passo ? <Check size={12} /> : i + 1}</i>{p}
          </button>
        ))}
      </div>

      {!helenaOk && <div style={{ marginBottom: 16 }}><Alerta tipo="warn"><b>A LawChat ainda não está conectada.</b> Sem ela não há números. <Link to="/integracoes">Conectar agora</Link></Alerta></div>}

      <div key={atual} className="passo-corpo">
        {atual === "Modelo" && (
          <div className="opcoes">
            {(biblioteca.dados ?? []).map((m) => (
              <button key={m.id} className={`opcao ${idModelo === m.id ? "on" : ""}`} onClick={() => { setIdModelo(m.id); setProduto(m.produto); }}>
                <BookOpen className="i" color="var(--acento)" /><b>{m.nome}</b><span>{m.descricao || "Modelo da biblioteca LawChat."}</span>
                <span className="chip ok" style={{ alignSelf: "flex-start" }}>biblioteca</span>
              </button>
            ))}
            {(catalogo?.produtos ?? []).map((p) => (
              <button key={p.id} className={`opcao ${!idModelo && produto === p.id ? "on" : ""}`} onClick={() => { setIdModelo(null); setProduto(p.id); }}>
                {p.tipo === "pronto" ? <Sparkles className="i" color="var(--acento)" /> : <Wand2 className="i" color="var(--acento)" />}
                <b>{p.nome}</b><span>{p.descricao}</span>
                <span className={`chip ${p.tipo === "pronto" ? "ok" : "ac"}`} style={{ alignSelf: "flex-start" }}>{p.tipo === "pronto" ? "pronto" : "do zero"}</span>
              </button>
            ))}
          </div>
        )}

        {atual === "Identidade" && (
          <div className="stack">
            <Painel titulo="Dê uma identidade ao seu agente">
              <label className="field"><span className="lbl">Nome do agente * <span className="chip">uso interno e apresentação</span></span>
                <input value={nome} onChange={(e) => setNome(e.target.value)} maxLength={60} placeholder="Ex.: Júlia" autoFocus /></label>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                {NOMES_SUGERIDOS.map((n) => <button key={n} className={`btn sm ${nome === n ? "pri" : ""}`} onClick={() => setNome(n)}>{n}</button>)}
              </div>
            </Painel>
            <Painel titulo={<h3 style={{ display: "flex", gap: 8, alignItems: "center" }}>Canal: WhatsApp <span className="chip warn">obrigatório</span></h3>} sem_corpo
              acoes={<button className="btn sm" onClick={sincronizar} disabled={ocupado || !helenaOk}><RefreshCw className={ocupado ? "girando" : ""} />Sincronizar</button>}>
              {canais.length === 0 ? <Vazio>Nenhum número na LawChat. Use "Sincronizar".</Vazio> : (
                <div className="rows">{canais.map((c) => {
                  const emUso = Boolean(c.id_agente);
                  return (
                    <label key={c.id} style={{ cursor: emUso ? "not-allowed" : "pointer", opacity: emUso ? .55 : 1 }}>
                      <input type="radio" name="canal" disabled={emUso} checked={idCanal === c.id} onChange={() => setIdCanal(c.id)} style={{ accentColor: "var(--acento)" }} />
                      <div style={{ flex: 1 }}><b className="mono">{formatarTelefone(c.numero_normalizado)}</b>
                        <div className="muted" style={{ fontSize: 12 }}>{c.tipo === "oficial" ? "API oficial" : "não oficial"} · canal {c.id_canal_helena}</div></div>
                      {emUso ? <span className="chip warn">Em uso por {c.nome_agente}</span> : <span className="chip ok">Disponível</span>}
                    </label>
                  );
                })}</div>
              )}
            </Painel>
          </div>
        )}

        {atual === "Comportamento" && (
          <Painel titulo="Comportamento do agente">
            <div className="form">
              <div className="field"><span className="lbl">Tempo de resposta</span>
                <div className="seg" style={{ maxWidth: 460 }}>
                  {ESPERAS.map((s) => <button key={s} className={espera === s ? "on" : ""} onClick={() => setEspera(s)}>{s}s</button>)}
                </div>
                <span className="ajuda">Espera antes de responder: junta as mensagens seguidas do lead numa resposta só e parece mais humano.</span></div>
              <div className="field"><span className="lbl">Pausa quando alguém da equipe responde</span>
                <div className="seg" style={{ maxWidth: 560 }}>
                  {PAUSAS.map(([rotulo, valor]) => <button key={rotulo} className={pausa === valor ? "on" : ""} onClick={() => setPausa(valor)}>{rotulo}</button>)}
                </div>
                <span className="ajuda">A IA fica calada nesse tempo. Cada nova fala do atendente reinicia a contagem.</span></div>
              <label className="field" style={{ maxWidth: 360 }}><span className="lbl">Modelo de IA (avançado)</span>
                <select value={modelo} onChange={(e) => setModelo(e.target.value)}>
                  {(catalogo?.modelos ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}{m.padrao ? " (padrão)" : ""}</option>)}
                </select></label>
            </div>
          </Painel>
        )}

        {atual === "Conteúdo" && (
          <Conteudo etapas={etapas} instrucoes={instrucoes} setInstrucoes={setInstrucoes} faq={faq} setFaq={setFaq}
            objecoes={objecoes} setObjecoes={setObjecoes} dadosEscritorio={dadosEscritorio} setDadosEscritorio={setDadosEscritorio}
            honorarios={honorarios} setHonorarios={setHonorarios} temHonorarios={produto === "auxilio_acidente"}
            editorDefinicao={proprioDoZero && definicao ? <EditorDefinicao valor={definicao} aoMudar={setDefinicao} aoErro={setErroDefinicao} /> : null} />
        )}

        {atual === "Integrações" && (
          <Painel titulo="Integrações e funções" sem_corpo>
            <div className="rows">{(catalogo?.funcoes ?? []).map((f) => {
              const falta = f.id === "contrato_zapsign" && !zapsignPronta ? "Configure a ZapSign em Integrações (token e modelo)."
                : f.id === "crm" && !crmPronto ? "Escolha o painel do CRM em Integrações para mover cards." : null;
              return (
                <div key={f.id} style={{ alignItems: "flex-start" }}>
                  <Interruptor rotulo={f.nome} ligado={Boolean(funcoes[f.id])} desligado={!f.pronta} aoMudar={(v) => setFuncoes({ ...funcoes, [f.id]: v })} />
                  <div style={{ flex: 1 }}><b>{f.nome}</b> {!f.pronta && <span className="chip">em breve</span>}
                    <div className="sec" style={{ fontSize: 13 }}>{f.descricao}</div>
                    {funcoes[f.id] && falta && <div style={{ marginTop: 6 }}><Alerta tipo="warn">{falta} <Link to="/integracoes">Abrir Integrações</Link></Alerta></div>}
                  </div>
                </div>
              );
            })}</div>
          </Painel>
        )}

        {atual === "Revisão" && (
          <div className="two">
            <Painel titulo="Checklist de ativação" sem_corpo>
              <div className="passos-ativacao" style={{ margin: "0 16px 16px" }}>
                {checklist.map((c) => (
                  <div key={c.item} className={`passo-at ${c.ok ? "ok" : c.obrigatorio ? "erro" : "pulado"}`}>
                    {c.ok ? <CheckCircle2 size={16} color="var(--ok)" /> : c.obrigatorio ? <XCircle size={16} color="var(--bad)" /> : <CircleDashed size={16} color="var(--ink-3)" />}
                    <div><b>{c.item}{c.obrigatorio ? "" : " (opcional)"}</b><span>{c.detalhe}</span></div>
                  </div>
                ))}
              </div>
            </Painel>
            <Painel titulo="Ativação">
              <div className="form">
                <label className="field"><span className="lbl">Números de teste</span>
                  <textarea rows={3} value={numerosTeste} onChange={(e) => setNumerosTeste(e.target.value)} placeholder={"Um por linha, com DDD.\n(11) 98888-7777"} />
                  <span className="ajuda">Em teste, a IA responde só a estes números. Os outros leads ficam registrados, sem resposta.</span></label>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <Interruptor rotulo="Ativar imediatamente" ligado={ativarJa} aoMudar={setAtivarJa} />
                  <div><b>Ativar imediatamente (em teste)</b><div className="sec" style={{ fontSize: 13 }}>Desligado, o agente fica como rascunho, pausado.</div></div>
                </div>
                {pendencias.length > 0 && ativarJa && <Alerta tipo="warn">Não dá para ativar ainda: {pendencias.map((p) => p.item.toLowerCase()).join(", ")}.</Alerta>}
                <Alerta tipo="info">Ao ativar, o sistema sincroniza o número, cria o webhook na LawChat e confere CRM e chave de IA. Para todos (produção) é na tela do agente, depois de testar.</Alerta>
              </div>
            </Painel>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 18, alignItems: "center" }}>
        {passo > 0 && <button className="btn" onClick={() => setPasso(passo - 1)}><ArrowLeft />Voltar</button>}
        <div style={{ flex: 1 }} />
        {motivoParado && <span className="muted" style={{ fontSize: 12.5 }}>{motivoParado}</span>}
        {passo < PASSOS.length - 1
          ? <button className="btn pri" disabled={!podeAvancar} onClick={() => setPasso(passo + 1)}>Continuar<ArrowRight /></button>
          : <button className="btn pri" disabled={ocupado || !idCanal || nome.trim().length < 2 || (ativarJa && pendencias.length > 0)} onClick={criar}>
              <Check />{ativarJa ? (pendencias.length ? `${pendencias.length} pendência(s)` : "Criar e ativar em teste") : "Criar como rascunho"}</button>}
      </div>
    </>
  );
}

function Conteudo(p: {
  etapas: { codigo: string; nome: string; instrucao_padrao: string }[]; instrucoes: Record<string, string>; setInstrucoes: (v: Record<string, string>) => void;
  faq: Faq[]; setFaq: (v: Faq[]) => void; objecoes: Objecao[]; setObjecoes: (v: Objecao[]) => void;
  dadosEscritorio: string; setDadosEscritorio: (v: string) => void; honorarios: string; setHonorarios: (v: string) => void; temHonorarios: boolean;
  editorDefinicao: JSX.Element | null;
}) {
  const [aba, setAba] = useState<string>(p.editorDefinicao ? "_definicao" : "_rapida");
  const etapaAtual = p.etapas.find((e) => e.codigo === aba);
  // Edição rápida: campos {{assim}} que aparecem nas instruções viram um formulário só.
  const campos = useMemo(() => {
    const achados = new Set<string>();
    for (const e of p.etapas) for (const m of (p.instrucoes[e.codigo] ?? e.instrucao_padrao).matchAll(/\{\{\s*([^}]+?)\s*\}\}/g)) achados.add(m[1]);
    return [...achados];
  }, [p.etapas, p.instrucoes]);
  const [valoresRapidos, setValoresRapidos] = useState<Record<string, string>>({});
  const aplicarCampo = (campo: string) => {
    const valor = valoresRapidos[campo];
    if (!valor) return;
    const novas = { ...p.instrucoes };
    for (const e of p.etapas) {
      const texto = novas[e.codigo] ?? e.instrucao_padrao;
      if (texto.includes("{{")) novas[e.codigo] = texto.replace(new RegExp(`\\{\\{\\s*${campo.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\}\\}`, "g"), valor);
    }
    p.setInstrucoes(novas);
  };

  const itens: [string, string, JSX.Element][] = [
    ...(p.editorDefinicao ? [["_definicao", "Etapas e regras", <Wand2 size={15} key="d" />] as [string, string, JSX.Element]] : []),
    ["_rapida", "Edição rápida", <Sparkles size={15} key="r" />],
    ...p.etapas.map((e) => [e.codigo, e.nome, <FileText size={15} key={e.codigo} />] as [string, string, JSX.Element]),
    ["_faq", `Perguntas frequentes (${p.faq.length})`, <MessageCircleQuestion size={15} key="f" />],
    ["_objecoes", `Objeções (${p.objecoes.length})`, <ShieldQuestion size={15} key="o" />],
    ["_escritorio", "Dados do escritório", <Building2 size={15} key="e" />],
  ];

  return (
    <div className="conteudo">
      <nav className="conteudo-menu" aria-label="Partes do conteúdo">
        {itens.map(([chave, rotulo, icone]) => (
          <button key={chave} className={aba === chave ? "on" : ""} onClick={() => setAba(chave)}>{icone}<span>{rotulo}</span>
            {p.instrucoes[chave] && <span className="chip ac" style={{ marginLeft: "auto" }}>personalizado</span>}</button>
        ))}
      </nav>
      <div key={aba} className="conteudo-corpo">
        {aba === "_definicao" && p.editorDefinicao}
        {aba === "_rapida" && (
          <Painel titulo="Edição rápida">
            <div className="form">
              {p.temHonorarios && <label className="field"><span className="lbl">Honorários</span>
                <textarea rows={2} value={p.honorarios} onChange={(e) => p.setHonorarios(e.target.value)} placeholder="Ex.: 30% do valor recebido, pagos só ao final e só se der certo." />
                <span className="ajuda">A IA só pode citar valores escritos aqui. Qualquer outro número é barrado pela trava.</span></label>}
              {campos.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nenhum campo {"{{assim}}"} nas instruções. Para personalizar, abra uma etapa ao lado.</p> :
                campos.map((c) => (
                  <div key={c} className="field"><span className="lbl">{`{{${c}}}`}</span>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input className="inp" value={valoresRapidos[c] ?? ""} onChange={(e) => setValoresRapidos({ ...valoresRapidos, [c]: e.target.value })} />
                      <button className="btn" onClick={() => aplicarCampo(c)} disabled={!valoresRapidos[c]}>Aplicar em todas</button>
                    </div></div>
                ))}
            </div>
          </Painel>
        )}
        {etapaAtual && (
          <Painel titulo={`Instrução: ${etapaAtual.nome}`} acoes={p.instrucoes[etapaAtual.codigo] ? <button className="btn sm" onClick={() => { const { [etapaAtual.codigo]: _x, ...resto } = p.instrucoes; p.setInstrucoes(resto); }}><RotateCcw />Restaurar padrão</button> : undefined}>
            <textarea className="inp codigo" rows={14} aria-label={`Instrução da etapa ${etapaAtual.nome}`}
              value={p.instrucoes[etapaAtual.codigo] ?? etapaAtual.instrucao_padrao}
              onChange={(e) => p.setInstrucoes({ ...p.instrucoes, [etapaAtual.codigo]: e.target.value })} />
            <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>Regras de segurança (não prometer resultado, não citar prazos, travas de valores) valem sempre, mesmo com instrução personalizada.</p>
          </Painel>
        )}
        {aba === "_faq" && (
          <Painel titulo="Perguntas frequentes" acoes={<button className="btn sm" onClick={() => p.setFaq([...p.faq, { pergunta: "", resposta: "" }])}><Plus />Pergunta</button>}>
            <ListaPares itens={p.faq.map((f) => [f.pergunta, f.resposta])} rotulos={["Pergunta", "Resposta"]}
              aoMudar={(l) => p.setFaq(l.map(([pergunta, resposta]) => ({ pergunta, resposta })))} vazio="Ex.: Onde fica o escritório? Quanto custa a consulta?" />
          </Painel>
        )}
        {aba === "_objecoes" && (
          <Painel titulo="Objeções" acoes={<button className="btn sm" onClick={() => p.setObjecoes([...p.objecoes, { objecao: "", resposta: "" }])}><Plus />Objeção</button>}>
            <ListaPares itens={p.objecoes.map((o) => [o.objecao, o.resposta])} rotulos={["Se o lead disser", "Responda assim"]}
              aoMudar={(l) => p.setObjecoes(l.map(([objecao, resposta]) => ({ objecao, resposta })))} vazio="Ex.: “É golpe?”, “Vou pensar”, “Já tentei e negaram”." />
          </Painel>
        )}
        {aba === "_escritorio" && (
          <Painel titulo="Dados do escritório">
            <textarea className="inp" rows={8} value={p.dadosEscritorio} onChange={(e) => p.setDadosEscritorio(e.target.value)}
              placeholder={"Endereço, horário, advogados responsáveis, OAB, diferenciais…"} aria-label="Dados do escritório" />
            <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>A IA usa quando o lead pergunta. Não inventa o que não estiver aqui.</p>
          </Painel>
        )}
      </div>
    </div>
  );
}

export function ListaPares({ itens, rotulos, aoMudar, vazio }: { itens: [string, string][]; rotulos: [string, string]; aoMudar: (l: [string, string][]) => void; vazio: string }) {
  if (!itens.length) return <Vazio>{vazio}</Vazio>;
  return (
    <div className="form">{itens.map(([a, b], i) => (
      <div key={i} className="par">
        <input className="inp" aria-label={rotulos[0]} placeholder={rotulos[0]} value={a} onChange={(e) => aoMudar(itens.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))} />
        <textarea className="inp" rows={2} aria-label={rotulos[1]} placeholder={rotulos[1]} value={b} onChange={(e) => aoMudar(itens.map((x, j) => (j === i ? [x[0], e.target.value] : x)))} />
        <button className="btn ghost sm" aria-label="Tirar" onClick={() => aoMudar(itens.filter((_, j) => j !== i))}><X /></button>
      </div>
    ))}</div>
  );
}
