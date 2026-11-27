import { useEffect, useState } from "react";
import BotaoBrilho from "@/components/reactbits/BotaoBrilho";
import { Power, Save, UserPlus } from "lucide-react";
import { enviar, quando } from "../api";
import { Alerta, Cabecalho, Carregando, Interruptor, Modal, Painel, SenhaProvisoria, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface Escritorio {
  id: string; nome: string; ia_desligada: boolean; situacao: string; config: Record<string, any>;
  usuarios: { id: string; email: string; nome: string; papel: string; ativo: boolean; ultimo_acesso_em: string | null }[];
}

const DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const PRODUTOS_ANUNCIO: [string, string][] = [["auxilio_acidente", "Auxílio-acidente"], ["bpc_loas", "BPC/LOAS"],
  ["auxilio_doenca", "Auxílio-doença"], ["aposentadoria_invalidez", "Aposentadoria por invalidez"], ["aposentadoria", "Aposentadoria"],
  ["pensao_morte", "Pensão por morte"], ["salario_maternidade", "Salário-maternidade"], ["revisao", "Revisão"]];

/** O mesmo que o servidor faz (app/cerebro/sinais.py, dominio_do_escritorio): "advmidia", "advmidia.wts.chat"
 *  ou a URL inteira viram "advmidia.wts.chat". Devolve null quando não dá um endereço válido. */
export function normalizarDominioHelena(valor: string): string | null {
  const bruto = valor.trim().toLowerCase().replace(/^https?:\/\//, "").split("/")[0].replace(/^\.+|\.+$/g, "");
  if (!bruto) return null;
  const host = bruto.includes(".") ? bruto : `${bruto}.wts.chat`;
  return /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$/.test(host) ? host : null;
}

/** Campo do domínio da LawChat, com a explicação e o link de exemplo (usado aqui e no cadastro de escritório). */
export function CampoDominioHelena({ valor, aoMudar }: { valor: string; aoMudar: (v: string) => void }) {
  const dominio = normalizarDominioHelena(valor);
  return (
    <label className="field"><span className="lbl">Domínio da LawChat</span>
      <input value={valor} onChange={(e) => aoMudar(e.target.value)} placeholder="advmidia.wts.chat"
        spellCheck={false} autoCapitalize="none" autoCorrect="off" inputMode="url" />
      <span className="ajuda">O endereço em que a equipe abre a LawChat. Serve para pôr o link da conversa nos avisos à equipe; sem ele, o aviso sai sem o link.</span>
      {valor.trim() && (dominio
        ? <span className="ajuda">Link de exemplo: <span className="mono">https://{dominio}/redirect?type=SESSION&amp;id=…</span></span>
        : <span className="ajuda" style={{ color: "var(--warn)" }}>Endereço inválido. Use, por exemplo, meuescritorio ou meuescritorio.wts.chat.</span>)}
    </label>
  );
}

export function TelaConfiguracoes() {
  const { escritorio, admin } = useSessao();
  const { dados, erro, recarregar } = useCarregar<Escritorio>("/escritorio", [escritorio], { guardar: false }); // formulário: sempre o dado do servidor
  const { ocupado, executar } = useAcao();
  const [form, setForm] = useState({ nome: "", honorarios: "", horario_inicio: 8, horario_fim: 18, horario_dias: [0, 1, 2, 3, 4], modo_ia_horario: "sempre", etiquetas_por_produto: {} as Record<string, string>, dominio_helena: "" });
  const [novo, setNovo] = useState<{ email: string; nome: string; papel: string } | null>(null);
  const [senha, setSenha] = useState<string | null>(null);

  useEffect(() => {
    if (dados) setForm({ nome: dados.nome, honorarios: dados.config.honorarios ?? "", horario_inicio: dados.config.horario_inicio ?? 8,
      horario_fim: dados.config.horario_fim ?? 18, horario_dias: dados.config.horario_dias ?? [0, 1, 2, 3, 4], modo_ia_horario: dados.config.modo_ia_horario ?? "sempre",
      etiquetas_por_produto: dados.config.etiquetas_por_produto ?? {}, dominio_helena: dados.config.dominio_helena ?? "" });
  }, [dados]);
  if (!dados) return <Carregando erro={erro} />;

  const salvar = () => executar(async () => { await enviar("/escritorio", form, "PATCH"); await recarregar(); }, "Escritório salvo.");
  const alternarIa = (desligar: boolean) => executar(async () => { await enviar("/escritorio", { ia_desligada: desligar }, "PATCH"); await recarregar(); },
    desligar ? "IA desligada em todo o escritório." : "IA religada.");

  return (
    <>
      <Cabecalho eyebrow="Configurar" titulo="Escritório" texto="Dados do escritório, interruptor geral da IA e quem acessa o painel." />
      <div className="two">
        <Painel titulo="Dados" acoes={<BotaoBrilho size="sm" radius={10} onClick={salvar} disabled={ocupado}><Save />Salvar</BotaoBrilho>}>
          <div className="form">
            <label className="field"><span className="lbl">Nome</span><input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></label>
            <label className="field"><span className="lbl">Honorários padrão</span>
              <textarea rows={3} value={form.honorarios} onChange={(e) => setForm({ ...form, honorarios: e.target.value })} />
              <span className="ajuda">Usado nos agentes novos. Cada agente pode ter o seu.</span></label>
            <div className="form cols">
              <label className="field"><span className="lbl">Horário comercial: início</span><input type="number" min={0} max={23} value={form.horario_inicio} onChange={(e) => setForm({ ...form, horario_inicio: Number(e.target.value) })} /></label>
              <label className="field"><span className="lbl">Fim</span><input type="number" min={1} max={24} value={form.horario_fim} onChange={(e) => setForm({ ...form, horario_fim: Number(e.target.value) })} /></label>
            </div>
            <div className="field"><span className="lbl">Dias de atendimento</span>
              <div className="dias" role="group" aria-label="Dias de atendimento">
                {DIAS.map((nome, i) => {
                  const on = form.horario_dias.includes(i);
                  return <button key={nome} type="button" aria-pressed={on} className={`chip ${on ? "ac" : ""}`}
                    onClick={() => setForm({ ...form, horario_dias: on ? form.horario_dias.filter((d) => d !== i) : [...form.horario_dias, i].sort((x, y) => x - y) })}>{nome}</button>;
                })}
              </div>
            </div>
            <label className="field"><span className="lbl">Quando a IA atende</span>
              <select value={form.modo_ia_horario} onChange={(e) => setForm({ ...form, modo_ia_horario: e.target.value })}>
                <option value="sempre">Sempre, 24 horas</option>
                <option value="so_no_horario">Só no horário comercial (fora dele, responde quando abrir)</option>
                <option value="so_fora_do_horario">Só fora do horário (no horário, a equipe atende)</option>
              </select>
              <span className="ajuda">Horário de Brasília. Vale para os agentes em produção; no modo teste a IA sempre responde.</span></label>
            <CampoDominioHelena valor={form.dominio_helena} aoMudar={(v) => setForm({ ...form, dominio_helena: v })} />
            <div className="field"><span className="lbl">Etiqueta pelo benefício do anúncio</span>
              <span className="ajuda" style={{ marginTop: 0 }}>Quando o lead vem de anúncio, a IA descobre o benefício anunciado e põe esta etiqueta na LawChat. Vazio = só a nota.</span>
              <div className="grid2" style={{ gap: 8 }}>
                {PRODUTOS_ANUNCIO.map(([codigo, nome]) => (
                  <label key={codigo} className="field" style={{ gap: 2 }}><span className="muted" style={{ fontSize: 12 }}>{nome}</span>
                    <input value={form.etiquetas_por_produto[codigo] ?? ""} placeholder="Etiqueta na LawChat"
                      onChange={(e) => setForm({ ...form, etiquetas_por_produto: { ...form.etiquetas_por_produto, [codigo]: e.target.value } })} /></label>
                ))}
              </div>
            </div>
          </div>
        </Painel>
        <div className="stack">
          <Painel titulo={<h3 style={{ display: "flex", gap: 8, alignItems: "center" }}><Power className="i" />Interruptor geral</h3>}>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <Interruptor rotulo="IA ligada no escritório" ligado={!dados.ia_desligada} aoMudar={(v) => alternarIa(!v)} desligado={ocupado} />
              <div><b>{dados.ia_desligada ? "IA desligada" : "IA ligada"}</b><div className="sec" style={{ fontSize: 13 }}>Desligar para todos os agentes de uma vez, numa emergência. As mensagens continuam registradas.</div></div>
            </div>
            {dados.situacao !== "ativo" && <div style={{ marginTop: 10 }}><Alerta tipo="warn">Escritório {dados.situacao}: a IA não responde.</Alerta></div>}
          </Painel>
          <Painel titulo="Quem acessa" sem_corpo acoes={<BotaoBrilho suave size="sm" radius={10} onClick={() => setNovo({ email: "", nome: "", papel: "atendente" })}><UserPlus />Convidar</BotaoBrilho>}>
            {dados.usuarios.length === 0 ? <Vazio>Ninguém ainda. Quem entra pela LawChat aparece aqui sozinho.</Vazio> : (
              <div className="rows">{dados.usuarios.map((u) => (
                <div key={u.id}>
                  <div style={{ flex: 1, minWidth: 0 }}><b>{u.nome}</b><div className="muted" style={{ fontSize: 12 }}>{u.email.endsWith(".helena.local") ? "entra pela LawChat" : u.email} · último acesso {quando(u.ultimo_acesso_em)}</div></div>
                  <span className="chip">{u.papel}</span>
                </div>
              ))}</div>
            )}
          </Painel>
          {admin && <Alerta tipo="info">Você está vendo como equipe LawChat.</Alerta>}
        </div>
      </div>

      {novo && (
        <Modal titulo="Convidar pessoa" texto="Ela recebe uma senha provisória para entrar fora da LawChat." aoFechar={() => { setNovo(null); setSenha(null); }}
          rodape={senha ? <><span className="sp" /><button className="btn pri" onClick={() => { setNovo(null); setSenha(null); }}>Pronto</button></> : <>
            <span className="sp" /><button className="btn" onClick={() => setNovo(null)}>Cancelar</button>
            <button className="btn pri" disabled={ocupado || !novo.email || novo.nome.length < 2} onClick={() => executar(async () => {
              const r = await enviar<{ senha_provisoria: string }>("/escritorio/usuarios", novo);
              setSenha(r.senha_provisoria); await recarregar();
            })}>Convidar</button></>}>
          {senha ? <SenhaProvisoria senha={senha} para={novo?.nome || novo?.email} nota="Envie para a pessoa por um canal seguro; ela troca no primeiro acesso." /> : (
            <div className="form">
              <label className="field"><span className="lbl">Nome</span><input value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })} /></label>
              <label className="field"><span className="lbl">E-mail</span><input type="email" value={novo.email} onChange={(e) => setNovo({ ...novo, email: e.target.value })} /></label>
              <label className="field"><span className="lbl">Papel</span>
                <select value={novo.papel} onChange={(e) => setNovo({ ...novo, papel: e.target.value })}>
                  <option value="atendente">Atendente: acompanha o início (sem configurar)</option>
                  <option value="gestor">Gestor: cria e edita agentes</option>
                </select></label>
            </div>
          )}
        </Modal>
      )}
    </>
  );
}
