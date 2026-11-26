import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, Ban, Bot, Brain, ChevronDown, CirclePause, CirclePlay, CircleStop, ClipboardList, Cpu, Flame, Info, LogIn, Megaphone, Route,
  Shield, ShieldAlert, Sparkles, UserRound,
} from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { formatarTelefone } from "../../api";
import {
  FONTES_FATO, MODOS_TURNO, MOTIVO_DESATIVADA, PRAZOS_DESATIVAR, QUEM_RASTRO, RESPONSAVEIS, ROTULOS_ORIGEM, SITUACOES_TURNO, chaveLegivel,
  dataHora, duracao, estadoDaIa, motivoLegivel, nomeDoEvento, nomeEtapa, valorLegivel, type AcaoIa, type DetalheConversa, type EstadoLead,
  type ItemRastro, type TipoRastro,
} from "./tipos";

/** Botões da IA nesta conversa: "Desativar IA" (30 min, 2 h, 24 h ou até religar), "Reativar IA" e "Encerrar".
 *  Mostra só o que faz sentido no estado atual. Gestor e atendente usam (a API é aberta aos dois). */
export function BotoesIa({ conversa: c, ocupado, aoAgir, compacto = false }: {
  conversa: DetalheConversa; ocupado: boolean; aoAgir: (acao: AcaoIa, minutos?: number) => void; compacto?: boolean;
}) {
  const tam = compacto ? " sm" : "";
  const rotulo = (curto: string, longo: string) => compacto ? <span className="max-[560px]:hidden">{curto}</span> : <span>{longo}</span>;
  const estado: EstadoLead = c.estado;
  const vencida = estado === "pausado" && c.pausado_ate != null && new Date(c.pausado_ate).getTime() <= Date.now();
  const pausada = estado === "pausado" && !vencida;
  const daEquipe = pausada && c.motivo_estado === MOTIVO_DESATIVADA;
  return (
    <>
      {estado !== "encerrado" && !daEquipe && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className={`cv-botao ambar${tam}`} disabled={ocupado} aria-label="Desativar a IA nesta conversa">
              <CirclePause aria-hidden />{rotulo("Desativar", "Desativar IA")}<ChevronDown aria-hidden className="opacity-70" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-[11rem]">
            <DropdownMenuLabel className="text-[11px] font-semibold uppercase tracking-wider text-[#98A2B3]">Desligar a IA</DropdownMenuLabel>
            {PRAZOS_DESATIVAR.map((p) => (
              <DropdownMenuItem key={p.minutos} onSelect={() => aoAgir("desativar", p.minutos)}>{p.rotulo}</DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {(pausada || estado === "encerrado") && (
        <button type="button" className={`cv-botao verde${tam}`} disabled={ocupado} onClick={() => aoAgir("reativar")}
          aria-label={estado === "encerrado" ? "Devolver a conversa para a IA" : "Reativar a IA nesta conversa"}>
          <CirclePlay aria-hidden />{estado === "encerrado" ? rotulo("Devolver", "Devolver para a IA") : rotulo("Reativar", "Reativar IA")}
        </button>
      )}
      {estado !== "encerrado" && (
        <button type="button" className={`cv-botao vermelho${tam}`} disabled={ocupado} onClick={() => aoAgir("encerrar")} aria-label="Encerrar a conversa">
          <CircleStop aria-hidden />{rotulo("Encerrar", "Encerrar a conversa")}
        </button>
      )}
    </>
  );
}

type Aba = "resumo" | "rastro" | "turnos" | "eventos";

/** Coluna da direita (ou gaveta, em telas menores): a IA nesta conversa, fatos, etapa, origem, turnos e eventos. */
export function PainelLateral({ detalhe: d, ocupado, aoAgir, semBotoes = false }: {
  detalhe: DetalheConversa; ocupado: boolean; aoAgir: (acao: AcaoIa, minutos?: number) => void; semBotoes?: boolean;
}) {
  const [aba, setAba] = useState<Aba>("resumo");
  const erros = d.eventos.filter((e) => e.gravidade === "erro" || e.gravidade === "critico").length;
  const abas: { valor: Aba; rotulo: string; qtd?: number; alerta?: boolean }[] = [
    { valor: "resumo", rotulo: "Resumo" },
    { valor: "rastro", rotulo: "Rastro", qtd: (d.rastro ?? []).filter((i) => i.tipo !== "entrada").length },
    { valor: "turnos", rotulo: "Turnos", qtd: d.turnos.length },
    { valor: "eventos", rotulo: "Eventos", qtd: d.eventos.length, alerta: erros > 0 },
  ];
  return (
    <div className="flex flex-col min-h-0 h-full">
      {!semBotoes && (
        <div className="p-3.5 pb-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[#98A2B3] mb-2">A IA nesta conversa</p>
          <p className="text-[13px] font-semibold mb-2" style={{ color: estadoDaIa(d).cor }}>{estadoDaIa(d).rotulo}</p>
          <div className="cv-botoes"><BotoesIa conversa={d} ocupado={ocupado} aoAgir={aoAgir} /></div>
        </div>
      )}
      <div className="cv-abas" role="tablist" aria-label="Detalhes do lead">
        {abas.map((a) => {
          const on = aba === a.valor;
          return (
            <button key={a.valor} type="button" role="tab" aria-selected={on} className="cv-aba" onClick={() => setAba(a.valor)}>
              {on && <motion.span layoutId="cv-aba-ativa" className="cv-filtro-fundo" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
              <span>
                {a.rotulo}
                {a.qtd != null && a.qtd > 0 && <span className={`font-mono text-[10.5px] ${a.alerta ? "text-[#DC2626]" : "text-[#98A2B3]"}`}>{a.qtd}</span>}
              </span>
            </button>
          );
        })}
      </div>
      <div className="cv-lateral-corpo" role="tabpanel">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={aba} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }}>
            {aba === "resumo" && <Resumo d={d} />}
            {aba === "rastro" && <Rastro d={d} />}
            {aba === "turnos" && <Turnos d={d} />}
            {aba === "eventos" && <Eventos d={d} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

function Resumo({ d }: { d: DetalheConversa }) {
  const estado = estadoDaIa(d);
  const motivo = d.estado !== "ativo" ? motivoLegivel(d.motivo_estado) : null;
  return (
    <>
      <div className="cv-bloco">
        <h4><UserRound aria-hidden /> Lead</h4>
        <dl className="cv-dl">
          <dt>Situação</dt>
          <dd><span className="inline-flex items-center gap-1 rounded-md px-1.5 py-px text-[10.5px] font-bold uppercase tracking-wide" style={{ background: estado.fundo, color: estado.cor }}>{estado.rotulo}</span></dd>
          {motivo && <><dt>Motivo</dt><dd>{motivo}</dd></>}
          {d.estado === "pausado" && d.pausado_ate && <><dt>IA volta</dt><dd>{dataHora(d.pausado_ate)}</dd></>}
          <dt>Etapa</dt><dd>{nomeEtapa(d.etapa)}</dd>
          <dt>Agente</dt><dd>{d.agente ?? "—"}</dd>
          <dt>Telefone</dt><dd className="tabular-nums">{formatarTelefone(d.telefone) || "oculto"}</dd>
          <dt>Chegou em</dt><dd>{dataHora(d.criado_em)}</dd>
          <dt>Lead falou</dt><dd>{dataHora(d.ultima_mensagem_lead_em)}</dd>
          <dt>IA falou</dt><dd>{dataHora(d.ultima_resposta_ia_em)}</dd>
        </dl>
      </div>
      <Memoria memoria={d.memoria} />
      <Origem origem={d.origem} />
      <Fatos d={d} />
    </>
  );
}

/** Acima disto, a ficha aparece recolhida, com "Ler tudo". */
const MEMORIA_CURTA = 360;

/** Ficha de memória: quando a conversa fica longa, a IA lê este resumo no lugar das mensagens antigas. */
function Memoria({ memoria }: { memoria: DetalheConversa["memoria"] }) {
  const [inteira, setInteira] = useState(false);
  const resumo = (memoria?.resumo ?? "").trim();
  if (!memoria || !resumo) {
    return (
      <div className="cv-bloco">
        <h4><Brain aria-hidden /> Memória da IA</h4>
        <p className="text-[12.5px] text-[#667085] m-0">Ainda sem resumo. Quando a conversa fica longa, a IA resume as mensagens antigas e passa a ler o resumo no lugar delas.</p>
      </div>
    );
  }
  const longa = resumo.length > MEMORIA_CURTA;
  const qtd = memoria.mensagens_resumidas;
  return (
    <div className="cv-bloco">
      <h4><Brain aria-hidden /> Memória da IA</h4>
      <p className="text-[11.5px] text-[#667085] mt-0 mb-2">
        Resume {qtd} {qtd === 1 ? "mensagem antiga" : "mensagens antigas"} · atualizada em {dataHora(memoria.atualizado_em)}
      </p>
      <p className={`cv-memoria${longa && !inteira ? " recolhida" : ""}`}>{resumo}</p>
      {longa && (
        <button type="button" className="mt-1.5 text-[11.5px] font-semibold text-[#475467] hover:text-[#00852A]" aria-expanded={inteira} onClick={() => setInteira((v) => !v)}>
          {inteira ? "Recolher" : "Ler tudo"}
        </button>
      )}
    </div>
  );
}

function Origem({ origem }: { origem: DetalheConversa["origem"] }) {
  const o = origem && typeof origem === "object" ? origem : {};
  const linhas = ROTULOS_ORIGEM.filter(([chave]) => o[chave] != null && o[chave] !== "");
  const tipo = o.origem === "anuncio" ? "Anúncio (clique para o WhatsApp)" : o.origem === "utm" ? "Link com UTM" : null;
  return (
    <div className="cv-bloco">
      <h4><Megaphone aria-hidden /> Origem</h4>
      {!tipo && linhas.length === 0 ? (
        <p className="text-[12.5px] text-[#667085] m-0">Veio direto, sem anúncio nem UTM registrado.</p>
      ) : (
        <dl className="cv-dl">
          {tipo && <><dt>Veio de</dt><dd>{tipo}</dd></>}
          {typeof o.produto === "string" && <><dt>Assunto</dt><dd>{chaveLegivel(o.produto)}</dd></>}
          {linhas.map(([chave, rotulo]) => (
            <FragmentoOrigem key={chave} rotulo={rotulo} valor={String(o[chave])} link={chave === "url"} />
          ))}
        </dl>
      )}
    </div>
  );
}

function FragmentoOrigem({ rotulo, valor, link }: { rotulo: string; valor: string; link: boolean }) {
  const seguro = link && /^https?:\/\//i.test(valor);
  return (
    <>
      <dt>{rotulo}</dt>
      <dd>{seguro ? <a href={valor} target="_blank" rel="noopener noreferrer nofollow" className="text-[#00852A] underline-offset-2 hover:underline break-all">{valor}</a> : valor}</dd>
    </>
  );
}

function Fatos({ d }: { d: DetalheConversa }) {
  const [verAntigos, setVerAntigos] = useState(false);
  const vigentes = d.fatos.filter((f) => !f.substituido_em);
  const antigos = d.fatos.filter((f) => f.substituido_em);
  return (
    <div className="cv-bloco">
      <h4><ClipboardList aria-hidden /> Fatos do lead {vigentes.length > 0 && <span className="font-mono text-[10.5px] text-[#98A2B3] font-normal">{vigentes.length}</span>}</h4>
      {vigentes.length === 0 ? (
        <p className="text-[12.5px] text-[#667085] m-0">A IA ainda não registrou nenhum fato desta conversa.</p>
      ) : vigentes.map((f) => (
        <div key={`${f.chave}-${f.criado_em}`} className="cv-fato">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11.5px] text-[#667085]">{chaveLegivel(f.chave)}</span>
            <span className="text-[10px] text-[#98A2B3] shrink-0">{FONTES_FATO[f.fonte] ?? f.fonte}</span>
          </div>
          <div className="text-[13px] font-semibold text-[#101828] break-words">{valorLegivel(f.valor)}</div>
          {f.trecho && <div className="cv-trecho">“{f.trecho}”</div>}
        </div>
      ))}
      {antigos.length > 0 && (
        <>
          <button type="button" className="mt-2 text-[11.5px] font-semibold text-[#475467] hover:text-[#00852A]" aria-expanded={verAntigos} onClick={() => setVerAntigos((v) => !v)}>
            {verAntigos ? "Esconder valores anteriores" : `Ver ${antigos.length} ${antigos.length === 1 ? "valor anterior" : "valores anteriores"}`}
          </button>
          {verAntigos && antigos.map((f) => (
            <div key={`${f.chave}-${f.criado_em}`} className="cv-fato opacity-70">
              <span className="text-[11.5px] text-[#667085]">{chaveLegivel(f.chave)} · trocado em {dataHora(f.substituido_em)}</span>
              <div className="text-[12.5px] text-[#475467] line-through break-words">{valorLegivel(f.valor)}</div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function Turnos({ d }: { d: DetalheConversa }) {
  if (d.turnos.length === 0) return <Nada icone={<Bot className="size-4" />} texto="A IA ainda não processou nenhuma mensagem deste lead." />;
  return (
    <div className="cv-bloco">
      <h4><Cpu aria-hidden /> Turnos da IA <span className="font-mono text-[10.5px] text-[#98A2B3] font-normal">últimos {d.turnos.length}</span></h4>
      <p className="text-[11.5px] text-[#667085] mt-0 mb-2">Cada turno é um lote de mensagens do lead e o que a IA fez com ele.</p>
      {d.turnos.map((t) => {
        const s = SITUACOES_TURNO[t.situacao] ?? { rotulo: t.situacao, chip: "" };
        const tempo = duracao(t.iniciado_em, t.concluido_em);
        const mudou = t.etapa_depois && t.etapa_antes !== t.etapa_depois;
        return (
          <div key={t.id} className="cv-turno">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className={`chip ${s.chip}`}><span className="d" />{s.rotulo}</span>
              <span className="text-[11px] text-[#98A2B3]">{dataHora(t.iniciado_em)}{tempo ? ` · ${tempo}` : ""}</span>
            </div>
            <div className="mt-1 text-[12px] text-[#475467] flex items-center gap-1 flex-wrap">
              {mudou ? (<>{nomeEtapa(t.etapa_antes)} <ArrowRight className="size-3 text-[#00bc33]" aria-label="para" /> <b className="text-[#101828]">{nomeEtapa(t.etapa_depois)}</b></>)
                : <>Etapa: {nomeEtapa(t.etapa_antes ?? t.etapa_depois)}</>}
              {t.modo !== "producao" && <span className="text-[10.5px] text-[#98A2B3]">· {MODOS_TURNO[t.modo] ?? t.modo}</span>}
            </div>
            {t.motivo && <div className="mt-0.5 text-[12px] text-[#667085] break-words">{t.motivo}</div>}
            {t.resposta != null && (
              <details className="mt-1.5">
                <summary>Ver detalhes técnicos</summary>
                <pre className="bloco">{JSON.stringify(t.resposta, null, 2)}</pre>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}

const GRAVIDADES: Record<string, string> = { info: "", aviso: "warn", erro: "bad", critico: "bad" };

function Eventos({ d }: { d: DetalheConversa }) {
  if (d.eventos.length === 0) return <Nada icone={<Sparkles className="size-4" />} texto="Nenhum problema ou trava nesta conversa." />;
  return (
    <div className="cv-bloco">
      <h4><ShieldAlert aria-hidden /> Eventos <span className="font-mono text-[10.5px] text-[#98A2B3] font-normal">{d.eventos.length}</span></h4>
      {d.eventos.map((e, i) => (
        <div key={`${e.tipo}-${e.criado_em}-${i}`} className="cv-evento">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`chip ${GRAVIDADES[e.gravidade] ?? ""}`}><span className="d" />{e.gravidade === "critico" ? "crítico" : e.gravidade}</span>
            {e.responsavel && <span className="text-[11px] text-[#667085]">{RESPONSAVEIS[e.responsavel] ?? e.responsavel}</span>}
            <span className="text-[11px] text-[#98A2B3] ml-auto">{dataHora(e.criado_em)}</span>
          </div>
          <div className="mt-1 text-[12.5px] font-semibold text-[#101828] break-words">{nomeDoEvento(e.tipo)}</div>
          {e.descricao && <div className="text-[12px] text-[#475467] break-words">{e.descricao}</div>}
          <div className="text-[10.5px] text-[#98A2B3] font-mono">{e.tipo}</div>
        </div>
      ))}
    </div>
  );
}

/** Visual de cada tipo de item do rastro: seta para passagem, escudo para barreira, pausa para a equipe. */
const VISUAL_RASTRO: Record<TipoRastro, { Icone: typeof ArrowRight; cor: string; fundo: string }> = {
  entrada: { Icone: LogIn, cor: "#475467", fundo: "#F1F5F9" },
  passagem: { Icone: ArrowRight, cor: "#00852A", fundo: "#e8f9ee" },
  recusa: { Icone: Ban, cor: "#b45309", fundo: "#fff4df" },
  barreira: { Icone: Shield, cor: "#b42318", fundo: "#fef3f2" },
  alerta: { Icone: Flame, cor: "#c2410c", fundo: "#fff1e6" },
  pausa: { Icone: CirclePause, cor: "#6d28d9", fundo: "#f3effe" },
};

/** Aba "Rastro" (B11): o funil com a etapa ativa destacada e a linha do tempo de quem atendeu, quando e por quê. */
function Rastro({ d }: { d: DetalheConversa }) {
  const funil = d.funil;
  const itens = d.rastro ?? [];
  return (
    <>
      <div className="cv-bloco">
        <h4><Route aria-hidden /> Funil do agente</h4>
        {!funil || funil.etapas.length === 0 ? (
          <p className="text-[12.5px] text-[#667085] m-0">Sem as etapas do agente desta conversa.</p>
        ) : (
          <>
            <ol className="m-0 p-0 list-none flex flex-wrap items-center gap-1" aria-label="Etapas do funil">
              {funil.etapas.map((e, i) => (
                <li key={e.codigo} className="flex items-center gap-1">
                  {i > 0 && <ArrowRight className="size-3 text-[#cbd5e1]" aria-hidden />}
                  <span aria-current={e.ativa ? "step" : undefined}
                    title={e.ativa ? "Etapa ativa agora" : e.alcancavel ? "Pode passar para esta etapa agora" : e.visitada ? "Já passou por aqui" : undefined}
                    className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-semibold border ${
                      e.ativa ? "bg-[#00bc33] text-white border-[#00bc33] shadow-[0_4px_12px_-6px_#00bc33]"
                        : e.alcancavel ? "bg-white text-[#0a6b25] border-[#00bc33]/60 border-dashed"
                        : e.visitada ? "bg-[#e8f9ee] text-[#0a6b25] border-transparent"
                        : "bg-[#F8FAFC] text-[#98A2B3] border-[#EAECF0]"}`}>
                    {e.nome}
                  </span>
                </li>
              ))}
            </ol>
            <p className="text-[11px] text-[#98A2B3] mt-2 mb-0">
              <span className="inline-block size-2 rounded-sm bg-[#00bc33] mr-1 align-middle" />ativa
              <span className="inline-block size-2 rounded-sm border border-dashed border-[#00bc33] ml-2.5 mr-1 align-middle" />pode ir agora
              <span className="inline-block size-2 rounded-sm bg-[#e8f9ee] ml-2.5 mr-1 align-middle" />já passou
            </p>
          </>
        )}
      </div>
      <div className="cv-bloco">
        <h4><Cpu aria-hidden /> Linha do tempo {itens.length > 0 && <span className="font-mono text-[10.5px] text-[#98A2B3] font-normal">{itens.length}</span>}</h4>
        {itens.length === 0 ? (
          <p className="text-[12.5px] text-[#667085] m-0">Nenhuma passagem, recusa, barreira ou pausa nesta conversa ainda.</p>
        ) : (
          <ol className="m-0 p-0 list-none">
            {itens.map((item, i) => <LinhaRastro key={`${item.quando}-${item.tipo}-${i}`} item={item} />)}
          </ol>
        )}
      </div>
    </>
  );
}

function LinhaRastro({ item }: { item: ItemRastro }) {
  const v = VISUAL_RASTRO[item.tipo] ?? VISUAL_RASTRO.alerta;
  const titulo = item.evento && item.tipo !== "pausa" ? nomeDoEvento(item.evento) : item.titulo;
  const quem = item.quem ? QUEM_RASTRO[item.quem] ?? item.quem : null;
  const passagem = item.tipo === "passagem" || item.tipo === "entrada";
  return (
    <li className="flex gap-2.5 py-2 border-b border-[#F1F5F9] last:border-b-0">
      <span className="mt-0.5 size-6 shrink-0 rounded-lg grid place-items-center" style={{ background: v.fundo, color: v.cor }}><v.Icone className="size-3.5" aria-hidden /></span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[12.5px] font-semibold text-[#101828]">{item.tipo === "passagem" ? "Passagem" : titulo}</span>
          <span className="text-[10.5px] text-[#98A2B3] shrink-0">{dataHora(item.quando)}</span>
        </div>
        {passagem ? (
          <div className="text-[12px] text-[#475467] flex items-center gap-1 flex-wrap">
            {item.de && <>{item.nome_de ?? nomeEtapa(item.de)} <ArrowRight className="size-3 text-[#00bc33]" aria-label="para" /></>}
            <b className="text-[#101828]">{item.nome_para ?? nomeEtapa(item.para)}</b>
            {quem && <span className="text-[#667085]">· {quem}</span>}
          </div>
        ) : (item.para || quem) ? (
          <div className="text-[12px] text-[#475467]">
            {item.para && <>{item.tipo === "recusa" ? "Destino: " : "Para: "}<b>{item.nome_para ?? nomeEtapa(item.para)}</b> </>}
            {quem && <span className="text-[#667085]">{item.para ? "· " : ""}{quem}</span>}
          </div>
        ) : null}
        {item.motivo && <div className="mt-0.5 text-[11.5px] text-[#667085] break-words">{item.tipo === "passagem" ? `Por quê: ${item.motivo}` : item.motivo}</div>}
      </div>
    </li>
  );
}

function Nada({ icone, texto }: { icone: React.ReactNode; texto: string }) {
  return (
    <div className="cv-bloco text-center py-6">
      <div className="mx-auto size-9 rounded-xl grid place-items-center bg-[#F1F5F9] text-[#667085]">{icone}</div>
      <p className="mt-2 mb-0 text-[12.5px] text-[#667085] flex items-center justify-center gap-1"><Info className="size-3.5" aria-hidden />{texto}</p>
    </div>
  );
}
