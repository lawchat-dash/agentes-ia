import { useState } from "react";
import { motion } from "framer-motion";
import {
  AlertCircle, Bot, Check, CheckCheck, Clock, Contact, ExternalLink, FileText, Headphones, Image as ImageIcon, MapPin, Smile, Sticker, UserRound, Video, Workflow,
  type LucideIcon,
} from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { AUTORES, TIPOS_MIDIA, formaDaMidia, hora, nomeDoArquivo, urlSegura, type FormaMidia, type Mensagem, type TipoMensagem } from "./tipos";

const ICONES_MIDIA: Record<Exclude<TipoMensagem, "texto">, LucideIcon> = {
  audio: Headphones, imagem: ImageIcon, video: Video, documento: FileText, figurinha: Sticker, localizacao: MapPin, contato: Contact,
};

/** A mídia que a IA envia fica gravada com este marcador interno (app/pipeline.py, `_enviar`): não é texto
 *  tirado de um arquivo do lead, então o balão não mostra "O que a IA viu..." para ela. */
const MIDIA_ENVIADA = /^\[m[íi]dia enviada:\s*(.*?)\]$/i;

/** Cor do nome do autor dentro do balão (só IA, atendente e automação mostram o nome). */
const AUTOR_VISUAL: Partial<Record<Mensagem["autor"], { icone: LucideIcon; cor: string }>> = {
  ia: { icone: Bot, cor: "#008A26" },
  humano: { icone: UserRound, cor: "#1D4ED8" },
  automacao: { icone: Workflow, cor: "#6D28D9" },
};

/**
 * Um balão estilo WhatsApp: o lead à esquerda; IA (verde claro), atendente (azul, com faixa) e automação
 * à direita; avisos do sistema no meio. Mídia com endereço toca ou abre no próprio balão (áudio, vídeo,
 * imagem, documento); sem endereço, aparece só o tipo. Nos dois casos, com o texto que a IA tirou dela.
 */
