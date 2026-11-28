import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Check, ExternalLink, Eye, EyeOff, Loader2, RefreshCw, Search, Copy,
  FileSignature, Bot, Settings2, Sparkles, FileText, PenLine, CheckCircle2, ShieldCheck, ChevronRight, Plus, X,
} from "lucide-react";
import { toast } from "sonner";
import { useZapsign, useZapsignAccount, useProdutoContrato, ZapsignConfig, ZapsignModel } from "@/hooks/useZapsign";
import zapsignLogo from "@/assets/zapsign-logo.png";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  value: ZapsignConfig;
  /** Persiste a config no rascunho (parent chama persistGroupField). */
  onSave: (next: ZapsignConfig) => Promise<void> | void;
  saving?: boolean;
  /** id do produto ativado (sistemaia_produtos_ativados.id) — âncora do contrato. */
  produtoId?: string;
}

/**
 * Diálogo de integração ZapSign — modelado no padrão LiderHub.
 * Aba 1 "Sincronizar modelos": conecta por token, lista os modelos importados
 * (com suas variáveis {{ }}) e deixa marcar o modelo padrão do contrato.
 * Abas 2/3 (Configurar Agentes / Pós assinatura): em breve.
 */
export function ZapsignDialog({ open, onOpenChange, value, onSave, saving, produtoId }: Props) {
  const { syncing, sincronizarModelos, registrarWebhook, removerWebhook } = useZapsign();
  // Token vive no ESCRITÓRIO (cofre do servidor) — salvo 1x, reusado em todo produto.
  const { token: accountToken, temToken, finalSegredo, config: accountConfig, savingToken, reload: reloadAccount } = useZapsignAccount();
  // Vínculo Produto ↔ Modelo de Contrato (âncora p/ ligar ao agente depois).
  const { row: contrato, padrao: contratoPadrao, salvar: salvarContrato } = useProdutoContrato(produtoId);
  const connected = !!value.enabled;
  const [committing, setCommitting] = useState(false);

  // Rascunho local do token (semeado pelo token da conta; persiste ao Conectar).
  const [token, setToken] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busca, setBusca] = useState("");
  const [tab, setTab] = useState("modelos");

  // Estado de TRABALHO local (nada é gravado até o "Concluir" final).
  const [selModel, setSelModel] = useState<string | undefined>(undefined);
  const [excluidas, setExcluidas] = useState<Set<string>>(new Set());
  // Aviso de assinatura é OBRIGATÓRIO para o contrato: sem ele o lead não avança sozinho, não sai resumo e os lembretes
  // não param. Sempre criado no "Concluir e salvar" (reusa o da conta se já existir).
  const posAtivo = true;

  // A aba e a busca só voltam ao começo quando o pop-up ABRE. Antes voltavam também quando o aviso de assinatura era
  // criado no "Concluir e salvar" (o webhook_id muda): o pop-up pulava para a 1ª aba antes de fechar.
  const estavaAberto = useRef(false);
  useEffect(() => {
    if (open && !estavaAberto.current) {
      setReveal(false);
      setBusca("");
      setTab("modelos");
    }
    estavaAberto.current = open;
  }, [open]);

  useEffect(() => {
    if (open && !committing) {
      setToken(accountToken ?? "");
      // O modelo salvo DESTE produto vem primeiro; sem ele, o último escolhido no rascunho.
      setSelModel(contrato?.modelo_token ?? value.template_id ?? (value.templates ?? [])[0]?.id);
      setExcluidas(new Set(Object.entries(contrato?.mapeamento ?? {}).filter(([, v]) => (v as any)?.origem === "ignorado").map(([k]) => k)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, accountToken, contrato?.id, value.template_id, accountConfig.webhook_id]);

  const toggleExcluir = (variable: string) => setExcluidas((s) => {
    const n = new Set(s); n.has(variable) ? n.delete(variable) : n.add(variable); return n;
  });

  // Revalida os modelos ao ABRIR (1x), p/ nunca mostrar cache velho.
  const autoRef = useRef(false);
  useEffect(() => {
    if (!open) { autoRef.current = false; return; }
    if (open && value.enabled && (temToken || accountToken || token) && !autoRef.current) {
      autoRef.current = true;
      void sincronizar(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, value.enabled, accountToken, temToken]);

  const modelos = value.templates ?? [];
  const filtrados = useMemo(() => {
    const q = busca.trim().toLowerCase();
    if (!q) return modelos;
    return modelos.filter(
      // Nome, ID do modelo (o token da ZapSign, copiado pelo ícone) ou variável.
      (m) => m.name.toLowerCase().includes(q) || String(m.id ?? "").toLowerCase().includes(q)
        || m.variables.some((v) => v.toLowerCase().includes(q)),
    );
  }, [modelos, busca]);

  /**
   * Sincroniza os modelos. silent=true (auto ao abrir) não toasta nem regrava o
   * token. Sempre corrige o modelo padrão se o anterior sumiu da lista.
   */
  const sincronizar = async (silent = false) => {
    const tk = (token || accountToken).trim();
    if (!tk && !temToken) { if (!silent) toast.error("Informe o token de API."); return; }
    // Token digitado → o servidor guarda no cofre e testa; sem token novo, usa o já salvo.
    const { models, error } = await sincronizarModelos(silent ? "" : tk);
    if (error) { if (!silent) toast.error(error); return; }
    if (!silent && tk) { setToken(""); await reloadAccount(); }
    const lista = models ?? [];
    const aindaExiste = lista.some((m) => m.id === value.template_id);
    const template_id = aindaExiste ? value.template_id : lista[0]?.id;
    // No auto-refresh silencioso, só grava se algo mudou (evita toast/escrita à toa).
    const igual = aindaExiste
      && JSON.stringify(lista) === JSON.stringify(value.templates ?? [])
      && template_id === value.template_id;
    if (silent && igual) return;
    await onSave({ enabled: true, templates: lista, template_id, synced_at: new Date().toISOString() });
    if (!silent) toast.success(`${lista.length} ${lista.length === 1 ? "modelo sincronizado" : "modelos sincronizados"}`);
  };
  const conectarOuAtualizar = () => sincronizar(false);

  const desconectar = async () => {
    // Só desliga a ZapSign NESTE produto. O token é da conta do escritório e vale para todos os produtos:
    // apagá-lo aqui desligava o contrato de todos (o mesmo defeito do sistema antigo). Trocar ou remover o
    // token da conta fica na tela de Integrações.
    await onSave({ enabled: false });
    onOpenChange(false);
  };

  const modeloSel = (value.templates ?? []).find((m) => m.id === selModel);

  /**
   * SALVAR ÚNICO — grava tudo de uma vez no fim do fluxo (Aba 1→2→3 só montam o
   * estado local). Persiste: modelo escolhido, mapeamento (com exclusões),
   * webhook de pós-assinatura e o rascunho do produto.
   */
  const concluir = async () => {
    if (!modeloSel) { toast.error("Escolha um modelo na aba “Sincronizar modelos”."); setTab("modelos"); return; }
    setCommitting(true);
    try {
      const vars = (modeloSel.inputs && modeloSel.inputs.length)
        ? modeloSel.inputs
        : modeloSel.variables.map((v) => ({ variable: `{{${v}}}`, label: v, type: "input", required: true }));
      const mapeamento = Object.fromEntries(vars.map((i) => {
        if (excluidas.has(i.variable)) return [i.variable, { origem: "ignorado" }];
        const campo = campoNoSistema(i.label);
        return [i.variable, campo ? { origem: "sistema", campo } : { origem: "ia" }];
      }));

      // Pós-assinatura: registra o webhook da conta 1x (reusa se já existe).
      let webhookId = accountConfig.webhook_id ?? null;
      if (posAtivo && !webhookId) {
        const { webhook_id, error } = await registrarWebhook(token, selModel!);
        // Não trava o resto: o contrato salva e o Início avisa até o aviso de assinatura ficar conectado.
        if (error) toast.warning(`Contrato salvo, mas o aviso de assinatura não foi conectado: ${error}`);
        webhookId = webhook_id ?? null;
        await reloadAccount();
      }

      // 1) rascunho do produto
      await onSave({ enabled: true, template_id: selModel, templates: value.templates, pos_assinatura: posAtivo ? { etapa: "concluido" } : undefined });
      // 2) vínculo produto↔contrato (o n8n lê daqui)
      if (produtoId) {
        const { error: errContrato } = await salvarContrato({ modelo_token: modeloSel.id, modelo_nome: modeloSel.name, variaveis: vars, mapeamento, webhook_id: posAtivo ? webhookId : null });
        if (errContrato) { toast.error(errContrato); return; }
      }
      toast.success("ZapSign configurado");
      onOpenChange(false);
    } finally {
      setCommitting(false);
    }
  };

  const busy = !!saving || syncing || savingToken;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto p-0">
        <div className="p-6 space-y-5">
          {/* Cabeçalho */}
          <DialogHeader className="space-y-0">
            <DialogTitle className="flex items-center gap-3">
              <img src={zapsignLogo} alt="ZapSign" className="size-11 rounded-xl object-contain shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-lg font-bold">ZapSign</span>
                  {connected ? (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-success/15 text-success border border-success/30 inline-flex items-center gap-1"><Check className="size-2.5" strokeWidth={3} />Conectado</span>
                  ) : (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#f1f5f9] text-[#64748b]">Não conectado</span>
                  )}
                </div>
                <div className="text-xs text-muted-foreground font-normal mt-0.5">
                  Contratos personalizados e recebe assinaturas automaticamente
                </div>
              </div>
            </DialogTitle>
          </DialogHeader>

          {!connected ? (
            /* ---------- Estado: não conectado (formulário de conexão) ---------- */
            <ConnectForm
              token={token}
              setToken={setToken}
              onConnect={conectarOuAtualizar}
              busy={busy}
              contaConectada={temToken}
              finalSegredo={finalSegredo}
            />
          ) : (
            /* ---------- Estado: conectado (3 abas) ---------- */
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList className="grid w-full grid-cols-3 bg-[#eef1f5] p-1 h-auto">
                <TabsTrigger value="modelos" className="text-xs gap-1.5 text-[#667085] data-[state=active]:bg-white data-[state=active]:text-[#101828] data-[state=active]:shadow-sm data-[state=active]:font-semibold"><RefreshCw className="size-3.5" />Sincronizar modelos</TabsTrigger>
                <TabsTrigger value="agentes" className="text-xs gap-1.5 text-[#667085] data-[state=active]:bg-white data-[state=active]:text-[#101828] data-[state=active]:shadow-sm data-[state=active]:font-semibold"><Bot className="size-3.5" />Configurar Agentes</TabsTrigger>
                <TabsTrigger value="pos" className="text-xs gap-1.5 text-[#667085] data-[state=active]:bg-white data-[state=active]:text-[#101828] data-[state=active]:shadow-sm data-[state=active]:font-semibold"><Settings2 className="size-3.5" />Verificar assinatura</TabsTrigger>
              </TabsList>

              {/* ===== Aba 1: Sincronizar modelos ===== */}
              <TabsContent value="modelos" className="mt-5 space-y-4">
                {/* Chave de API (somente leitura, com revelar) */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs font-semibold">Chave API</Label>
                    <a href="https://docs.zapsign.com.br/" target="_blank" rel="noopener noreferrer" className="text-[11px] font-semibold text-primary inline-flex items-center gap-1">
                      <ExternalLink className="size-3" />Ver tutorial
                    </a>
                  </div>
                  <div className="relative">
                    <Input value={token} onChange={(e) => setToken(e.target.value)} type={reveal ? "text" : "password"} className="pr-10" placeholder={finalSegredo ? `Salvo, termina em ${finalSegredo}` : undefined} />
                    <button type="button" onClick={() => setReveal((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                      {reveal ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                </div>

                {/* Modelos importados */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-bold text-[#101828]">Modelos importados</h3>
                    <Button size="sm" variant="outline" onClick={conectarOuAtualizar} disabled={busy} className="h-8">
                      {syncing ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="size-3.5 mr-1.5" />}
                      Atualizar
                    </Button>
                  </div>

                  <p className="text-[11px] text-[#667085] mb-1">Clique no modelo que o agente deste produto vai usar para gerar o contrato.</p>
                  <p className="text-[11px] text-amber-700 bg-amber-50 rounded-md px-2 py-1 mb-2">
                    A escolha vale só para este produto e só depois de <strong>Concluir e salvar</strong> (na última aba).
                    {contrato?.modelo_nome
                      ? <> Salvo agora: <strong>{contrato.modelo_nome}</strong>.</>
                      : contratoPadrao?.modelo_nome
                        ? <> Até lá, este produto usa o modelo padrão do escritório: <strong>{contratoPadrao.modelo_nome}</strong>.</>
                        : null}
                  </p>

                  <div className="relative mb-2">
                    <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <Input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar por nome, ID do modelo ou variável…" className="pl-9 h-9" />
                  </div>

                  {modelos.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-[#e5e8ee] bg-[#fafbfc] p-6 text-center">
                      <Sparkles className="size-5 mx-auto text-[#cbd5e1] mb-2" />
                      <p className="text-sm text-[#667085]">Nenhum modelo importado ainda.</p>
                      <p className="text-xs text-[#98A2B3] mt-0.5">Clique em <strong>Atualizar</strong> para buscar os modelos da sua conta ZapSign.</p>
                    </div>
                  ) : (
                    <div className="rounded-xl border border-[#eef1f5] overflow-hidden">
                      <div className="grid grid-cols-[1fr_1.3fr_auto] gap-2 px-3 py-2 bg-[#f8fafc] text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">
                        <span>Nome do modelo</span><span>Variáveis</span><span className="text-right">Usar</span>
                      </div>
                      <div className="divide-y divide-[#eef1f5] max-h-[300px] overflow-y-auto">
                        {filtrados.map((m) => (
                          <ModelRow
                            key={m.id}
                            model={m}
                            isDefault={selModel === m.id}
                            onSetDefault={() => setSelModel(m.id)}
                          />
                        ))}
                        {filtrados.length === 0 && (
                          <div className="px-3 py-6 text-center text-sm text-[#98A2B3]">Nenhum modelo encontrado para "{busca}".</div>
                        )}
                      </div>
                    </div>
                  )}

                  {modelos.length > 0 && (
                    <p className="text-[11px] text-[#98A2B3] mt-2">
                      {modelos.length} {modelos.length === 1 ? "modelo" : "modelos"} · marque o modelo que o agente vai usar para gerar o contrato.
                    </p>
                  )}
                </div>

                <div className="flex justify-between gap-2 pt-3 border-t border-border/60">
                  <Button variant="ghost" onClick={desconectar} disabled={busy || committing}>Desligar neste produto</Button>
                  <Button
                    onClick={() => setTab("agentes")}
                    disabled={!selModel}
                    className="bg-gradient-primary text-white shadow-glow"
                  >
                    Continuar<ChevronRight className="size-4 ml-1" />
                  </Button>
                </div>
              </TabsContent>

              {/* ===== Aba 2: Configurar Agentes (variáveis do contrato) ===== */}
              <TabsContent value="agentes" className="mt-5 space-y-4">
                {!modeloSel ? (
                  <EmBreve
                    icon={<Bot className="size-5" />}
                    titulo="Escolha um modelo primeiro"
                    texto="Volte em “Sincronizar modelos” e selecione o modelo. Aqui você confere as variáveis que a IA vai coletar."
                  />
                ) : (
                  <>
                    <Aba2Variaveis modelo={modeloSel} excluidas={excluidas} onToggleExcluir={toggleExcluir} onAtualizarModelo={() => setTab("modelos")} />
                    <div className="flex justify-between gap-2 pt-1">
                      <Button variant="ghost" onClick={() => setTab("modelos")}><ChevronRight className="size-4 mr-1 rotate-180" />Voltar</Button>
                      <Button onClick={() => setTab("pos")} className="bg-gradient-primary text-white shadow-glow">Continuar<ChevronRight className="size-4 ml-1" /></Button>
                    </div>
                  </>
                )}
              </TabsContent>

              {/* ===== Aba 3: Pós assinatura ===== */}
              <TabsContent value="pos" className="mt-5 space-y-4">
                <div>
                  <h3 className="text-sm font-bold text-[#101828]">Verificar assinatura do contrato</h3>
                  <p className="text-xs text-[#667085] mt-0.5 leading-relaxed">
                    Etapa obrigatória do contrato: assim que o cliente <strong>assina</strong>, a ZapSign avisa o agente
                    e o lead avança no funil sozinho. Não precisa fazer nada: criamos o aviso ao clicar em <strong>Concluir e salvar</strong>.
                  </p>
                </div>

                {/* Aviso de assinatura: obrigatório, sem chave de ligar/desligar. */}
                <div className="w-full rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
                  <div className="flex items-center gap-3">
                    <div className="size-8 rounded-lg grid place-items-center shrink-0 bg-emerald-100 text-emerald-600">
                      <CheckCircle2 className="size-[18px]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-[#101828]">Aviso de contrato assinado</div>
                      <div className="text-[11px] text-[#667085] mt-0.5">
                        {accountConfig.webhook_id ? "Já está criado na sua conta ZapSign e vale para este produto." : "Vamos criar na sua conta ZapSign ao concluir (uma vez só, vale para todos os produtos)."}
                      </div>
                    </div>
                    <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-md bg-emerald-100 text-emerald-700">
                      {accountConfig.webhook_id ? "Criado" : "Obrigatório"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-3 pt-3 border-t border-black/5 text-[11px] text-[#667085]">
                    <ShieldCheck className="size-3.5 text-emerald-600 shrink-0" />
                    Ao assinar → lead marcado como <strong>concluído</strong> e follow-up de pós-venda disparado.
                  </div>
                </div>

                <div className="flex justify-between gap-2 pt-1 border-t border-border/60">
                  <Button variant="ghost" onClick={() => setTab("agentes")}><ChevronRight className="size-4 mr-1 rotate-180" />Voltar</Button>
                  <Button onClick={concluir} disabled={committing || !selModel} className="bg-gradient-primary text-white shadow-glow">
                    {committing ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Check className="size-4 mr-1.5" />}
                    Concluir e salvar
                  </Button>
                </div>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Campos que o sistema/IA já sabe coletar (normalizado → rótulo amigável). */
const CAMPOS_SISTEMA: Record<string, string> = {
  nome: "Nome", "nome completo": "Nome", email: "E-mail", "e mail": "E-mail",
  telefone: "Telefone", celular: "Telefone", whatsapp: "Telefone", cpf: "CPF", rg: "RG",
  endereco: "Endereço", logradouro: "Endereço", numero: "Número", complemento: "Complemento",
  bairro: "Bairro", cidade: "Cidade", estado: "Estado", uf: "Estado", cep: "CEP",
  profissao: "Profissão", "estado civil": "Estado civil", nacionalidade: "Nacionalidade",
  data: "Data", "data assinatura": "Data", oab: "OAB",
};
const normaliza = (s: string) =>
  s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[{}]/g, "").replace(/[_-]+/g, " ").trim().toLowerCase();
const campoNoSistema = (label: string): string | null => CAMPOS_SISTEMA[normaliza(label)] ?? null;

/* ---------- Aba 2: variáveis do contrato (a IA coleta na conversa) ---------- */
type VarMap = Record<string, { origem: string; campo?: string }>;
function Aba2Variaveis({ modelo, excluidas, onToggleExcluir, onAtualizarModelo }: {
  modelo?: ZapsignModel;
  excluidas: Set<string>;
  onToggleExcluir: (variable: string) => void;
  onAtualizarModelo: () => void;
}) {
  const vars = (modelo?.inputs && modelo.inputs.length)
    ? modelo.inputs
    : (modelo?.variables ?? []).map((v) => ({ variable: `{{${v}}}`, label: v, type: "input", required: true }));
  const toggle = onToggleExcluir;
  if (!modelo) return null;

  const ativas = vars.filter((i) => !excluidas.has(i.variable));
  const noSistema = ativas.filter((i) => campoNoSistema(i.label)).length;
  const foraDoPadrao = ativas.filter((i) => !campoNoSistema(i.label)).length;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-bold text-[#101828]">Configurar Agentes</h3>
        <p className="text-xs text-[#667085] mt-0.5 leading-relaxed">
          O agente gera o contrato <strong>{modelo.name}</strong> e a IA coleta cada campo na conversa.
          Confira se as variáveis <strong>batem com o nosso padrão</strong>. As <strong className="text-rose-600">fora do padrão</strong> ficam em vermelho — você pode <strong>excluir</strong> ou atualizar o modelo na ZapSign.
        </p>
      </div>

      {/* Resumo */}
      <div className={`rounded-lg px-3 py-2 text-xs font-medium flex items-center gap-2 ${foraDoPadrao === 0 ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
        {foraDoPadrao === 0 ? <CheckCircle2 className="size-4 shrink-0" /> : <Sparkles className="size-4 shrink-0" />}
        {noSistema} no padrão{foraDoPadrao > 0 ? ` · ${foraDoPadrao} fora do padrão` : ""}{excluidas.size > 0 ? ` · ${excluidas.size} excluída(s)` : ""}{foraDoPadrao === 0 ? " · tudo certo" : ""}.
      </div>

      <div className="rounded-xl border border-[#eef1f5] overflow-hidden">
        <div className="grid grid-cols-[1.2fr_0.8fr_auto] gap-2 px-3 py-2 bg-[#f8fafc] text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">
          <span>Variável</span><span>Tipo</span><span className="text-right">Situação</span>
        </div>
        <div className="divide-y divide-[#eef1f5] max-h-[280px] overflow-y-auto">
          {vars.map((i) => {
            const excluida = excluidas.has(i.variable);
            const campo = campoNoSistema(i.label);
            return (
              <div key={i.variable} className={`grid grid-cols-[1.2fr_0.8fr_auto] gap-2 px-3 py-2 items-center ${excluida ? "bg-[#fafbfc] opacity-60" : campo ? "" : "bg-rose-50/40"}`}>
                <code className={`text-[11px] font-medium rounded px-1.5 py-0.5 truncate ${excluida ? "line-through text-[#98A2B3] bg-[#eef1f5]" : campo ? "text-[#7c3aed] bg-[#ede9fe]" : "text-rose-700 bg-rose-100"}`} title={i.variable}>{i.variable}</code>
                <span className="text-[11px] text-[#667085] truncate">{i.type}</span>
                <div className="justify-self-end flex items-center gap-1.5">
                  {excluida ? (
                    <button onClick={() => toggle(i.variable)} className="text-[10px] font-bold text-[#475467] hover:text-[#101828] inline-flex items-center gap-1">
                      <Plus className="size-3" />Reincluir
                    </button>
                  ) : campo ? (
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 bg-emerald-50 rounded-full px-2 py-0.5" title={`Mapeia para “${campo}”`}>
                      <CheckCircle2 className="size-2.5" />{campo}
                    </span>
                  ) : (
                    <>
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold text-rose-700 bg-rose-100 rounded-full px-2 py-0.5">fora do padrão</span>
                      <button onClick={() => toggle(i.variable)} title="Excluir esta variável" className="text-rose-400 hover:text-rose-600"><X className="size-3.5" /></button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {foraDoPadrao > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-[11px] text-amber-800 flex items-start gap-2">
          <Sparkles className="size-3.5 mt-0.5 shrink-0" />
          <span>Tem variável fora do padrão? Você pode <strong>excluí-la</strong> acima, ou editar o modelo na ZapSign e <button onClick={onAtualizarModelo} className="font-bold underline">atualizar a lista</button>.</span>
        </div>
      )}

      <span className="block text-[11px] text-[#98A2B3]">{ativas.length} de {vars.length} {vars.length === 1 ? "variável" : "variáveis"} no contrato · salvo no final</span>
    </div>
  );
}

/* ---------- Linha da tabela de modelos ---------- */
function ModelRow({ model, isDefault, onSetDefault }: { model: ZapsignModel; isDefault: boolean; onSetDefault: () => void }) {
  // O selecionado mostra todas as variáveis; nos outros, "+N" abre o resto sem selecionar o modelo.
  const [abertas, setAbertas] = useState(false);
  const todas = isDefault || abertas;
  const copiarId = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(model.id);
    toast.success("ID do modelo copiado");
  };
  return (
    <div
      onClick={onSetDefault}
      role="button"
      className={`grid grid-cols-[1fr_1.3fr_auto] gap-2 px-3 py-2.5 items-center cursor-pointer transition-colors ${isDefault ? "bg-success/8 ring-1 ring-inset ring-success/30" : "hover:bg-[#fafbfc]"}`}
    >
      <div className="min-w-0">
        <div className="text-sm font-semibold text-[#101828] truncate flex items-center gap-1.5" title={model.name}>
          {model.name}
          {isDefault && <span className="text-[9px] font-bold text-success bg-success/12 rounded-full px-1.5 py-0.5 shrink-0">SELECIONADO</span>}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <button onClick={copiarId} className="text-[10px] text-[#98A2B3] hover:text-primary inline-flex items-center gap-1">
            <Copy className="size-2.5" />{model.id.slice(0, 10)}…
          </button>
          {model.extras && model.extras.length > 0 && (
            <span className="text-[10px] text-[#94a3b8]" title={model.extras.join(", ")}>
              +{model.extras.length} doc{model.extras.length > 1 ? "s" : ""} complementar{model.extras.length > 1 ? "es" : ""}
            </span>
          )}
        </div>
      </div>
      <div className="min-w-0 flex flex-wrap gap-1">
        {model.variables.length === 0 ? (
          <span className="text-[11px] text-[#cbd5e1]">— sem variáveis —</span>
        ) : (
          <>
            {(todas ? model.variables : model.variables.slice(0, 4)).map((v) => (
              <code key={v} className={`text-[10px] font-medium text-[#7c3aed] bg-[#ede9fe] rounded px-1.5 py-0.5 ${todas ? "break-all" : "truncate max-w-[120px]"}`} title={`{{${v}}}`}>{`{{${v}}}`}</code>
            ))}
            {!todas && model.variables.length > 4 && (
              <button type="button" onClick={(e) => { e.stopPropagation(); setAbertas(true); }} title="Ver todas as variáveis"
                className="text-[10px] font-bold text-[#7c3aed] bg-[#ede9fe] hover:bg-[#ddd6fe] rounded px-1.5 py-0.5">+{model.variables.length - 4} ver todas</button>
            )}
            {abertas && !isDefault && model.variables.length > 4 && (
              <button type="button" onClick={(e) => { e.stopPropagation(); setAbertas(false); }}
                className="text-[10px] font-semibold text-[#667085] underline px-1">mostrar menos</button>
            )}
            {isDefault && <span className="basis-full text-[10.5px] text-[#667085] mt-0.5">{model.variables.length} variáve{model.variables.length === 1 ? "l" : "is"} neste modelo: confira todas em “Configurar Agentes”.</span>}
          </>
        )}
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onSetDefault(); }}
          title={isDefault ? "Modelo selecionado" : "Selecionar este modelo"}
          className="grid place-items-center"
        >
          <span className={`size-5 rounded-md border-2 grid place-items-center transition-colors ${isDefault ? "bg-success border-success text-white" : "border-[#cbd5e1] hover:border-success/60"}`}>
            {isDefault && <Check className="size-3.5" strokeWidth={3} />}
          </span>
        </button>
      </div>
    </div>
  );
}

/* ---------- Formulário de conexão (estado não conectado) ---------- */
function ConnectForm({ token, setToken, onConnect, busy, contaConectada, finalSegredo }: {
  token: string; setToken: (v: string) => void; onConnect: () => void; busy: boolean;
  contaConectada?: boolean; finalSegredo?: string | null;
}) {
  const [outroToken, setOutroToken] = useState(false);
  if (contaConectada && !outroToken) {
    // O escritório já conectou a ZapSign (Integrações): o produto só usa a mesma conta, sem pedir o token de novo.
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-start gap-2.5">
          <CheckCircle2 className="size-4 text-emerald-600 shrink-0 mt-0.5" />
          <div className="text-[13px] leading-snug text-[#101828]">
            A ZapSign do escritório já está conectada{finalSegredo ? <> (token termina em <strong>{finalSegredo}</strong>)</> : null}.
            Este produto usa a mesma conta: é só ler os modelos e escolher o deste produto.
          </div>
        </div>
        <Button onClick={onConnect} disabled={busy} className="w-full bg-gradient-primary text-white shadow-glow">
          {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <RefreshCw className="size-4 mr-1.5" />}
          Usar a ZapSign do escritório
        </Button>
        <button type="button" onClick={() => setOutroToken(true)} className="w-full text-[11px] font-semibold text-muted-foreground hover:text-primary">
          Trocar o token da conta
        </button>
      </div>
    );
  }
  const features: { Icon: typeof FileText; tile: string; fg: string; t: string; d: string }[] = [
    { Icon: FileText, tile: "bg-blue-50", fg: "text-blue-600", t: "Criação de contratos", d: "Gera documentos a partir dos seus modelos da ZapSign" },
    { Icon: PenLine, tile: "bg-violet-50", fg: "text-violet-600", t: "Assinatura digital", d: "Gera o link de assinatura e envia na conversa" },
    { Icon: CheckCircle2, tile: "bg-emerald-50", fg: "text-emerald-600", t: "Acompanhamento", d: "Monitora o status e avisa quem já assinou" },
  ];
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 flex items-start gap-2.5">
        <ShieldCheck className="size-4 text-warning shrink-0 mt-0.5" />
        <div className="text-[13px] leading-snug text-[#101828]">
          <strong>Obrigatório para ativar o agente.</strong> Sem o ZapSign conectado, o agente <strong>não consegue gerar nem fechar contratos automaticamente</strong> na conversa — é o que fecha a venda pela IA.
        </div>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">
        Conecte sua conta ZapSign para que seu agente crie contratos, envie links de assinatura e acompanhe o status automaticamente durante as conversas.
      </p>

      <div className="rounded-xl border border-[#eef1f5] bg-[#fafbfc] p-4">
        <div className="flex items-center gap-1.5 mb-3">
          <Sparkles className="size-3 text-[#94a3b8]" />
          <span className="text-[10px] uppercase tracking-wider font-bold text-[#94a3b8]">O que o agente passa a fazer</span>
        </div>
        <div className="space-y-2.5">
          {features.map(({ Icon, tile, fg, t, d }) => (
            <div key={t} className="flex items-start gap-3">
              <div className={`size-9 rounded-lg grid place-items-center shrink-0 ${tile} ${fg}`}>
                <Icon className="size-[18px]" strokeWidth={2.2} />
              </div>
              <div className="min-w-0 pt-0.5">
                <div className="text-sm font-semibold text-[#101828] leading-tight">{t}</div>
                <div className="text-xs text-[#667085] mt-0.5 leading-snug">{d}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-1.5 mt-3.5 pt-3 border-t border-[#eef1f5] text-[11px] text-[#667085]">
          <ShieldCheck className="size-3.5 text-emerald-600 shrink-0" />
          Assinaturas com validade jurídica · seu token fica guardado com segurança na sua conta.
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-xs font-semibold">Token de API</Label>
          <a href="https://docs.zapsign.com.br/" target="_blank" rel="noopener noreferrer" className="text-[11px] font-semibold text-primary inline-flex items-center gap-1">
            <ExternalLink className="size-3" />Ver tutorial
          </a>
        </div>
        <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="Cole seu token aqui…" type="password" />
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Obtenha em <a href="https://app.zapsign.com.br" target="_blank" rel="noopener noreferrer" className="text-primary font-semibold">app.zapsign.com.br</a> › Configurações › Integrações › API.
        </p>
      </div>

      <Button onClick={onConnect} disabled={busy || !token.trim()} className="w-full bg-gradient-primary text-white shadow-glow">
        {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <RefreshCw className="size-4 mr-1.5" />}
        Conectar e sincronizar modelos
      </Button>
    </div>
  );
}

/* ---------- Placeholder "em breve" ---------- */
function EmBreve({ icon, titulo, texto }: { icon: React.ReactNode; titulo: string; texto: string }) {
  return (
    <div className="rounded-xl border border-dashed border-[#e5e8ee] bg-[#fafbfc] p-8 text-center">
      <div className="size-11 rounded-xl bg-[#eef1f5] grid place-items-center text-[#94a3b8] mx-auto mb-3">{icon}</div>
      <h3 className="text-sm font-bold text-[#101828]">{titulo}</h3>
      <p className="text-xs text-[#98A2B3] mt-1 max-w-sm mx-auto leading-relaxed">{texto}</p>
      <span className="inline-block mt-3 text-[10px] font-bold uppercase tracking-wider text-[#94a3b8] bg-[#eef1f5] rounded-full px-2.5 py-1">Em breve</span>
    </div>
  );
}
