import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Check, Plus, Save, Wallet, X } from "lucide-react";
import { enviar, quando } from "../api";
import { Alerta, Cabecalho, Carregando, Modal, Painel, Vazio, useAcao, useCarregar, useConfirmar } from "../componentes/ui";
import { Extrato, reais, type Movimento } from "./Carteira";

/*
 * Cobrança (equipe LawChat): carteiras de todos, lançamentos com motivo, recargas, planos, cotação e markup, e o
 * consumo por escritório com custo real × valor cobrado (margem).
 */

interface LinhaCarteira { id_escritorio: string; nome: string; modo: string; saldo_brl: number; bonus_brl: number; bonus_do_mes_brl: number;
  pausado_por_saldo: boolean; pausado_em: string | null; markup: number | null; id_plano: string | null; plano: string | null; pendente_brl: number;
  custo_usd: number; custo_brl_real: number; cobrado_brl: number; recargas_pendentes: number }
interface Plano { id: string; codigo: string; nome: string; descricao: string | null; preco_mensal_brl: number; bonus_mensal_brl: number;
  bonus_acumula: boolean; ativo: boolean; ordem: number; escritorios: number }
interface Config { vigente: { cotacao_usd_brl: number; markup: number; markup_percentual: number; vigente_desde: string | null };
  historico: { id: string; cotacao_usd_brl: number; markup: number; vigente_desde: string; motivo: string | null; usuario: string | null }[] }
interface RecargaAdmin { id: string; id_escritorio: string; escritorio: string; valor_brl: number; situacao: string; gateway: string; metodo: string | null;
  criado_em: string; paga_em: string | null; observacao: string | null; pedido_por: string | null; confirmada_por: string | null }
interface Soma { chamadas: number; tokens: number; custo_usd: number; custo_brl_real: number; cobrado_brl: number; margem_brl: number }
interface ConsumoAdmin { dias: number; total: { custo_usd: number; custo_brl_real: number; cobrado_brl: number; margem_brl: number };
  por_escritorio: (Soma & { id_escritorio: string; nome: string })[]; por_modelo: (Soma & { modelo: string; sem_preco: number })[]; chamadas_sem_preco: number }

type Aba = "carteiras" | "recargas" | "planos" | "cotacao" | "consumo";
const ABAS: [Aba, string][] = [["carteiras", "Carteiras"], ["recargas", "Recargas"], ["planos", "Planos"], ["cotacao", "Cotação e markup"], ["consumo", "Consumo e margem"]];
const usd = (v: number | null | undefined) => `US$ ${(v ?? 0).toFixed(4)}`;

// Financeiro = Carteiras, Cotação e markup e Consumo e margem. Recargas é uma tela própria (item do menu).
// Planos fica fora por enquanto (o componente Planos continua no arquivo para quando voltar).
const ABAS_FINANCEIRO: [Aba, string][] = [["carteiras", "Carteiras"], ["cotacao", "Cotação e markup"], ["consumo", "Consumo e margem"]];

export function TelaAdminCobranca() {
  // A aba vem do endereço (?aba=recargas): o menu do superadmin abre Recargas e Financeiro direto.
  const [params, setParams] = useSearchParams();
  const pedida = params.get("aba") as Aba | null;
  const aba: Aba = pedida && ABAS.some(([id]) => id === pedida) && pedida !== "planos" ? pedida : "carteiras";
  const setAba = (nova: Aba) => setParams({ aba: nova });
  if (aba === "recargas") {
    return (
      <>
        <Cabecalho eyebrow="Superadmin" titulo="Recargas"
          texto="Pedidos de crédito dos escritórios. Quando o pagamento cair na conta, confirme aqui: o valor entra no saldo e a IA volta a responder se estava pausada." />
        <Recargas />
      </>
    );
  }
  return (
    <>
      <Cabecalho eyebrow="Superadmin" titulo="Financeiro"
        texto="Saldo de cada escritório em R$, o preço cobrado pela IA (cotação do dólar e markup) e quanto cada escritório consumiu." />
      <div className="seg" role="tablist" aria-label="Seções do financeiro" style={{ marginBottom: 16 }}>
        {ABAS_FINANCEIRO.map(([id, nome]) => <button key={id} role="tab" aria-selected={aba === id} className={aba === id ? "on" : ""} onClick={() => setAba(id)}>{nome}</button>)}
      </div>
      {aba === "carteiras" && <Carteiras />}
      {aba === "cotacao" && <Cotacao />}
      {aba === "consumo" && <ConsumoMargem />}
    </>
  );
}