export function BolhaMensagem({ mensagem: m, novoAutor }: { mensagem: Mensagem; novoAutor: boolean }) {
  const lado = m.autor === "lead" ? "esq" : m.autor === "sistema" ? "meio" : "dir";
  const visual = AUTOR_VISUAL[m.autor];
  const midia = m.tipo !== "texto" ? TIPOS_MIDIA[m.tipo] : null;
  const IconeMidia = m.tipo !== "texto" ? ICONES_MIDIA[m.tipo] ?? Smile : null;
  const texto = (m.texto ?? "").trim();
  const bruto = (m.texto_extraido ?? "").trim();
  const enviada = m.autor !== "lead" ? MIDIA_ENVIADA.exec(bruto) : null;
  const extraido = enviada ? "" : bruto;
  const nossa = m.autor !== "lead" && m.autor !== "sistema";
  const url = m.tipo !== "texto" ? urlSegura(m.url_midia) : null;
  const forma = url ? formaDaMidia(m.tipo, url) : null;
  // Com arquivo, o rótulo segue o que ele é de fato (a IA grava toda mídia enviada como "video").
  const rotuloMidia = forma ? TIPOS_MIDIA[forma] : midia;

  return (
    <motion.div className={`cv-linha ${lado}${novoAutor ? " novo-autor" : ""}`}
      initial={{ opacity: 0, y: 6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}>
      <div className={`cv-bolha ${m.autor}`}>
        {visual && novoAutor && (
          <div className="cv-autor" style={{ color: visual.cor }}><visual.icone aria-hidden />{AUTORES[m.autor]}</div>
        )}
        {url && forma ? (
          <ArquivoDaMidia url={url} forma={forma} rotulo={rotuloMidia?.rotulo ?? "Mídia"} />
        ) : midia && IconeMidia && (
          <div className="cv-midia"><IconeMidia aria-hidden />{midia.rotulo}</div>
        )}
        {texto && <div>{texto}</div>}
        {extraido && extraido !== texto && (
          <div className="cv-extraido"><b>{rotuloMidia?.extraido ?? "Texto extraído"}</b>{extraido}</div>
        )}
        {enviada && enviada[1] && (
          <div className="cv-extraido"><b>Mídia enviada pela IA</b>{enviada[1]}</div>
        )}
        {!texto && !extraido && !enviada && !midia && <div className="text-[#98A2B3] italic">mensagem vazia</div>}
        {m.situacao_envio === "falhou" && (
          <div className="cv-falhou flex items-start gap-1.5" role="note">
            <AlertCircle className="size-3.5 mt-0.5 shrink-0" aria-hidden />
            <span><b>Não foi entregue.</b>{m.erro ? ` ${m.erro}` : ""}</span>
          </div>
        )}
        {m.autor !== "sistema" && (
          <div className="cv-rodape">
            <span>{hora(m.enviada_em)}</span>
            {nossa && <SituacaoEnvio situacao={m.situacao_envio} />}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/** O arquivo no balão: player nativo para áudio e vídeo, miniatura que amplia para imagem, link para documento.
 *  Se o arquivo não abrir (link vencido, fora do ar), vira um link para tentar abrir em outra aba. */
function ArquivoDaMidia({ url, forma, rotulo }: { url: string; forma: FormaMidia; rotulo: string }) {
  const [falhou, setFalhou] = useState(false);
  const [ampliada, setAmpliada] = useState(false);

  if (falhou || forma === "documento") {
    const nome = forma === "documento" ? nomeDoArquivo(url) : `${rotulo} (não carregou aqui)`;
    return (
      <a className="cv-arquivo" href={url} target="_blank" rel="noopener noreferrer nofollow" title="Abrir em outra aba">
        <span className="cv-arquivo-icone" aria-hidden>{falhou ? <AlertCircle /> : <FileText />}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold text-[#111B21]">{nome}</span>
          <span className="block text-[11px] text-[#667781]">{falhou ? "Abrir em outra aba" : "Documento · abrir"}</span>
        </span>
        <ExternalLink className="cv-arquivo-abrir" aria-hidden />
      </a>
    );
  }
  if (forma === "audio") {
    return <audio className="cv-audio" controls preload="none" src={url} onError={() => setFalhou(true)} aria-label={rotulo} />;
  }
  if (forma === "video") {
    return <video className="cv-video" controls preload="metadata" playsInline src={url} onError={() => setFalhou(true)} aria-label={rotulo} />;
  }
  return (
    <>
      <button type="button" className="cv-imagem" onClick={() => setAmpliada(true)} aria-label={`Ampliar ${rotulo.toLowerCase()}`}>
        <img src={url} alt={rotulo} loading="lazy" decoding="async" onError={() => setFalhou(true)} />
      </button>
      <Dialog open={ampliada} onOpenChange={setAmpliada}>
        <DialogContent className="cv-imagem-ampliada w-auto max-w-[min(92vw,1100px)] p-0 gap-2 border-0 bg-transparent shadow-none justify-items-center sm:rounded-none">
          <DialogTitle className="sr-only">{rotulo}</DialogTitle>
          <DialogDescription className="sr-only">Imagem da conversa em tamanho maior.</DialogDescription>
          <img src={url} alt={rotulo} />
          <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="cv-imagem-link"><ExternalLink aria-hidden />Abrir o original</a>
        </DialogContent>
      </Dialog>
    </>
  );
}

function SituacaoEnvio({ situacao }: { situacao: Mensagem["situacao_envio"] }) {
  if (situacao === "pendente") return <Clock aria-label="Enviando" />;
  if (situacao === "falhou") return <AlertCircle aria-label="Falhou" style={{ color: "#DC2626" }} />;
  if (situacao === "enviada") return <CheckCheck aria-label="Enviada" style={{ color: "#53BDEB" }} />;
  return <Check aria-label="Registrada" />;
}
