import ProductConfigurator from "@/components/agent/ProductConfigurator";

/**
 * Página de ativação de produto (wizard de 5 passos).
 * Toda a lógica vive em ProductConfigurator (modo "create"), compartilhada com o
 * editor de produto (/meus-produtos/:id, modo "edit").
 */
const Ativar = () => <ProductConfigurator mode="create" />;

export default Ativar;
