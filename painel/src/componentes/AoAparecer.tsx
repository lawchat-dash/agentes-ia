import { useEffect, useRef, useState, type ReactNode } from "react";

/** Monta o conteúdo só quando ele chega perto da tela (e mantém montado depois). Telas com muitos gráficos (Relatórios)
 *  montavam tudo de uma vez ao abrir e travavam; agora só o que está à vista é montado na hora. */
export function AoAparecer({ children, altura = 320, margem = "600px" }: { children: ReactNode; altura?: number; margem?: string }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [ver, setVer] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (ver || !ref.current) return;
    const obs = new IntersectionObserver((e) => { if (e.some((x) => x.isIntersecting)) { setVer(true); obs.disconnect(); } }, { rootMargin: margem });
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, [ver, margem]);
  if (ver) return <>{children}</>;
  return <div ref={ref} style={{ minHeight: altura }} aria-hidden />;
}
