import { useSearchParams } from "react-router-dom";
import { TelaConfiguracoes } from "./Configuracoes";
import { TelaIntegracoes } from "./Integracoes";

/** Minha Conta: os dados do escritório e as integrações (WhatsApp/LawChat e ZapSign) numa tela só, em abas. */
export function TelaMinhaConta() {
  const [params, setParams] = useSearchParams();
  const aba = params.get("aba") === "integracoes" ? "integracoes" : "escritorio";
  return (
    <>
      <div className="seg" role="tablist" aria-label="Minha Conta" style={{ marginBottom: 16 }}>
        <button role="tab" aria-selected={aba === "escritorio"} className={aba === "escritorio" ? "on" : ""} onClick={() => setParams({ aba: "escritorio" })}>Escritório</button>
        <button role="tab" aria-selected={aba === "integracoes"} className={aba === "integracoes" ? "on" : ""} onClick={() => setParams({ aba: "integracoes" })}>Integrações</button>
      </div>
      {aba === "escritorio" ? <TelaConfiguracoes /> : <TelaIntegracoes />}
    </>
  );
}
