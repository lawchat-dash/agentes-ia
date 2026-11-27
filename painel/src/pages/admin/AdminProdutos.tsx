import { Cabecalho } from "@/componentes/ui";
import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, enviar } from "@/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Aviso } from "@/components/common/Aviso";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { Pencil, Plus, Trash2, Copy, Search, Package, CheckCircle2, Clock3, FileEdit, Sparkles, Loader2, Upload } from "lucide-react";
import { categories, getCategoryIcon, resolveGradient } from "@/data/categories";
import { ImportarCatalogoDialog } from "@/components/admin/ImportarCatalogoDialog";

// Catálogo: agentesia_biblioteca_produtos (via /api/biblioteca e /api/admin/biblioteca). Cada produto tem
// 5 agentes em agentesia_biblioteca_agentes (editados no AdminProdutoEditor).
type ProdStatus = "rascunho" | "em_breve" | "publicado";

const STATUS_LABEL: Record<ProdStatus, string> = {
  rascunho: "Rascunho", em_breve: "Em breve", publicado: "Publicado",
};
const STATUS_DOT: Record<ProdStatus, string> = {
  publicado: "#16a34a", em_breve: "#d97706", rascunho: "#94a3b8",
};

type ProductRow = {
  id: string;
  slug: string;
  nome: string;
  categoria: string;
  descricao_curta: string | null;
  capa_gradiente: string | null;
  status: ProdStatus;
  versao: string | null;
  updated_at: string;
  created_at?: string | null;
};

// Ordem FIXA da lista: mais novo primeiro pela data de CRIAÇÃO (e nome no empate). Antes ordenava por updated_at, que o
// banco renova a cada salvamento/troca de status: o produto editado pulava para o topo e "sumia" de onde estava.
const ordenarProdutos = (lista: ProductRow[]) => lista.slice().sort((x, y) =>
  String(y.created_at ?? "").localeCompare(String(x.created_at ?? "")) || x.nome.localeCompare(y.nome, "pt-BR"));

