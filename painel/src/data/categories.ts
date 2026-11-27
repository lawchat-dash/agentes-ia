import {
  Scale,
  Landmark,
  HeartCrack,
  ShieldCheck,
  Banknote,
  Home,
  Lock,
  BarChart3,
  ScrollText,
  Briefcase,
  type LucideIcon,
} from "lucide-react";

export interface Category {
  name: string;
  Icon: LucideIcon;
  /** kept for any legacy usage; UI should prefer Icon */
  icon?: string;
  color: string;
}

export const categories: Category[] = [
  { name: "Trabalhista",     Icon: Scale,       color: "from-slate-700 to-slate-900" },
  { name: "Previdenciário",  Icon: Landmark,    color: "from-slate-700 to-slate-900" },
  { name: "Família",         Icon: HeartCrack,  color: "from-slate-700 to-slate-900" },
  { name: "Consumidor",      Icon: ShieldCheck, color: "from-slate-700 to-slate-900" },
  { name: "Bancário",        Icon: Banknote,    color: "from-slate-700 to-slate-900" },
  { name: "Imobiliário",     Icon: Home,        color: "from-slate-700 to-slate-900" },
  { name: "Criminal",        Icon: Lock,        color: "from-slate-700 to-slate-900" },
  { name: "Tributário",      Icon: BarChart3,   color: "from-slate-700 to-slate-900" },
  { name: "Civil",           Icon: ScrollText,  color: "from-slate-700 to-slate-900" },
];

const FALLBACK: LucideIcon = Briefcase;

export function getCategoryIcon(name?: string | null): LucideIcon {
  if (!name) return FALLBACK;
  return categories.find((c) => c.name === name)?.Icon ?? FALLBACK;
}

/** Gradiente (hex) por categoria — usado nos ícones dos cards/detalhe (sem roxo). */
const CAT_GRAD: Record<string, [string, string]> = {
  Trabalhista: ["#0ea5e9", "#0369a1"],
  Previdenciário: ["#22c55e", "#15803d"],
  Família: ["#f43f5e", "#be123c"],
  Consumidor: ["#f59e0b", "#b45309"],
  Bancário: ["#14b8a6", "#0f766e"],
  Imobiliário: ["#f97316", "#c2410c"],
  Criminal: ["#475569", "#1e293b"],
  Tributário: ["#06b6d4", "#0e7490"],
  Civil: ["#10b981", "#047857"],
};

export const getCategoryGradient = (name?: string | null): [string, string] =>
  (name && CAT_GRAD[name]) || ["#00bc33", "#009926"];

/** Paleta de cores de produto (hex) — usada no seletor de cor do admin. */
export const GRADIENT_PRESETS: { name: string; c1: string; c2: string; value: string }[] = [
  { name: "Verde", c1: "#00bc33", c2: "#009926" },
  { name: "Azul", c1: "#0ea5e9", c2: "#0369a1" },
  { name: "Roxo", c1: "#8b5cf6", c2: "#6d28d9" },
  { name: "Rosa", c1: "#f43f5e", c2: "#be123c" },
  { name: "Âmbar", c1: "#f59e0b", c2: "#b45309" },
  { name: "Teal", c1: "#14b8a6", c2: "#0f766e" },
  { name: "Laranja", c1: "#f97316", c2: "#c2410c" },
  { name: "Ardósia", c1: "#475569", c2: "#1e293b" },
].map((p) => ({ ...p, value: `${p.c1},${p.c2}` }));

/** Converte "#c1,#c2" (hex) em par. Ignora formatos antigos (classes Tailwind) → null. */
export const parseGradient = (s?: string | null): [string, string] | null => {
  if (!s) return null;
  const parts = s.split(",").map((x) => x.trim());
  if (parts.length === 2 && parts.every((p) => /^#[0-9a-fA-F]{6}$/.test(p))) {
    return [parts[0], parts[1]];
  }
  return null;
};

/** Cor efetiva: cor própria do produto (hex) se houver; senão a cor da categoria. */
export const resolveGradient = (cover?: string | null, category?: string | null): [string, string] =>
  parseGradient(cover) ?? getCategoryGradient(category);


/** Emoji próprio do produto (campo icone do catálogo). Nome de ícone (ex.: "scale") não conta: aí vale o ícone da categoria. */
export const emojiDoProduto = (icone?: string | null): string | null =>
  icone && icone.trim() && !/^[a-z0-9_-]+$/i.test(icone.trim()) ? icone.trim() : null;
