import { useEffect, useMemo, useState } from "react";
import { api, enviar } from "@/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { AlertCircle, Cpu, Eye, Info, Loader2, Lock, RotateCcw, Search } from "lucide-react";

/** Um bloco de texto que o motor põe no prompt (GET /admin/biblioteca/regras-sistema). */
export interface BlocoSistema {
  chave: string;
  titulo: string;
  grupo: string;
  quando_entra: string;
  padrao: string;
  editavel: boolean;
  placeholders: string[];
  obrigatorios: string[];
}

interface Props {
  /** Produto salvo (a prévia precisa do id). */
  idProduto?: string;
  /** Textos editados {chave: texto}; chave ausente = vale o padrão do código. */
  value: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
  /** Etapas do produto para o seletor da prévia. */
  etapas: { papel: string; label: string }[];
  accent: [string, string];
}

/** Placeholders obrigatórios que o texto editado tirou (o backend recusa ao salvar). */
export const placeholdersFaltando = (bloco: BlocoSistema, texto: string) =>
  bloco.obrigatorios.filter((p) => !texto.includes(p));

/**
 * Aba "Regras do sistema" do editor do catálogo (super admin): tudo o que o motor põe no prompt da IA além do
 * roteiro — regras de conduta, das etapas, da família, das ferramentas, dos avisos e da passagem de etapa. Cada
 * bloco mostra o texto atual (o editado ou o padrão) e volta ao padrão num clique. O Formato da resposta é só
 * leitura (mudar o JSON quebraria a leitura da resposta). Os textos vão em config_modelo.regras_sistema ao salvar.
 */