export default function AdminProdutos() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  // Invalida o catálogo do cliente (/biblioteca) p/ refletir mudanças na hora
  // (staleTime global é 30s — sem isto o cliente vê status/produto desatualizado).
  const invalidarCatalogo = () => {
    qc.invalidateQueries({ queryKey: ["templates"] });
    qc.invalidateQueries({ queryKey: ["template"] });
  };
  const [rows, setRows] = useState<ProductRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [cat, setCat] = useState<string | null>(null);

  // Criar produto JÁ no padrão (5 agentes) via POST /admin/biblioteca/produtos/padrao.
  const [criarOpen, setCriarOpen] = useState(false);
  const [importarOpen, setImportarOpen] = useState(false);   // importar o catálogo do sistema antigo
  const [criando, setCriando] = useState(false);
  const [novoNome, setNovoNome] = useState("");
  const [novaArea, setNovaArea] = useState("");
  const [novaCat, setNovaCat] = useState<string>(categories[0]?.name ?? "Consumidor");
  const [novaDesc, setNovaDesc] = useState("");

  const criarPadrao = async () => {
    if (!novoNome.trim() || !novaArea.trim()) { toast.error("Informe o nome e a área do produto."); return; }
    setCriando(true);
    let data: any = null;
    try {
      data = await enviar("/admin/biblioteca/produtos/padrao", {
        nome: novoNome.trim(),
        area_juridica: novaArea.trim(),
        categoria: novaCat,
        descricao: novaDesc.trim() || null,
      });
    } catch (e: any) {
      setCriando(false);
      toast.error(e?.message ?? "Erro ao criar");
      return;
    }
    setCriando(false);
    toast.success("Produto criado no padrão (5 agentes prontos)");
    setCriarOpen(false);
    setNovoNome(""); setNovaArea(""); setNovaDesc("");
    if (data?.id) navigate(`/admin/produtos/${data.id}`);
    else load(true);
  };

  // Recarga depois de uma mudança é silenciosa: a tabela continua na tela (sem a linha "Carregando…" piscando).
  const load = async (silencioso = false) => {
    if (!silencioso) setLoading(true);
    try {
      // ?todos=1: a equipe LawChat recebe também os rascunhos.
      const data = await api<ProductRow[]>("/biblioteca/produtos?todos=1");
      setRows(ordenarProdutos((data ?? []) as ProductRow[]));
    } catch (e: any) {
      toast.error(e?.message ?? "Erro ao carregar");
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      const ms =
        !search ||
        r.nome.toLowerCase().includes(search.toLowerCase()) ||
        r.slug.toLowerCase().includes(search.toLowerCase());
      const mc = !cat || r.categoria === cat;
      return ms && mc;
    });
  }, [rows, search, cat]);

  const stats = useMemo(() => ({
    total: rows.length,
    publicado: rows.filter((r) => r.status === "publicado").length,
    em_breve: rows.filter((r) => r.status === "em_breve").length,
    rascunho: rows.filter((r) => r.status === "rascunho").length,
  }), [rows]);

  // Troca de status: a linha muda na hora e fica no mesmo lugar; se o servidor recusar, volta ao que era.
  const setStatus = async (r: ProductRow, status: ProdStatus) => {
    if (status === r.status) return;
    const anterior = r.status;
    setRows((lista) => lista.map((x) => (x.id === r.id ? { ...x, status } : x)));
    try {
      await enviar(`/admin/biblioteca/produtos/${r.id}`, { status }, "PATCH");
    } catch (e: any) {
      setRows((lista) => lista.map((x) => (x.id === r.id ? { ...x, status: anterior } : x)));
      return toast.error(e?.status === 403 ? "Sem permissão para alterar este produto." : e?.message);
    }
    toast.success(`Status: ${STATUS_LABEL[status]}`);
    invalidarCatalogo();
    load(true);
  };

  // Exclusão do catálogo: confirmada num AlertDialog (antes era confirm() nativo).
  const [excluindo, setExcluindo] = useState<ProductRow | null>(null);
  const [removendo, setRemovendo] = useState(false);
  const remove = async () => {
    const r = excluindo;
    if (!r) return;
    setRemovendo(true);
    try {
      await api(`/admin/biblioteca/produtos/${r.id}`, { metodo: "DELETE" });
    } catch (e: any) {
      setRemovendo(false);
      return toast.error("Não foi possível excluir", { description: e?.message });
    }
    setRemovendo(false);
    setExcluindo(null);
    toast.success("Produto excluído do catálogo", { description: r.nome });
    invalidarCatalogo();
    load(true);
  };

  const duplicate = async (r: ProductRow) => {
    // O servidor copia o produto (rascunho, slug -copia-xxxx) e os 5 agentes
    // (prompts, handoff, config_modelo) — a cópia não perde a config por-agente.
    try {
      await enviar(`/admin/biblioteca/produtos/${r.id}/duplicar`, {});
    } catch (e: any) {
      return toast.error(e?.message ?? "Falha ao duplicar");
    }
    toast.success("Duplicado");
    load(true);
  };

  const statCards = [
    { key: "total", label: "Total", value: stats.total, Icon: Package, color: "#334155" },
    { key: "publicado", label: "Publicados", value: stats.publicado, Icon: CheckCircle2, color: "#16a34a" },
    { key: "em_breve", label: "Em breve", value: stats.em_breve, Icon: Clock3, color: "#d97706" },
    { key: "rascunho", label: "Rascunhos", value: stats.rascunho, Icon: FileEdit, color: "#64748b" },
  ];

  return (
    <div className="space-y-5">
      {/* Cabeçalho (mesmo padrão das outras telas do superadmin) */}
      <Cabecalho eyebrow="Superadmin" titulo="Produtos" texto="Catálogo da Biblioteca: o que os escritórios podem ativar."
        acoes={<>
          <button type="button" className="btn" onClick={() => setImportarOpen(true)}><Upload />Importar do Weaver</button>
          <button type="button" className="btn" onClick={() => setCriarOpen(true)}><Sparkles />Criar no padrão</button>
          <button type="button" className="btn pri" onClick={() => navigate("/admin/produtos/novo")}><Plus />Novo produto</button>
        </>} />

      <ImportarCatalogoDialog open={importarOpen} onOpenChange={setImportarOpen} onImportado={() => { void load(true); invalidarCatalogo(); }} />

      {/* Criar no padrão — gera produto + 5 agentes prontos (sistemaia_criar_produto_padrao) */}
      <Dialog open={criarOpen} onOpenChange={setCriarOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Sparkles className="size-5 text-primary" />Criar produto no padrão</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground -mt-1">
            Gera o produto + os <strong>5 agentes</strong> (SDR, Closer, Contratos, Assinatura, Desqualificado) já com prompts no modelo <code className="text-[#7c3aed]">{"{{ }}"}</code> e handoffs. Você ajusta os detalhes depois no editor.
          </p>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">Nome do produto</Label>
              <Input value={novoNome} onChange={(e) => setNovoNome(e.target.value)} placeholder="Ex: Aposentadoria Especial" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">Área jurídica (usada nos prompts)</Label>
              <Input value={novaArea} onChange={(e) => setNovaArea(e.target.value)} placeholder="Ex: Aposentadoria Especial" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">Categoria</Label>
                <Select value={novaCat} onValueChange={setNovaCat}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {categories.map((c) => <SelectItem key={c.name} value={c.name}>{c.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">Descrição curta <span className="text-muted-foreground font-normal">(opcional)</span></Label>
              <Textarea value={novaDesc} onChange={(e) => setNovaDesc(e.target.value)} placeholder="Deixe em branco para gerar automático" className="min-h-[64px]" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCriarOpen(false)} disabled={criando}>Cancelar</Button>
            <Button onClick={criarPadrao} disabled={criando || !novoNome.trim() || !novaArea.trim()}>
              {criando ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Sparkles className="size-4 mr-1.5" />}
              Criar produto
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Resumo */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {statCards.map((s) => (
          <Card key={s.key} className="p-4 flex items-center gap-3">
            <div className="size-10 rounded-xl grid place-items-center shrink-0" style={{ backgroundColor: `${s.color}14`, color: s.color }}>
              <s.Icon className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="text-2xl font-bold leading-none tabular-nums">{s.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{s.label}</div>
            </div>
          </Card>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por nome ou slug..."
            className="pl-9 h-10 rounded-xl"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setCat(null)}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${!cat ? "bg-primary text-primary-foreground border-primary" : "bg-card hover:bg-accent"}`}
          >
            Todas
          </button>
          {categories.map((c) => (
            <button
              key={c.name}
              onClick={() => setCat(c.name)}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${cat === c.name ? "bg-primary text-primary-foreground border-primary" : "bg-card hover:bg-accent"}`}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>

      {/* Tabela */}
      <Card className="p-0 overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Produto</TableHead>
              <TableHead>Categoria</TableHead>
              <TableHead>Versão</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow><TableCell colSpan={5} className="text-center py-10 text-muted-foreground">Carregando…</TableCell></TableRow>
            )}
            {!loading && filtered.length === 0 && (
              <TableRow><TableCell colSpan={5} className="text-center py-14 text-muted-foreground">
                <Package className="size-7 mx-auto mb-2 text-muted-foreground/40" />
                Nenhum produto encontrado.
              </TableCell></TableRow>
            )}
            {filtered.map((r) => {
              const Icon = getCategoryIcon(r.categoria);
              const [c1, c2] = resolveGradient(r.capa_gradiente, r.categoria);
              return (
                <TableRow key={r.id} className="group cursor-pointer" onClick={() => navigate(`/admin/produtos/${r.id}`)}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div className="size-9 rounded-lg grid place-items-center text-white shrink-0 shadow-sm" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>
                        <Icon className="size-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="font-medium truncate group-hover:text-primary transition-colors">{r.nome}</div>
                        <div className="text-xs text-muted-foreground font-mono truncate">{r.slug}</div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-sm">{r.categoria}</TableCell>
                  <TableCell className="text-sm text-muted-foreground font-mono">{r.versao}</TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Select value={r.status} onValueChange={(v) => setStatus(r, v as ProdStatus)}>
                      <SelectTrigger className="h-8 w-[140px] text-xs gap-1.5">
                        <span className="size-2 rounded-full shrink-0" style={{ backgroundColor: STATUS_DOT[r.status] }} />
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="rascunho">Rascunho</SelectItem>
                        <SelectItem value="em_breve">Em breve</SelectItem>
                        <SelectItem value="publicado">Publicado</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-0.5 opacity-60 group-hover:opacity-100 transition-opacity">
                      <Button size="icon" variant="ghost" title="Duplicar" onClick={() => duplicate(r)}><Copy className="size-4" /></Button>
                      <Button size="icon" variant="ghost" title="Editar" onClick={() => navigate(`/admin/produtos/${r.id}`)}><Pencil className="size-4" /></Button>
                      <Button size="icon" variant="ghost" title="Excluir" aria-label={`Excluir ${r.nome}`} onClick={() => setExcluindo(r)}><Trash2 className="size-4 text-destructive" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>

      {/* Confirmação de exclusão do catálogo — sem volta */}
      <AlertDialog open={!!excluindo} onOpenChange={(o) => { if (!o && !removendo) setExcluindo(null); }}>
        <AlertDialogContent className="max-w-md rounded-2xl">
          <AlertDialogHeader>
            <div className="flex items-center gap-3">
              <span className="size-10 rounded-xl grid place-items-center shrink-0 bg-destructive/10 text-destructive">
                <Trash2 className="size-5" />
              </span>
              <AlertDialogTitle className="text-left">Excluir produto do catálogo?</AlertDialogTitle>
            </div>
            <AlertDialogDescription asChild>
              <div className="space-y-3 pt-1 text-left">
                <p>
                  O produto <strong className="text-foreground">{excluindo?.nome}</strong> e os agentes dele serão
                  apagados do catálogo da Biblioteca. Nenhum cliente poderá mais ativá-lo.
                </p>
                <Aviso tipo="erro" compacto titulo="Esta ação não tem volta">
                  Não dá para desfazer nem recuperar depois. Se quiser só tirar do ar, mude o status para <strong>Rascunho</strong>.
                </Aviso>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="gap-2 sm:gap-0">
            <AlertDialogCancel disabled={removendo}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); void remove(); }}
              disabled={removendo}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {removendo ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Trash2 className="size-4 mr-1.5" />}
              Excluir definitivamente
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