// ---------------------------------------------------------------------------- carteiras
function Carteiras() {
  const { dados, erro, recarregar } = useCarregar<LinhaCarteira[]>("/admin/carteiras", [], { guardar: false }); // saldos e formulário do detalhe
  const planos = useCarregar<Plano[]>("/admin/planos");
  const [aberta, setAberta] = useState<LinhaCarteira | null>(null);
  if (!dados) return <Carregando erro={erro} />;
  if (dados.length === 0) return <div className="panel"><Vazio icone={<Wallet />}>Nenhum escritório.</Vazio></div>;
  return (
    <>
      <div className="lst"><table>
        <thead><tr><th>Escritório</th><th>Modo</th><th>Plano</th><th className="num">Saldo</th><th className="num">Bônus</th><th className="num">A debitar</th>
          <th className="num">Cobrado no mês</th><th className="num">Custo real</th><th className="num">Margem</th><th>Situação</th><th /></tr></thead>
        <tbody>{dados.map((c) => (
          <tr key={c.id_escritorio}>
            <td>{c.nome}{c.recargas_pendentes > 0 && <span className="chip warn" style={{ marginLeft: 6 }}>{c.recargas_pendentes} recarga(s)</span>}</td>
            <td><span className="chip">{c.modo === "pre_pago" ? "pré-pago" : "só registrar"}</span></td>
            <td>{c.plano ?? "—"}</td>
            <td className="num">{reais(c.saldo_brl)}</td>
            <td className="num">{reais(c.bonus_brl)}</td>
            <td className="num">{reais(c.pendente_brl)}</td>
            <td className="num">{reais(c.cobrado_brl)}</td>
            <td className="num" title={usd(c.custo_usd)}>{reais(c.custo_brl_real)}</td>
            <td className="num">{reais(c.cobrado_brl - c.custo_brl_real)}</td>
            <td>{c.pausado_por_saldo ? <span className="chip bad">IA pausada</span> : <span className="chip ok">ativa</span>}</td>
            <td><button className="btn" onClick={() => setAberta(c)}>Abrir</button></td>
          </tr>
        ))}</tbody>
      </table></div>
      {aberta && <CarteiraDetalhe linha={aberta} planos={planos.dados ?? []} aoFechar={() => { setAberta(null); recarregar(); }} />}
    </>
  );
}

