import { useRef, useState } from "react";
import { UploadCloud, File as FileIcon, X } from "lucide-react";
import { cn } from "@/lib/utils";

export const formatFileSize = (bytes: number) => {
  if (!bytes) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

interface FileUploadProps {
  /** Arquivos selecionados (controlado pelo pai). */
  files: File[];
  /** Recebe a nova lista de arquivos. */
  onChange: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  title?: string;
  hint?: string;
  className?: string;
}

/**
 * Zona de upload com drag & drop + lista de arquivos selecionados.
 * Componente controlado: o pai mantém `files` e decide quando enviar.
 */
export const FileUpload = ({
  files,
  onChange,
  accept,
  multiple = true,
  disabled = false,
  title = "Envie seus arquivos",
  hint = "Arraste os arquivos ou clique para selecionar",
  className,
}: FileUploadProps) => {
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (disabled) return;
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const addFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    const incoming = Array.from(list);
    onChange(multiple ? [...files, ...incoming] : incoming.slice(0, 1));
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (disabled) return;
    addFiles(e.dataTransfer.files);
  };

  const removeFile = (index: number) => onChange(files.filter((_, i) => i !== index));

  return (
    <div className={cn("w-full", className)}>
      <div className="mb-3 text-center">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>

      <form onDragEnter={handleDrag} onSubmit={(e) => e.preventDefault()} className="relative">
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
          className="hidden"
        />

        <div
          onClick={() => !disabled && inputRef.current?.click()}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={cn(
            "flex flex-col items-center justify-center w-full h-40 rounded-xl border-2 border-dashed transition-colors duration-200 cursor-pointer",
            disabled && "opacity-60 cursor-not-allowed",
            dragActive
              ? "border-primary bg-primary/10"
              : "border-border bg-muted/40 hover:bg-muted/70",
          )}
        >
          <UploadCloud className={cn("size-9 mb-2.5", dragActive ? "text-primary" : "text-muted-foreground")} />
          <p className="text-sm text-foreground font-medium">
            Arraste e solte ou <span className="text-primary">selecione</span>
          </p>
          <p className="text-xs text-muted-foreground mt-1">{hint}</p>
        </div>
      </form>

      {files.length > 0 && (
        <div className="mt-4 space-y-2">
          <h4 className="text-xs font-medium text-muted-foreground">
            {files.length} arquivo{files.length > 1 ? "s" : ""} selecionado{files.length > 1 ? "s" : ""}
          </h4>
          <div className="max-h-44 overflow-y-auto space-y-2 pr-1">
            {files.map((file, index) => (
              <div
                key={`${file.name}-${index}`}
                className="flex items-center justify-between p-2.5 bg-muted/30 border border-border rounded-lg group hover:border-primary/50 transition-colors"
              >
                <div className="flex items-center gap-3 overflow-hidden">
                  <div className="p-1.5 bg-background rounded text-primary shrink-0 border border-border/50">
                    <FileIcon className="size-4" />
                  </div>
                  <div className="flex flex-col overflow-hidden">
                    <span className="text-sm font-medium text-foreground truncate">{file.name}</span>
                    <span className="text-xs text-muted-foreground">{formatFileSize(file.size)}</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => removeFile(index)}
                  className="p-1.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-md transition-colors shrink-0"
                  aria-label="Remover arquivo"
                >
                  <X className="size-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default FileUpload;