export const RegrasSistemaEditor = ({ idProduto, value, onChange, etapas, accent }: Props) => {
  const [blocos, setBlocos] = useState<BlocoSistema[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [soEditados, setSoEditados] = useState(false);
  const [etapa, setEtapa] = useState(etapas[0]?.papel ?? "sdr");
  const [previa, setPrevia] = useState<{ nome: string; sistema: string; caracteres: number } | null>(null);
  const [carregandoPrevia, setCarregandoPrevia] = useState(false);
  const [c1, c2] = accent;

  useEffect(() => {
    api<BlocoSistema[]>("/admin/biblioteca/regras-sistema")
      .then(setBlocos)
      .catch((e: any) => setErro(e?.message ?? "Não foi possível carregar as regras do sistema."));
  }, []);

  useEffect(() => {
    if (!etapas.some((e) => e.papel === etapa) && etapas[0]) setEtapa(etapas[0].papel);
  }, [etapas, etapa]);

  const editados = Object.keys(value).filter((k) => (value[k] ?? "").trim()).length;

  const grupos = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    const mapa = new Map<string, BlocoSistema[]>();
    (blocos ?? []).forEach((b) => {
      const editado = !!(value[b.chave] ?? "").trim();
      if (soEditados && !editado) return;
      if (termo && !`${b.titulo} ${b.quando_entra} ${value[b.chave] ?? b.padrao}`.toLowerCase().includes(termo)) return;
      if (!mapa.has(b.grupo)) mapa.set(b.grupo, []);
      mapa.get(b.grupo)!.push(b);
    });
    return [...mapa.entries()];
  }, [blocos, value, busca, soEditados]);

  const mudar = (bloco: BlocoSistema, texto: string) => {
    const novo = { ...value };
    // Igual ao padrão ou vazio = sem edição (vale o padrão do código).
    if (!texto.trim() || texto.trim() === bloco.padrao.trim()) delete novo[bloco.chave];
    else novo[bloco.chave] = texto;
    onChange(novo);
  };

  const verPrevia = async () => {
    if (!idProduto) return toast.error("Salve o produto antes de ver a prévia.");
    setCarregandoPrevia(true);
    try {
      const r = await enviar<{ nome: string; sistema: string; caracteres: number }>(
        `/admin/biblioteca/produtos/${idProduto}/previa-sistema`, { papel: etapa, regras_sistema: value });
      setPrevia(r);
    } catch (e: any) {
      toast.error("Não foi possível montar a prévia", { description: e?.message });
    } finally {
      setCarregandoPrevia(false);
    }
  };

  if (erro) {
    return (
      <Card className="p-6 flex items-center gap-2 text-sm text-destructive">
        <AlertCircle className="size-4" /> {erro}
      </Card>
    );
  }
  if (!blocos) {
    return (
      <div className="grid place-items-center py-16">
        <Loader2 className="size-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Aviso de contexto + prévia */}
      <div className="flex items-start gap-3 rounded-xl border p-3.5" style={{ borderColor: `${c1}33`, backgroundColor: `${c1}0d` }}>
        <div className="size-8 rounded-lg grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>
          <Cpu className="size-4" />
        </div>
        <div className="flex-1 min-w-0 space-y-3">
          <p className="text-xs text-muted-foreground leading-relaxed">
            Estes são os textos que o <strong className="text-foreground">motor</strong> junta ao roteiro de cada etapa antes de mandar para a IA.
            Editar aqui vale só para <strong className="text-foreground">este produto</strong> e chega aos escritórios na próxima ativação ou sincronização.
            Bloco sem edição usa o padrão do sistema.
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={etapa} onValueChange={setEtapa}>
              <SelectTrigger className="h-9 w-[200px] bg-background"><SelectValue placeholder="Etapa" /></SelectTrigger>
              <SelectContent>
                {etapas.map((e) => <SelectItem key={e.papel} value={e.papel}>{e.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <Button size="sm" onClick={verPrevia} disabled={carregandoPrevia || !idProduto} className="gap-1.5">
              {carregandoPrevia ? <Loader2 className="size-4 animate-spin" /> : <Eye className="size-4" />}
              Ver como a IA recebe
            </Button>
            {!idProduto && <span className="text-[11px] text-muted-foreground">Salve o produto para ver a prévia.</span>}
          </div>
        </div>
      </div>

      {/* Filtros */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar regra ou trecho…" className="pl-9" />
        </div>
        <Button variant={soEditados ? "default" : "outline"} size="sm" onClick={() => setSoEditados((s) => !s)}>
          Só editados{editados ? ` (${editados})` : ""}
        </Button>
      </div>

      {grupos.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground text-center">Nenhuma regra encontrada.</Card>
      )}

      {grupos.map(([grupo, lista]) => (
        <div key={grupo} className="space-y-3">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#98A2B3] px-1 pt-2">{grupo}</div>
          {lista.map((b) => {
            const editado = !!(value[b.chave] ?? "").trim();
            const texto = editado ? value[b.chave] : b.padrao;
            const faltam = b.editavel ? placeholdersFaltando(b, texto) : [];
            const linhas = Math.min(18, Math.max(3, texto.split("\n").length + 1));
            return (
              <Card key={b.chave} className="p-5 space-y-3">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm font-semibold">{b.titulo}</h3>
                      {!b.editavel ? (
                        <Badge variant="outline" className="gap-1 font-medium"><Lock className="size-3" /> Só leitura</Badge>
                      ) : editado ? (
                        <Badge className="font-medium" style={{ backgroundColor: "#e8f9ee", color: "#009926" }}>Editado</Badge>
                      ) : (
                        <Badge variant="secondary" className="font-medium">Padrão</Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">Quando entra: {b.quando_entra}</p>
                  </div>
                  {b.editavel && (
                    <Button variant="outline" size="sm" className="gap-1.5 shrink-0" disabled={!editado}
                      onClick={() => mudar(b, "")}>
                      <RotateCcw className="size-3.5" /> Voltar ao padrão
                    </Button>
                  )}
                </div>
                <Textarea
                  rows={linhas}
                  value={texto}
                  readOnly={!b.editavel}
                  onChange={(e) => mudar(b, e.target.value)}
                  placeholder={b.padrao ? undefined : "Vazio: não entra nada. Escreva quando a IA deve usar este destino."}
                  className={`font-mono text-[12.5px] leading-relaxed ${!b.editavel ? "bg-muted/40 text-muted-foreground" : ""}`}
                />
                {(b.placeholders.length > 0 || faltam.length > 0) && (
                  <div className="flex items-center gap-1.5 flex-wrap text-[11px] text-muted-foreground">
                    <Info className="size-3 shrink-0" />
                    {b.placeholders.map((p) => (
                      <code key={p} className="text-[#7c3aed]">{p}</code>
                    ))}
                    <span>{b.obrigatorios.length ? "o motor troca pelo valor real; não apague." : "o motor troca pelo valor real."}</span>
                    {faltam.length > 0 && (
                      <span className="text-destructive font-medium inline-flex items-center gap-1">
                        <AlertCircle className="size-3" /> Falta {faltam.join(", ")}: o produto não salva assim.
                      </span>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      ))}

      <Dialog open={!!previa} onOpenChange={(o) => !o && setPrevia(null)}>
        <DialogContent className="max-w-4xl w-[calc(100vw-2rem)] max-h-[88vh] flex flex-col gap-3">
          <DialogHeader>
            <DialogTitle>Como a IA recebe · {previa?.nome}</DialogTitle>
            <DialogDescription>
              Prompt de sistema completo, na ordem real. Roteiro, conteúdo e frases de troca salvos no produto; regras desta aba como estão na tela.
              As variáveis {"{{ }}"} ficam sem valor: cada escritório preenche as suas. {previa ? `${previa.caracteres.toLocaleString("pt-BR")} caracteres.` : ""}
            </DialogDescription>
          </DialogHeader>
          <pre className="flex-1 min-h-0 overflow-auto rounded-lg border bg-muted/30 p-4 text-[12px] leading-relaxed font-mono whitespace-pre-wrap break-words">
            {previa?.sistema}
          </pre>
        </DialogContent>
      </Dialog>
    </div>
  );
};