function CarteiraDetalhe({ linha, planos, aoFechar }: { linha: LinhaCarteira; planos: Plano[]; aoFechar: () => void }) {
  const detalhe = useCarregar<any>(`/admin/carteiras/${linha.id_escritorio}`);
  const { ocupado, executar } = useAcao();
  const [confirmar, modalConfirmar] = useConfirmar();
  const [tipo, setTipo] = useState("bonus_manual");
  const [valor, setValor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [plano, setPlano] = useState(linha.id_plano ?? "");
  const [markup, setMarkup] = useState(linha.markup ? String(Math.round((linha.markup - 1) * 10000) / 100) : "");
  const d = detalhe.dados;
  const lancar = () => executar(async () => {
    await enviar(`/admin/carteiras/${linha.id_escritorio}/lancamentos`, { tipo, valor_brl: Number(valor.replace(",", ".")), motivo: motivo.trim() });
    setValor(""); setMotivo(""); detalhe.recarregar();
  }, "Lançado no livro.");
  const alterar = (corpo: Record<string, unknown>, aviso: string) => executar(async () => {
    await enviar(`/admin/carteiras/${linha.id_escritorio}`, corpo, "PATCH"); detalhe.recarregar();
  }, aviso);
  const ligarPrePago = async () => {
    const negativo = (d?.saldo_brl ?? 0) < 0;
    const perdoar = negativo && await confirmar({ titulo: "Saldo negativo do período só registrar",
      texto: `O escritório consumiu ${reais(-(d?.saldo_brl ?? 0))} sem cobrança. Perdoar (ajuste no livro) antes de ligar o pré-pago?`,
      confirmar: "Perdoar e ligar", cancelar: "Ligar sem perdoar" });
    alterar({ modo: "pre_pago", perdoar_negativo: perdoar }, "Pré-pago ligado.");
  };
  return (
    <Modal titulo={`Carteira · ${linha.nome}`} aoFechar={aoFechar} largura={900}
      rodape={<><span className="sp" /><button className="btn" onClick={aoFechar}>Fechar</button></>}>
      {modalConfirmar}
      {!d ? <Carregando erro={detalhe.erro} /> : (
        <div className="stack">
          {Math.abs(d.conferencia?.diferenca ?? 0) > 0.000001 && <Alerta tipo="bad">Carteira diferente da soma do livro: {d.conferencia.diferenca}</Alerta>}
          <div className="grid2" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            <div><span className="lbl">Disponível</span><b>{reais(d.disponivel_brl)}</b></div>
            <div><span className="lbl">Saldo</span><b>{reais(d.saldo_brl)}</b></div>
            <div><span className="lbl">Bônus do mês</span><b>{reais(d.bonus_brl)}</b> <span className="ajuda">de {reais(d.bonus_do_mes_brl)}</span></div>
            <div><span className="lbl">Modo</span><b>{d.modo === "pre_pago" ? "pré-pago" : "só registrar"}</b>{d.pausado_por_saldo && <span className="chip bad" style={{ marginLeft: 6 }}>pausada</span>}</div>
          </div>
          <Painel titulo="Plano, modo e markup">
            <div className="form">
              <div className="grid2">
                <label className="field"><span className="lbl">Plano</span>
                  <div style={{ display: "flex", gap: 8 }}>
                    <select value={plano} onChange={(e) => setPlano(e.target.value)}>
                      <option value="">Sem plano</option>
                      {planos.filter((p) => p.ativo || p.id === plano).map((p) => <option key={p.id} value={p.id}>{p.nome} · {reais(p.preco_mensal_brl)} · bônus {reais(p.bonus_mensal_brl)}</option>)}
                    </select>
                    <button className="btn" disabled={ocupado || plano === (linha.id_plano ?? "")} onClick={() => alterar(plano ? { id_plano: plano } : { tirar_plano: true }, "Plano salvo.")}><Save />Salvar</button>
                  </div>
                  <span className="ajuda">Ao escolher um plano, o bônus do mês entra na hora (se ainda não entrou neste mês).</span>
                </label>
                <label className="field"><span className="lbl">Markup só deste escritório (% sobre o custo)</span>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input inputMode="decimal" value={markup} onChange={(e) => setMarkup(e.target.value)} placeholder="vazio = markup global" />
                    <button className="btn" disabled={ocupado} onClick={() => alterar(markup.trim() ? { markup_percentual: Number(markup.replace(",", ".")) } : { usar_markup_global: true }, "Markup salvo.")}><Save />Salvar</button>
                  </div>
                </label>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {d.modo !== "pre_pago"
                  ? <button className="btn pri" disabled={ocupado} onClick={ligarPrePago}>Ligar pré-pago (pausa sem saldo)</button>
                  : <button className="btn" disabled={ocupado} onClick={() => alterar({ modo: "so_registrar" }, "Voltou para só registrar.")}>Voltar para só registrar</button>}
              </div>
            </div>
          </Painel>
          <Painel titulo="Lançar crédito, bônus ou ajuste">
            <div className="form">
              <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr 2fr auto" }}>
                <select value={tipo} onChange={(e) => setTipo(e.target.value)} aria-label="Tipo">
                  <option value="bonus_manual">Bônus LawChat</option><option value="recarga">Crédito de recarga (pago por fora)</option><option value="ajuste">Ajuste (+ ou −)</option>
                </select>
                <input inputMode="decimal" value={valor} onChange={(e) => setValor(e.target.value)} placeholder="Valor em R$" aria-label="Valor" />
                <input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Motivo (obrigatório)" aria-label="Motivo" />
                <button className="btn pri" disabled={ocupado || !Number(valor.replace(",", ".")) || motivo.trim().length < 3} onClick={lancar}><Plus />Lançar</button>
              </div>
              <span className="ajuda">Bônus LawChat e crédito entram no saldo e não expiram. O bônus do plano é mensal e fica separado.</span>
            </div>
          </Painel>
          <Painel titulo="Livro (extrato completo)"><Extrato movimentos={d.extrato as Movimento[]} admin /></Painel>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------- recargas
function Recargas() {
  const [situacao, setSituacao] = useState("pendente");
  const { dados, erro, recarregar } = useCarregar<RecargaAdmin[]>(`/admin/recargas${situacao ? `?situacao=${situacao}` : ""}`, [situacao]);
  const { ocupado, executar } = useAcao();
  const [confirmar, modal] = useConfirmar();
  const confirmarPagamento = async (r: RecargaAdmin) => {
    if (!await confirmar({ titulo: "Confirmar pagamento", texto: `Creditar ${reais(r.valor_brl)} para ${r.escritorio}? Confira se o valor caiu na conta.`, confirmar: "Confirmar e creditar" })) return;
    executar(async () => { await enviar(`/admin/recargas/${r.id}/confirmar`, {}); recarregar(); }, "Recarga creditada.");
  };
  return (
    <>
      {modal}
      <Painel titulo={<>Pedidos de recarga{dados ? <span className="muted" style={{ fontWeight: 400 }}> · {dados.length}</span> : null}</>}
        acoes={<div className="seg" role="radiogroup" aria-label="Situação">
          {[["pendente", "Pendentes"], ["paga", "Pagas"], ["", "Todas"]].map(([v, n]) => <button key={v} role="radio" aria-checked={situacao === v} className={situacao === v ? "on" : ""} onClick={() => setSituacao(v)}>{n}</button>)}
        </div>}>
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? (
        <Vazio icone={<Wallet />}>{situacao === "pendente" ? "Nenhum pedido esperando pagamento." : situacao === "paga" ? "Nenhuma recarga paga ainda." : "Nenhuma recarga ainda."}
          <br /><span className="muted" style={{ fontSize: 12 }}>Os escritórios pedem recarga em Créditos › Pedir recarga.</span></Vazio>
      ) : (
        <div className="lst"><table>
          <thead><tr><th>Pedido em</th><th>Escritório</th><th className="num">Valor</th><th>Situação</th><th>Gateway</th><th>Quem pediu</th><th>Obs.</th><th /></tr></thead>
          <tbody>{dados.map((r) => (
            <tr key={r.id}>
              <td className="s num">{quando(r.criado_em)}</td><td>{r.escritorio}</td><td className="num">{reais(r.valor_brl)}</td>
              <td><span className={`chip ${r.situacao === "paga" ? "ok" : r.situacao === "pendente" ? "warn" : ""}`}>{r.situacao}</span>{r.confirmada_por && <span className="ajuda"> · {r.confirmada_por}</span>}</td>
              <td>{r.gateway}</td><td>{r.pedido_por ?? "—"}</td><td className="s">{r.observacao ?? ""}</td>
              <td style={{ whiteSpace: "nowrap" }}>{r.situacao === "pendente" && <>
                <button className="btn pri" disabled={ocupado} onClick={() => confirmarPagamento(r)}><Check />Confirmar pagamento</button>{" "}
                <button className="btn" disabled={ocupado} onClick={() => executar(async () => { await enviar(`/admin/recargas/${r.id}/cancelar`, {}); recarregar(); }, "Recarga cancelada.")}><X />Cancelar</button>
              </>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      </Painel>
    </>
  );
}

// ---------------------------------------------------------------------------- planos
function Planos() {
  const { dados, erro, recarregar } = useCarregar<Plano[]>("/admin/planos");
  const [editar, setEditar] = useState<Partial<Plano> | null>(null);
  return (
    <>
      <div style={{ marginBottom: 12 }}><button className="btn pri" onClick={() => setEditar({ codigo: "", nome: "", preco_mensal_brl: 0, bonus_mensal_brl: 0, bonus_acumula: false, ativo: true, ordem: 0 })}><Plus />Novo plano</button></div>
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? <div className="panel"><Vazio>Nenhum plano. Crie o primeiro.</Vazio></div> : (
        <div className="lst"><table>
          <thead><tr><th>Plano</th><th className="num">Preço mensal</th><th className="num">Bônus mensal</th><th>Sobra do bônus</th><th className="num">Escritórios</th><th>Situação</th><th /></tr></thead>
          <tbody>{dados.map((p) => (
            <tr key={p.id}><td>{p.nome} <span className="ajuda">{p.codigo}</span></td><td className="num">{reais(p.preco_mensal_brl)}</td><td className="num">{reais(p.bonus_mensal_brl)}</td>
              <td>{p.bonus_acumula ? "acumula" : "expira no fim do mês"}</td><td className="num">{p.escritorios}</td>
              <td><span className={`chip ${p.ativo ? "ok" : ""}`}>{p.ativo ? "ativo" : "inativo"}</span></td>
              <td><button className="btn" onClick={() => setEditar(p)}>Editar</button></td></tr>
          ))}</tbody>
        </table></div>
      )}
      {editar && <EditarPlano plano={editar} aoFechar={() => { setEditar(null); recarregar(); }} />}
    </>
  );
}

function EditarPlano({ plano, aoFechar }: { plano: Partial<Plano>; aoFechar: () => void }) {
  const { ocupado, executar } = useAcao();
  const [p, setP] = useState<Partial<Plano>>(plano);
  const novo = !plano.id;
  const salvar = () => executar(async () => {
    const corpo = { nome: p.nome, descricao: p.descricao ?? null, preco_mensal_brl: Number(p.preco_mensal_brl), bonus_mensal_brl: Number(p.bonus_mensal_brl),
      bonus_acumula: Boolean(p.bonus_acumula), ativo: Boolean(p.ativo), ordem: Number(p.ordem ?? 0) };
    if (novo) await enviar("/admin/planos", { ...corpo, codigo: p.codigo });
    else await enviar(`/admin/planos/${plano.id}`, corpo, "PATCH");
    aoFechar();
  }, "Plano salvo.");
  return (
    <Modal titulo={novo ? "Novo plano" : `Plano ${plano.nome}`} aoFechar={aoFechar}
      texto="O bônus mensal é renovado todo mês. Mudança de bônus vale a partir do próximo mês."
      rodape={<><span className="sp" /><button className="btn" onClick={aoFechar}>Cancelar</button><button className="btn pri" disabled={ocupado || !p.nome || (novo && !p.codigo)} onClick={salvar}><Save />Salvar</button></>}>
      <div className="form">
        <div className="grid2">
          <label className="field"><span className="lbl">Código</span><input value={p.codigo ?? ""} disabled={!novo} onChange={(e) => setP({ ...p, codigo: e.target.value.toLowerCase() })} placeholder="basico" /></label>
          <label className="field"><span className="lbl">Nome</span><input value={p.nome ?? ""} onChange={(e) => setP({ ...p, nome: e.target.value })} /></label>
          <label className="field"><span className="lbl">Preço mensal (R$)</span><input inputMode="decimal" value={String(p.preco_mensal_brl ?? 0)} onChange={(e) => setP({ ...p, preco_mensal_brl: Number(e.target.value.replace(",", ".")) || 0 })} /></label>
          <label className="field"><span className="lbl">Bônus mensal de IA (R$)</span><input inputMode="decimal" value={String(p.bonus_mensal_brl ?? 0)} onChange={(e) => setP({ ...p, bonus_mensal_brl: Number(e.target.value.replace(",", ".")) || 0 })} /></label>
        </div>
        <label className="field"><span className="lbl">Descrição</span><input value={p.descricao ?? ""} onChange={(e) => setP({ ...p, descricao: e.target.value })} /></label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}><input type="checkbox" checked={Boolean(p.bonus_acumula)} onChange={(e) => setP({ ...p, bonus_acumula: e.target.checked })} />O bônus que sobra passa para o mês seguinte (acumula)</label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}><input type="checkbox" checked={Boolean(p.ativo)} onChange={(e) => setP({ ...p, ativo: e.target.checked })} />Ativo (pode ser escolhido)</label>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------- cotação e markup
function Cotacao() {
  const { dados, erro, recarregar } = useCarregar<Config>("/admin/cobranca/config");
  const { ocupado, executar } = useAcao();
  const [cotacao, setCotacao] = useState("");
  const [percentual, setPercentual] = useState("");
  const [motivo, setMotivo] = useState("");
  if (!dados) return <Carregando erro={erro} />;
  const v = dados.vigente;
  const c = Number((cotacao || String(v.cotacao_usd_brl)).replace(",", "."));
  const m = 1 + Number((percentual || String(v.markup_percentual)).replace(",", ".")) / 100;
  return (
    <div className="stack">
      <Painel titulo="Valendo agora">
        <p>R$ {v.cotacao_usd_brl.toFixed(4)} por US$ · markup {v.markup.toFixed(4)}x ({v.markup_percentual}% sobre o custo){v.vigente_desde && <span className="ajuda"> · desde {quando(v.vigente_desde)}</span>}</p>
        <p className="ajuda">Exemplo: uma chamada de US$ 0,0100 custa R$ {(0.01 * v.cotacao_usd_brl).toFixed(4)} e é cobrada R$ {(0.01 * v.cotacao_usd_brl * v.markup).toFixed(4)}.</p>
      </Painel>
      <Painel titulo="Mudar">
        <div className="form">
          <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr 2fr" }}>
            <label className="field"><span className="lbl">Cotação (R$ por US$)</span><input inputMode="decimal" value={cotacao} placeholder={String(v.cotacao_usd_brl)} onChange={(e) => setCotacao(e.target.value)} /></label>
            <label className="field"><span className="lbl">Markup (% sobre o custo)</span><input inputMode="decimal" value={percentual} placeholder={String(v.markup_percentual)} onChange={(e) => setPercentual(e.target.value)} /></label>
            <label className="field"><span className="lbl">Motivo</span><input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Ex.: dólar subiu" /></label>
          </div>
          <span className="ajuda">Prévia: US$ 0,0100 → R$ {(0.01 * c).toFixed(4)} de custo → R$ {(0.01 * c * m).toFixed(4)} cobrado. Vale para as chamadas de agora em diante; as já gravadas guardam a cotação e o markup delas.</span>
          <button className="btn pri" style={{ alignSelf: "flex-start" }} disabled={ocupado || !(c > 0) || !(m > 0)}
            onClick={() => executar(async () => { await enviar("/admin/cobranca/config", { cotacao_usd_brl: c, markup_percentual: Number((percentual || String(v.markup_percentual)).replace(",", ".")), motivo: motivo || null }); setCotacao(""); setPercentual(""); setMotivo(""); recarregar(); }, "Cotação e markup salvos.")}><Save />Salvar</button>
        </div>
      </Painel>
      <Painel titulo="Histórico">
        <div className="lst"><table>
          <thead><tr><th>Desde</th><th className="num">Cotação</th><th className="num">Markup</th><th>Motivo</th><th>Quem</th></tr></thead>
          <tbody>{dados.historico.map((h) => <tr key={h.id}><td className="s num">{quando(h.vigente_desde)}</td><td className="num">{h.cotacao_usd_brl.toFixed(4)}</td><td className="num">{h.markup.toFixed(4)}x</td><td>{h.motivo ?? ""}</td><td>{h.usuario ?? "sistema"}</td></tr>)}</tbody>
        </table></div>
      </Painel>
    </div>
  );
}

// ---------------------------------------------------------------------------- consumo e margem
function ConsumoMargem() {
  const [dias, setDias] = useState(30);
  const { dados, erro } = useCarregar<ConsumoAdmin>(`/admin/cobranca/consumo?dias=${dias}`, [dias]);
  return (
    <div className="stack">
      <div className="seg" role="radiogroup" aria-label="Período">
        {[7, 30, 90].map((d) => <button key={d} role="radio" aria-checked={dias === d} className={dias === d ? "on" : ""} onClick={() => setDias(d)}>{d} dias</button>)}
      </div>
      {!dados ? <Carregando erro={erro} /> : <>
        {dados.chamadas_sem_preco > 0 && <Alerta tipo="warn">{dados.chamadas_sem_preco} chamada(s) com tokens e custo zero: modelo fora da tabela de preços (app/modelo.py). Essas não foram cobradas.</Alerta>}
        <Painel titulo={`Total em ${dias} dias`}>
          <p>Custo real {usd(dados.total.custo_usd)} = {reais(dados.total.custo_brl_real)} · cobrado {reais(dados.total.cobrado_brl)} · margem <b>{reais(dados.total.margem_brl)}</b></p>
        </Painel>
        <Painel titulo="Por escritório"><TabelaSoma linhas={dados.por_escritorio.map((l) => ({ ...l, rotulo: l.nome }))} /></Painel>
        <Painel titulo="Por modelo"><TabelaSoma linhas={dados.por_modelo.map((l) => ({ ...l, rotulo: l.modelo + (l.sem_preco ? ` (${l.sem_preco} sem preço)` : "") }))} /></Painel>
      </>}
    </div>
  );
}

function TabelaSoma({ linhas }: { linhas: (Soma & { rotulo: string })[] }) {
  if (linhas.length === 0) return <Vazio>Sem consumo no período.</Vazio>;
  return (
    <div className="lst"><table>
      <thead><tr><th /><th className="num">Chamadas</th><th className="num">Tokens</th><th className="num">Custo US$</th><th className="num">Custo R$</th><th className="num">Cobrado</th><th className="num">Margem</th></tr></thead>
      <tbody>{linhas.map((l) => (
        <tr key={l.rotulo}><td>{l.rotulo}</td><td className="num">{l.chamadas}</td><td className="num">{(l.tokens ?? 0).toLocaleString("pt-BR")}</td><td className="num">{usd(l.custo_usd)}</td>
          <td className="num">{reais(l.custo_brl_real)}</td><td className="num">{reais(l.cobrado_brl)}</td><td className="num">{reais(l.margem_brl)}</td></tr>
      ))}</tbody>
    </table></div>
  );
}
