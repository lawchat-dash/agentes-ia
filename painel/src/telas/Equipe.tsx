import { useState } from "react";
import { KeyRound, Plus, Users } from "lucide-react";
import { NOME_PAPEL, enviar, quando, type Papel } from "../api";
import { Alerta, Cabecalho, Carregando, Iniciais, Modal, SenhaProvisoria, Situacao, Vazio, useAcao, useCarregar, useConfirmar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface Membro {
  id: string; email: string; nome: string; papel: Papel; ativo: boolean; trocar_senha: boolean;
  ultimo_acesso_em: string | null; criado_em: string; escritorios: number;
}

/** Quem é da LawChat. Todo mundo da equipe vê; só o dono adiciona, muda papel e desativa. */
export function TelaEquipe() {
  const { eu, dono } = useSessao();
  const { dados, erro, recarregar } = useCarregar<Membro[]>("/admin/equipe");
  const { ocupado, executar } = useAcao();
  const [novo, setNovo] = useState(false);
  const [senha, setSenha] = useState<{ nome: string; senha: string } | null>(null);
  const [confirmar, janelaConfirmar] = useConfirmar();

  const alterar = (m: Membro, corpo: Partial<Pick<Membro, "papel" | "ativo">>, aviso: string) =>
    executar(async () => { await enviar(`/admin/equipe/${m.id}`, corpo, "PATCH"); recarregar(); }, aviso);
  const novaSenha = async (m: Membro) => {
    const sim = await confirmar({
      titulo: `Gerar nova senha para ${m.nome}?`, confirmar: "Gerar senha", perigo: true,
      texto: <>A senha atual de <b>{m.nome}</b> deixa de valer na hora. A nova é provisória: aparece uma vez só e a pessoa troca no primeiro acesso.</>,
    });
    if (!sim) return;
    executar(async () => {
      const r = await enviar<{ senha_provisoria: string }>(`/admin/equipe/${m.id}/senha`, {});
      setSenha({ nome: m.nome, senha: r.senha_provisoria });
    });
  };
  const alternarAcesso = async (m: Membro) => {
    if (m.ativo && !(await confirmar({
      titulo: `Desativar o acesso de ${m.nome}?`, confirmar: "Desativar", perigo: true,
      texto: <><b>{m.nome}</b> não entra mais no painel nem nos escritórios. Dá para reativar depois.</>,
    }))) return;
    alterar(m, { ativo: !m.ativo }, m.ativo ? "Acesso desativado." : "Acesso reativado.");
  };

  return (
    <>
      <Cabecalho eyebrow="LawChat" titulo="Equipe LawChat"
        texto="Quem é nosso: o dono cuida da equipe; a equipe atende e edita os escritórios. Cliente nunca aparece aqui."
        acoes={dono ? <button className="btn pri" onClick={() => setNovo(true)}><Plus />Adicionar pessoa</button> : undefined} />
      {!dono && <><Alerta tipo="info">Só o dono da LawChat adiciona pessoas, muda papel ou desativa.</Alerta><div style={{ height: 14 }} /></>}
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? <div className="panel"><Vazio icone={<Users />}>Ninguém ainda.</Vazio></div> : (
        <div className="lst"><table>
          <thead><tr><th>Pessoa</th><th>Papel</th><th>Escritórios</th><th>Último acesso</th><th>Situação</th>{dono && <th />}</tr></thead>
          <tbody>{dados.map((m) => {
            const eu_mesmo = m.id === eu?.id;
            return (
              <tr key={m.id} style={{ opacity: m.ativo ? 1 : 0.6 }}>
                <td><div style={{ display: "flex", gap: 10, alignItems: "center" }}><Iniciais nome={m.nome} />
                  <div><div className="t">{m.nome}{eu_mesmo && <span className="chip" style={{ marginLeft: 6 }}>você</span>}</div><div className="s">{m.email}</div></div></div></td>
                <td>{dono && !eu_mesmo ? (
                  <select className="inp" aria-label={`Papel de ${m.nome}`} value={m.papel} disabled={ocupado}
                    onChange={(e) => alterar(m, { papel: e.target.value as Papel }, "Papel alterado.")}>
                    <option value="dono_lawchat">Dono</option>
                    <option value="admin_lawchat">Equipe</option>
                  </select>
                ) : <span className={`chip ${m.papel === "dono_lawchat" ? "ac" : ""}`}>{NOME_PAPEL[m.papel]}</span>}</td>
                <td className="num">{m.escritorios}</td>
                <td className="s num">{m.ultimo_acesso_em ? quando(m.ultimo_acesso_em) : "nunca entrou"}</td>
                <td><Situacao valor={m.ativo ? "ativo" : "encerrado"} texto={m.ativo ? (m.trocar_senha ? "senha provisória" : "ativo") : "desativado"} /></td>
                {dono && <td style={{ whiteSpace: "nowrap" }}>
                  {!eu_mesmo && <button className="btn sm" disabled={ocupado} onClick={() => alternarAcesso(m)}>{m.ativo ? "Desativar" : "Reativar"}</button>}
                  {" "}<button className="btn sm ghost" disabled={ocupado || !m.ativo} onClick={() => novaSenha(m)} title="Gerar senha provisória"><KeyRound />Senha</button>
                </td>}
              </tr>
            );
          })}</tbody>
        </table></div>
      )}
      {janelaConfirmar}
      {novo && <NovoMembro aoFechar={() => setNovo(false)} aoCriar={recarregar} />}
      {senha && (
        <Modal titulo="Nova senha gerada" aoFechar={() => setSenha(null)} rodape={<><span className="sp" /><button className="btn pri" onClick={() => setSenha(null)}>Pronto</button></>}>
          <SenhaProvisoria para={senha.nome} senha={senha.senha} />
        </Modal>
      )}
    </>
  );
}

function NovoMembro({ aoFechar, aoCriar }: { aoFechar: () => void; aoCriar: () => void }) {
  const { ocupado, executar } = useAcao();
  const [form, setForm] = useState({ nome: "", email: "", papel: "admin_lawchat" as Papel });
  const [senha, setSenha] = useState<string | null>(null);
  const criar = () => executar(async () => {
    const r = await enviar<{ senha_provisoria: string }>("/admin/equipe", form);
    setSenha(r.senha_provisoria); aoCriar();
  }, "Pessoa adicionada.");
  return (
    <Modal titulo="Adicionar à equipe LawChat" texto="Para quem é da LawChat. Clientes entram pela Helena ou pelo gestor do escritório." aoFechar={aoFechar}
      rodape={senha ? <><span className="sp" /><button className="btn pri" onClick={aoFechar}>Pronto</button></> : <>
        <span className="sp" /><button className="btn" onClick={aoFechar}>Cancelar</button>
        <button className="btn pri" disabled={ocupado || form.nome.trim().length < 2 || !form.email.includes("@")} onClick={criar}>Adicionar</button></>}>
      {senha ? <SenhaProvisoria para={form.nome.trim()} senha={senha} /> : (
        <div className="form">
          <div className="form cols">
            <label className="field"><span className="lbl">Nome</span><input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></label>
            <label className="field"><span className="lbl">E-mail</span><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          </div>
          <label className="field"><span className="lbl">Papel</span>
            <select value={form.papel} onChange={(e) => setForm({ ...form, papel: e.target.value as Papel })}>
              <option value="admin_lawchat">Equipe: atende e edita os escritórios</option>
              <option value="dono_lawchat">Dono: tudo, inclusive a equipe</option>
            </select></label>
        </div>
      )}
    </Modal>
  );
}
