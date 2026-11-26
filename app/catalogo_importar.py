"""Importa o catálogo do agents-lawchat-main (tabelas sistemaia_* do Supabase AGENT WEAVER) para o nosso.

Entrada (qualquer combinação de arquivos):
  * o JSON de docs/EXPORTAR_CATALOGO.sql: {"sistemaia_biblioteca_produtos": [...], "sistemaia_biblioteca_agentes": [...], ...},
    também aceito dentro de {"catalogo": {...}} ou como CSV de uma célula só (coluna "catalogo");
  * um JSON por tabela (lista de linhas) com o nome da tabela no nome do arquivo;
  * CSV exportado do Table Editor (uma tabela por arquivo, nome da tabela no nome do arquivo; colunas jsonb em texto).
    CSV salvo pelo Excel (";" e Windows-1252, VERDADEIRO/FALSO) também é lido; linha com colunas a mais ou a menos é recusada.

Casamento dos produtos (re-importar nunca duplica nem mistura produtos):
  1. pelo id de lá guardado aqui (agentesia_biblioteca_produtos.id_origem);
  2. pelo mesmo id (produtos que já vieram de lá com o id de lá);
  3. pelo slug, só se o dono do slug aqui não é outro produto de lá.
  Um produto renomeado lá muda de endereço aqui; um produto novo lá que pegou o slug antigo vira produto novo aqui.

Mapeamento (mesmos nomes de coluna; o que muda):
  * agente: FAQ, objeções e regras do agente vão para config_modelo (faq_items {q,a}, objecoes {gatilho,resposta},
    rules_markdown), que é onde o editor do admin lê e grava;
  * follow-up do catálogo (sistemaia_biblioteca_followups) vai para padrao_followup.agentes[etapa] do produto;
    sem a tabela no arquivo, os follow-ups daqui ficam; sem a coluna padrao_followup, a cadência daqui fica;
  * conhecimento padrão vira agentesia_documentos (travado, origem 'produto', id_externo = id de lá); documento
    desligado ou que sumiu de lá é desligado aqui — só os que vieram da importação, nunca os criados aqui no admin;
    arquivo que não baixou nesta rodada mantém a versão já importada;
  * frases de transferência casadas por (produto, destino); texto novo é repassado aos agentes já ativados daquele produto;
    frase fora do padrão lá não apaga a daqui; frases gerais daqui só são sincronizadas se o arquivo trouxer frases gerais.
O download de arquivo de documento sem texto só acessa o Storage do Supabase (https, *.supabase.co/storage/v1/object/),
com limite de tamanho e de tempo. Re-importar não regrava o que não mudou (não mexe no updated_at à toa, o que descartaria
rascunhos de ativação dos escritórios). `simular=True` só devolve o plano.

Linha de comando:
  .venv/Scripts/python -m app.catalogo_importar catalogo.json [mais arquivos] [--simular]
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import asyncpg

TABELAS = ("sistemaia_biblioteca_produtos", "sistemaia_biblioteca_agentes", "sistemaia_frases_troca",
           "sistemaia_biblioteca_followups", "sistemaia_biblioteca_conhecimento")
PAPEIS = ("sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado")
JSONB_ORIGEM = {"etiquetas", "blocos_prompt", "config_modelo", "exemplos", "casos_de_uso", "padrao_followup", "faq",
                "objecoes", "regras_handoff"}
BOOLEANOS = ("publicado", "oferece_periodo_graca", "ativo", "habilitado_padrao")
CAMPOS_PRODUTO = ("slug", "nome", "categoria", "idioma", "icone", "capa_gradiente", "capa_imagem_url", "descricao_curta",
                  "descricao_longa", "etiquetas", "blocos_prompt", "modelo_recomendado", "config_modelo",
                  "mensagem_boas_vindas", "mensagem_despedida", "mensagem_fallback", "mensagem_fora_horario", "exemplos",
                  "casos_de_uso", "plano_minimo", "status", "versao", "padrao_followup", "faq", "objecoes",
                  "regras_markdown", "dados_escritorio", "modo_midia", "oferece_periodo_graca")
TEXTOS_PRODUTO = {"categoria", "idioma", "icone", "capa_gradiente", "capa_imagem_url", "descricao_curta", "descricao_longa",
                  "modelo_recomendado", "mensagem_boas_vindas", "mensagem_despedida", "mensagem_fallback",
                  "mensagem_fora_horario", "plano_minimo", "versao", "regras_markdown", "dados_escritorio"}
CAMPOS_AGENTE = ("nome_exibicao", "descricao", "icone", "ordem", "blocos_prompt", "texto_prompt", "mensagem_boas_vindas",
                 "mensagem_despedida", "mensagem_fallback", "modelo_recomendado", "config_modelo", "regras_handoff")
TEXTOS_AGENTE = {"descricao", "icone", "texto_prompt", "mensagem_boas_vindas", "mensagem_despedida", "mensagem_fallback",
                 "modelo_recomendado"}
LIMITE_DOCUMENTO = 400_000              # o mesmo corte do envio pelo admin (app/conhecimento.py)
LIMITE_DOWNLOAD = 8 * 1024 * 1024       # o mesmo limite de arquivo do admin
PRAZO_POR_ARQUIVO_S = 30
PRAZO_DOWNLOADS_S = 90                  # todos os downloads de uma importação juntos
_NS = uuid.UUID("6f1c2b1e-9c1a-4c5e-9a7d-4d1b8a0c2e51")     # ids estáveis para o que lá não é uuid
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_AVISOS = "_avisos"                     # avisos da leitura dos arquivos (vão para o plano)


class ErroImportacao(ValueError):
    pass


@dataclass
class Plano:
    produtos: list[dict[str, Any]] = field(default_factory=list)   # {slug, nome, status, acao, agentes, documentos, frases, followups}
    frases_globais: int = 0
    avisos: list[str] = field(default_factory=list)
    aplicado: bool = False

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------- utilitários
def _txt(valor: Any) -> str:
    """Texto de qualquer coisa que veio do arquivo (números, listas e None também)."""
    if valor is None:
        return ""
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False)
    return str(valor).strip()


def _int(valor: Any, padrao: int = 0) -> int:
    """Número vindo de JSON/CSV/planilha: aceita '1', '1.0', 1.0, vazio (padrão)."""
    if valor is None or isinstance(valor, bool):
        return padrao
    try:
        return int(float(str(valor).strip().replace(",", ".")))
    except (TypeError, ValueError, OverflowError):
        return padrao


def _verdadeiro(valor: Any, padrao: bool = False) -> bool:
    if valor is None:
        return padrao
    if isinstance(valor, bool):
        return valor
    texto = str(valor).strip().lower()
    if texto in ("true", "t", "1", "sim", "yes", "verdadeiro", "v"):
        return True
    if texto in ("false", "f", "0", "nao", "não", "no", "falso"):
        return False
    return padrao


def _lista(valor: Any) -> list:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except json.JSONDecodeError:
            return []
    return valor if isinstance(valor, list) else []


def _obj(valor: Any) -> dict:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except json.JSONDecodeError:
            return {}
    return valor if isinstance(valor, dict) else {}


def _data(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


def _slug(texto: Any) -> str:
    """Mesma normalização do admin, sem cortar: dois slugs longos de lá não podem virar um só aqui."""
    import unicodedata
    sem = unicodedata.normalize("NFKD", _txt(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", sem).strip("-")


def _j(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


def _id_la(linha: dict[str, Any]) -> str:
    return _txt(linha.get("id"))


# ---------------------------------------------------------------------------- leitura dos arquivos
def _tabela_pelo_nome(nome: str) -> str | None:
    base = nome.lower()
    for tabela in sorted(TABELAS, key=len, reverse=True):
        if tabela in base or tabela.replace("sistemaia_", "") in base:
            return tabela
    return None


def _juntar(destino: dict[str, list], tabela: str, linhas: Any) -> None:
    if not isinstance(linhas, list):
        raise ErroImportacao(f"{tabela}: esperava uma lista de linhas.")
    destino.setdefault(tabela, []).extend(l for l in linhas if isinstance(l, dict))


def _json(texto: str, nome: str) -> Any:
    try:
        return json.loads(texto)
    except json.JSONDecodeError as erro:
        raise ErroImportacao(f"{nome}: JSON inválido ou cortado ({erro.msg}, linha {erro.lineno}, coluna {erro.colno}). "
                             "Baixe o resultado da consulta de novo.") from erro


def _do_json(objeto: Any, nome: str, destino: dict[str, list]) -> None:
    if isinstance(objeto, list) and len(objeto) == 1 and isinstance(objeto[0], dict) and "catalogo" in objeto[0]:
        objeto = objeto[0]                                   # resultado do SQL Editor copiado como linha
    if isinstance(objeto, dict) and "catalogo" in objeto:
        objeto = objeto["catalogo"]
        if isinstance(objeto, str):
            objeto = _json(objeto, nome)
    if isinstance(objeto, dict) and any(t in objeto for t in TABELAS):
        for tabela in TABELAS:
            if tabela in objeto and objeto[tabela] is not None:
                _juntar(destino, tabela, objeto[tabela])
        return
    if isinstance(objeto, list):
        tabela = _tabela_pelo_nome(nome)
        if not tabela:
            raise ErroImportacao(f"{nome}: não sei de qual tabela é esta lista (ponha o nome da tabela no nome do arquivo).")
        _juntar(destino, tabela, objeto)
        return
    raise ErroImportacao(f"{nome}: formato não reconhecido (use o JSON de docs/EXPORTAR_CATALOGO.sql).")


def _separador(texto: str) -> str:
    """Separador pela linha de cabeçalho (o Sniffer erra quando os textos têm ';' e ',' dentro das aspas)."""
    cabecalho = texto.split("\n", 1)[0]
    contagens = {s: cabecalho.count(s) for s in (",", ";", "\t")}
    return max(contagens, key=lambda s: contagens[s]) if max(contagens.values()) else ","


def _do_csv(texto: str, nome: str, destino: dict[str, list]) -> None:
    csv.field_size_limit(2**31 - 1)
    # CSV íntegro tem número par de aspas (as de dentro do texto vêm dobradas). Ímpar = cortado no meio de um texto:
    # sem isto o leitor fecharia o campo pela metade e o texto truncado substituiria o bom.
    if texto.count('"') % 2:
        raise ErroImportacao(f"{nome}: o CSV parece cortado no meio de um texto (aspas sem fechar). Exporte de novo pelo Supabase.")
    leitor =csv.reader(io.StringIO(texto), delimiter=_separador(texto), quotechar='"', doublequote=True, strict=False)
    try:
        linhas = [l for l in leitor if any(c.strip() for c in l)]
    except csv.Error as erro:
        raise ErroImportacao(f"{nome}: CSV ilegível ({erro}).") from erro
    if not linhas:
        raise ErroImportacao(f"{nome}: arquivo vazio.")
    colunas = [c.strip() for c in linhas[0]]
    if len(colunas) == 1 and colunas[0].lower() in ("catalogo", "json_build_object"):
        if len(linhas) < 2:
            raise ErroImportacao(f"{nome}: a coluna catalogo veio vazia.")
        _do_json(_json(linhas[1][0], nome), nome, destino)
        return
    tabela = _tabela_pelo_nome(nome)
    if not tabela:
        raise ErroImportacao(f"{nome}: CSV sem o nome da tabela no nome do arquivo.")
    if len(colunas) < 2:
        raise ErroImportacao(f"{nome}: o CSV veio com uma coluna só ({colunas[0]}); confira o separador (vírgula ou ponto e vírgula).")
    convertidas = []
    for numero, valores in enumerate(linhas[1:], start=2):
        if len(valores) != len(colunas):
            raise ErroImportacao(f"{nome}, linha {numero}: {len(valores)} campos para {len(colunas)} colunas. "
                                 "O arquivo parece corrompido (aberto e salvo em planilha?); exporte de novo pelo Supabase.")
        nova: dict[str, Any] = {}
        for chave, valor in zip(colunas, valores):
            if not chave:
                continue
            if valor == "":
                nova[chave] = None
            elif chave in JSONB_ORIGEM:
                try:
                    nova[chave] = json.loads(valor)
                except json.JSONDecodeError:
                    nova[chave] = valor
            elif chave in BOOLEANOS:
                nova[chave] = _verdadeiro(valor, None)  # type: ignore[arg-type]
            else:
                nova[chave] = valor
        convertidas.append(nova)
    _juntar(destino, tabela, convertidas)


def ler_arquivos(arquivos: list[tuple[str, bytes]]) -> dict[str, list[dict[str, Any]]]:
    """[(nome, conteúdo)] -> {tabela: [linhas]} (+ "_avisos" com o que vale contar ao admin)."""
    dados: dict[str, list] = {_AVISOS: []}
    for nome, conteudo in arquivos:
        try:
            texto = conteudo.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = conteudo.decode("cp1252", errors="replace")
            dados[_AVISOS].append(f"{nome}: não estava em UTF-8 (parece salvo pelo Excel); acentos foram lidos como Windows-1252. "
                                  "Confira os textos depois de importar.")
        if not texto.strip():
            raise ErroImportacao(f"{nome}: arquivo vazio.")
        if texto.lstrip()[0] in "[{":
            _do_json(_json(texto.strip(), nome), nome, dados)
        else:
            # Só as quebras de linha das pontas: o TAB final da última linha é um campo vazio, não sobra.
            _do_csv(texto.strip("\r\n"), nome, dados)
    produtos = dados.get("sistemaia_biblioteca_produtos") or []
    if not produtos:
        raise ErroImportacao("Nenhum produto encontrado nos arquivos (falta sistemaia_biblioteca_produtos).")
    sem_nome = [p for p in produtos if not _txt(p.get("slug")) and not _txt(p.get("nome"))]
    if sem_nome:
        raise ErroImportacao(f"{len(sem_nome)} produto(s) sem slug e sem nome. O arquivo parece corrompido "
                             "(CSV aberto e salvo em planilha?). Exporte de novo pelo Supabase.")
    sem_id = [p for p in produtos if not _id_la(p)]
    if sem_id:
        raise ErroImportacao(f"{len(sem_id)} produto(s) sem id. Exporte pelo docs/EXPORTAR_CATALOGO.sql (o id liga os agentes, "
                             "documentos e frases ao produto).")
    ids = [_id_la(p) for p in produtos]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise ErroImportacao(f"Produto repetido no arquivo (mesmo id): {', '.join(repetidos)}.")
    # O id do documento vira o id dele aqui: sem id (ou repetido) dois documentos se sobrescreveriam, até entre produtos.
    documentos = dados.get("sistemaia_biblioteca_conhecimento") or []
    docs_sem_id = [d for d in documentos if not _txt(d.get("id"))]
    if docs_sem_id:
        raise ErroImportacao(f"{len(docs_sem_id)} documento(s) de conhecimento sem id. Exporte pelo docs/EXPORTAR_CATALOGO.sql "
                             "com todas as colunas.")
    ids_docs = [_txt(d.get("id")) for d in documentos]
    docs_repetidos = sorted({i for i in ids_docs if ids_docs.count(i) > 1})
    if docs_repetidos:
        raise ErroImportacao(f"Documento de conhecimento repetido no arquivo (mesmo id): {', '.join(docs_repetidos[:10])}.")
    return dados


# ---------------------------------------------------------------------------- normalização
def _status(p: dict[str, Any]) -> str:
    status = _txt(p.get("status"))
    if status in ("rascunho", "em_breve", "publicado"):
        return status
    return "publicado" if _verdadeiro(p.get("publicado")) else "rascunho"


def normalizar_produto(p: dict[str, Any]) -> dict[str, Any]:
    saida = {c: p.get(c) for c in CAMPOS_PRODUTO if c in p}
    for c in TEXTOS_PRODUTO & set(saida):
        saida[c] = _txt(saida[c]) or None
    saida["slug"] = _slug(p.get("slug") or p.get("nome")) or "produto"
    saida["nome"] = _txt(p.get("nome")) or saida["slug"]
    saida["status"] = _status(p)
    for c in ("etiquetas", "blocos_prompt", "exemplos", "casos_de_uso", "faq", "objecoes"):
        if c in saida:
            saida[c] = _lista(saida[c])
    for c in ("config_modelo", "padrao_followup"):
        if c in saida:
            saida[c] = _obj(saida[c])
    if saida.get("modo_midia") not in ("texto", "audio"):
        saida["modo_midia"] = "texto"
    saida["oferece_periodo_graca"] = _verdadeiro(p.get("oferece_periodo_graca"))
    saida["descricao_curta"] = saida.get("descricao_curta") or ""
    saida["categoria"] = saida.get("categoria") or "Previdenciário"
    saida["modelo_recomendado"] = saida.get("modelo_recomendado") or "gpt-4.1-mini"
    saida["versao"] = saida.get("versao") or "1.0.0"
    if not saida.get("idioma"):
        saida.pop("idioma", None)
    return saida


def normalizar_agente(a: dict[str, Any]) -> dict[str, Any]:
    saida = {c: a.get(c) for c in CAMPOS_AGENTE if c in a}
    for c in TEXTOS_AGENTE & set(saida):
        saida[c] = _txt(saida[c]) or None
    saida["blocos_prompt"] = _lista(a.get("blocos_prompt"))
    saida["regras_handoff"] = _lista(a.get("regras_handoff"))
    config = _obj(a.get("config_modelo"))
    # FAQ/objeções/regras do agente (colunas da mig 0079): onde o editor do admin daqui lê e grava.
    faq = _lista(a.get("faq"))
    if faq:
        config["faq_items"] = [{"q": _txt(f.get("pergunta") or f.get("q")), "a": _txt(f.get("resposta") or f.get("a"))}
                               for f in faq if isinstance(f, dict)]
    objecoes = _lista(a.get("objecoes"))
    if objecoes:
        config["objecoes"] = [{"gatilho": _txt(o.get("titulo") or o.get("gatilho")), "resposta": _txt(o.get("resposta"))}
                              for o in objecoes if isinstance(o, dict)]
    if _txt(a.get("regras_gerais")):
        config["rules_markdown"] = _txt(a.get("regras_gerais"))
    saida["config_modelo"] = config
    saida["nome_exibicao"] = _txt(a.get("nome_exibicao")) or _txt(a.get("papel"))
    saida["ordem"] = _int(a.get("ordem"))
    saida["modelo_recomendado"] = saida.get("modelo_recomendado") or "gpt-4.1-mini"
    return saida


def _prompt_do_agente(a: dict[str, Any]) -> str:
    blocos = _lista(a.get("blocos_prompt"))
    texto = " ".join(_txt(b.get("content")) for b in blocos if isinstance(b, dict) and b.get("type") != "handoff_trigger")
    return (texto + " " + _txt(a.get("texto_prompt"))).strip()


def _frase_valida(frase: str) -> bool:
    return 8 <= len(frase) <= 400 and "\n" not in frase and not re.search(r'[@{}"\\\[\]]', frase)


_EXTENSOES = {"pdf": "pdf", "docx": "docx", "xlsx": "xlsx", "txt": "texto", "md": "texto", "markdown": "texto", "csv": "texto", "json": "texto"}
_MIMES = {"application/pdf": "pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx"}


def formato_do_documento(d: dict[str, Any]) -> str:
    """pdf | docx | xlsx | texto (os formatos que o resto do sistema entende)."""
    if _txt(d.get("tipo")) != "arquivo":
        return "texto"
    nome = _txt(d.get("arquivo_nome") or d.get("nome"))
    extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if extensao in _EXTENSOES:
        return _EXTENSOES[extensao]
    return _MIMES.get(_txt(d.get("arquivo_mime")).split(";")[0].strip().lower(), "texto")


def _documento_ativo(d: dict[str, Any]) -> bool:
    return _verdadeiro(d.get("ativo"), True)


def _documento_entra(d: dict[str, Any]) -> bool:
    return _documento_ativo(d) and bool(_txt(d.get("conteudo")) or _txt(d.get("arquivo_url")))


def _id_documento(d: dict[str, Any]) -> str:
    return str(uuid.uuid5(_NS, f"conhecimento:{_txt(d.get('id'))}"))


# ---------------------------------------------------------------------------- casar produtos
def casar_produtos(produtos: list[dict[str, Any]], existentes: list[dict[str, Any]] | dict[str, str]) -> tuple[dict[str, tuple[str, str | None]], list[str]]:
    """{id de lá: (slug normalizado, id daqui ou None se é novo)} e os avisos.

    existentes = [{id, slug, id_origem}] do nosso catálogo (ou {id: slug}). Duas passadas: primeiro os que casam
    pelo id (de origem ou o mesmo id) ficam reservados; depois casa pelo slug só quando o dono do slug aqui não foi
    reservado por outro produto do arquivo e não pertence a outro produto de lá."""
    if isinstance(existentes, dict):
        existentes = [{"id": i, "slug": s, "id_origem": None} for i, s in existentes.items()]
    por_id = {str(e["id"]).lower(): e for e in existentes}
    por_origem = {str(e["id_origem"]): e for e in existentes if e.get("id_origem")}
    por_slug = {e["slug"]: e for e in existentes}
    avisos: list[str] = []
    resultado: dict[str, tuple[str, str | None]] = {}
    slugs_do_arquivo: dict[str, str] = {}
    for p in produtos:
        slug = normalizar_produto(p)["slug"]
        if slug in slugs_do_arquivo and slugs_do_arquivo[slug] != _id_la(p):
            raise ErroImportacao(f"Dois produtos do arquivo ficam com o mesmo endereço '{slug}' ({slugs_do_arquivo[slug]} e {_id_la(p)}). "
                                 "Ajuste o slug de um deles lá e exporte de novo.")
        slugs_do_arquivo[slug] = _id_la(p)
    reservados: dict[str, str] = {}                       # id daqui -> id de lá
    for p in produtos:                                    # 1ª passada: pelo id
        id_la = _id_la(p)
        dono = por_origem.get(id_la) or (por_id.get(id_la.lower()) if _UUID.match(id_la) else None)
        if dono and dono.get("id_origem") and str(dono["id_origem"]) != id_la:
            dono = None                                   # mesmo uuid, mas é outro produto de lá
        if dono:
            reservados[str(dono["id"]).lower()] = id_la
            resultado[id_la] = (normalizar_produto(p)["slug"], str(dono["id"]).lower())
    for p in produtos:                                    # 2ª passada: pelo slug
        id_la = _id_la(p)
        if id_la in resultado:
            continue
        slug = normalizar_produto(p)["slug"]
        dono = por_slug.get(slug)
        if dono and str(dono["id"]).lower() not in reservados and not (dono.get("id_origem") and str(dono["id_origem"]) != id_la):
            reservados[str(dono["id"]).lower()] = id_la
            resultado[id_la] = (slug, str(dono["id"]).lower())
        else:
            resultado[id_la] = (slug, None)
    # O slug novo de cada produto não pode ser de um produto daqui que fica com ele.
    slug_final = {id_aqui: resultado[id_la][0] for id_aqui, id_la in reservados.items()}
    for id_la, (slug, id_aqui) in resultado.items():
        dono = por_slug.get(slug)
        if not dono or str(dono["id"]).lower() == id_aqui:
            continue
        id_dono = str(dono["id"]).lower()
        if id_dono in slug_final and slug_final[id_dono] != slug:
            continue                                      # o dono atual também muda de endereço nesta importação
        raise ErroImportacao(f"O endereço '{slug}' já é de outro produto aqui ('{dono['slug']}'). "
                             "Troque o slug de um deles antes de importar.")
    for id_la, (slug, id_aqui) in resultado.items():
        if id_aqui and por_id.get(id_aqui) and por_id[id_aqui]["slug"] != slug:
            avisos.append(f"O endereço muda de '{por_id[id_aqui]['slug']}' para '{slug}'.")
    return resultado, avisos


# ---------------------------------------------------------------------------- planejar
def planejar(dados: dict[str, list[dict[str, Any]]], existentes: list[dict[str, Any]] | dict[str, str] | None = None) -> Plano:
    """O que a importação vai fazer (sem banco). existentes = [{id, slug, id_origem}] do nosso catálogo."""
    if isinstance(existentes, dict):
        existentes = [{"id": i, "slug": s, "id_origem": None} for i, s in existentes.items()]
    existentes = existentes or []
    plano = Plano(avisos=list(dados.get(_AVISOS) or []))
    produtos = dados.get("sistemaia_biblioteca_produtos", [])
    casamento, avisos_casamento = casar_produtos(produtos, existentes)
    plano.avisos.extend(avisos_casamento)
    ids_la = {_id_la(p) for p in produtos}
    ids_aqui = {str(e["id"]).lower() for e in existentes}
    origens_aqui = {str(e["id_origem"]) for e in existentes if e.get("id_origem")}
    for p in produtos:
        n = normalizar_produto(p)
        id_la = _id_la(p)
        do_produto = lambda t: [x for x in dados.get(t, []) if _txt(x.get("id_produto_biblioteca")) == id_la]  # noqa: E731
        agentes = do_produto("sistemaia_biblioteca_agentes")
        papeis_ok = [a for a in agentes if a.get("papel") in PAPEIS]
        for a in agentes:
            if a.get("papel") not in PAPEIS:
                plano.avisos.append(f"{n['nome']}: agente com papel '{_txt(a.get('papel'))}' não existe aqui e foi ignorado.")
            elif not _prompt_do_agente(a):
                plano.avisos.append(f"{n['nome']}: o prompt do agente {a.get('papel')} está vazio.")
        documentos = do_produto("sistemaia_biblioteca_conhecimento")
        for d in documentos:
            if not _documento_ativo(d):
                continue
            conteudo = _txt(d.get("conteudo"))
            if not conteudo:
                plano.avisos.append(f"{n['nome']}: documento '{_txt(d.get('nome'))}' sem texto"
                                    + (" (vou tentar baixar o arquivo)." if _txt(d.get("arquivo_url")) else " e será ignorado."))
            elif len(conteudo) > LIMITE_DOCUMENTO:
                plano.avisos.append(f"{n['nome']}: documento '{_txt(d.get('nome'))}' tem {len(conteudo):,} caracteres; "
                                    f"entram os primeiros {LIMITE_DOCUMENTO:,}.".replace(",", "."))
        frases = do_produto("sistemaia_frases_troca")
        for f in frases:
            if not _frase_valida(_txt(f.get("frase"))):
                plano.avisos.append(f"{n['nome']}: frase de transferência para {_txt(f.get('etapa_destino'))} fora do padrão e ignorada "
                                    "(a que já estava aqui para esse destino fica).")
        if "id_produto_base" in p:
            base = _txt(p.get("id_produto_base"))
            if base and base == id_la:
                plano.avisos.append(f"{n['nome']}: aponta para si mesmo como produto-base; a variante fica sem vínculo.")
            elif base and base not in ids_la and base.lower() not in ids_aqui and base not in origens_aqui:
                plano.avisos.append(f"{n['nome']}: o produto-base ({base}) não está no arquivo nem aqui; a variante fica sem vínculo.")
        plano.produtos.append({
            "id_origem": id_la, "slug": n["slug"], "nome": n["nome"], "status": n["status"],
            "categoria": n["categoria"], "modo_midia": n["modo_midia"],
            "acao": "atualizar" if casamento[id_la][1] else "criar", "agentes": len(papeis_ok),
            "papeis": [a.get("papel") for a in sorted(papeis_ok, key=lambda a: _int(a.get("ordem")))],
            "documentos": len([d for d in documentos if _documento_entra(d)]),
            "frases": len([f for f in frases if _frase_valida(_txt(f.get("frase"))) and _txt(f.get("etapa_destino"))]),
            "followups": len(do_produto("sistemaia_biblioteca_followups")),
        })
    plano.frases_globais = len([f for f in dados.get("sistemaia_frases_troca", [])
                                if not _txt(f.get("id_produto_biblioteca")) and _frase_valida(_txt(f.get("frase")))])
    orfas = [x for t in TABELAS[1:] for x in dados.get(t, [])
             if _txt(x.get("id_produto_biblioteca")) and _txt(x.get("id_produto_biblioteca")) not in ids_la]
    if orfas:
        plano.avisos.append(f"{len(orfas)} linha(s) apontam para produto que não veio no arquivo e foram ignoradas.")
    return plano


# ---------------------------------------------------------------------------- download de arquivo de documento
def _url_permitida(url: str) -> bool:
    """Só o Storage do Supabase (de onde vêm os documentos do catálogo antigo): nada de rede interna."""
    from urllib.parse import urlparse
    try:
        partes = urlparse(url)
        host = (partes.hostname or "").lower()
        porta = partes.port                              # porta inválida (':99999', ':x') levanta aqui
    except ValueError:
        return False
    return (partes.scheme == "https" and re.fullmatch(r"[a-z0-9-]+\.supabase\.co", host) is not None
            and partes.path.startswith("/storage/v1/object/") and porta in (None, 443))


async def _baixar(url: str) -> bytes | None:
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False) as http:
        async with http.stream("GET", url, headers={"Accept-Encoding": "identity"}) as resposta:
            if resposta.status_code != 200 or _int(resposta.headers.get("content-length")) > LIMITE_DOWNLOAD:
                return None
            pedacos, total = [], 0
            async for pedaco in resposta.aiter_raw():
                total += len(pedaco)
                if total > LIMITE_DOWNLOAD:
                    return None
                pedacos.append(pedaco)
            return b"".join(pedacos)


async def _texto_do_arquivo(url: str, nome: str, mime: str | None) -> tuple[str, str] | None:
    """Documento padrão sem texto salvo: baixa o arquivo do Storage e lê. (texto, formato) ou None (nunca levanta)."""
    from app.midia.extrair import detectar_formato, extrair_texto
    if not _url_permitida(url):
        return None
    try:
        conteudo = await asyncio.wait_for(_baixar(url), PRAZO_POR_ARQUIVO_S)
        if not conteudo:
            return None
        formato = detectar_formato(conteudo, mime, nome)
        if formato not in ("pdf", "docx", "xlsx", "texto"):
            return None
        texto = await asyncio.to_thread(extrair_texto, conteudo, formato)     # PDF grande não trava o servidor
        return (texto, formato) if texto and texto.strip() else None
    except Exception:                                    # qualquer falha vira aviso, nunca erro 500
        return None


async def _baixar_documentos(dados: dict[str, list[dict[str, Any]]], ids_la: set[str], plano: Plano) -> dict[str, tuple[str, str]]:
    baixados: dict[str, tuple[str, str]] = {}
    por_url: dict[str, tuple[str, str] | None] = {}
    inicio = time.monotonic()
    for d in dados.get("sistemaia_biblioteca_conhecimento", []):
        url = _txt(d.get("arquivo_url"))
        if (_txt(d.get("id_produto_biblioteca")) not in ids_la or not _documento_ativo(d) or _txt(d.get("conteudo")) or not url):
            continue
        if url not in por_url:
            if not _url_permitida(url):
                plano.avisos.append(f"Documento '{_txt(d.get('nome'))}': o link do arquivo não é do Storage do Supabase e não foi baixado.")
                por_url[url] = None
            elif time.monotonic() - inicio > PRAZO_DOWNLOADS_S:
                por_url[url] = None
                plano.avisos.append(f"Documento '{_txt(d.get('nome'))}': tempo de download esgotado nesta importação.")
            else:
                por_url[url] = await _texto_do_arquivo(url, _txt(d.get("arquivo_nome") or d.get("nome")), _txt(d.get("arquivo_mime")) or None)
        if por_url[url]:
            baixados[_txt(d.get("id"))] = por_url[url]  # type: ignore[assignment]
    return baixados


# ---------------------------------------------------------------------------- aplicar
def _distinto(colunas: list[str], alias: str, primeiro_parametro: int) -> str:
    """'(t.a, t.b) is distinct from ($n::jsonb, $n+1)' — só grava quando muda (não mexe no updated_at à toa)."""
    esquerda = ", ".join(f"{alias}.{c}" for c in colunas)
    direita = ", ".join(f"${primeiro_parametro + i}{'::jsonb' if c in JSONB_ORIGEM else ''}" for i, c in enumerate(colunas))
    return f"({esquerda}) is distinct from ({direita})"


async def importar(pool: asyncpg.Pool, dados: dict[str, list[dict[str, Any]]], *, simular: bool = False,
                   criado_por: str | None = None, baixar_arquivos: bool = True) -> Plano:
    linhas_aqui = await pool.fetch("select id, slug, id_origem, padrao_followup from agentesia_biblioteca_produtos")
    existentes = [{"id": str(r["id"]), "slug": r["slug"], "id_origem": r["id_origem"]} for r in linhas_aqui]
    followup_aqui = {str(r["id"]): _obj(r["padrao_followup"]) for r in linhas_aqui}
    plano = planejar(dados, existentes)
    if simular:
        return plano
    produtos = dados.get("sistemaia_biblioteca_produtos", [])
    casamento, _ = casar_produtos(produtos, existentes)
    ids_la = {_id_la(p) for p in produtos}
    por_origem = {str(e["id_origem"]): str(e["id"]) for e in existentes if e.get("id_origem")}
    ids_aqui = {str(e["id"]).lower() for e in existentes}
    baixados = await _baixar_documentos(dados, ids_la, plano) if baixar_arquivos else {}
    async with pool.acquire() as conexao, conexao.transaction():
        mapa: dict[str, str] = {}                       # id de lá -> id daqui
        # Quem muda de endereço solta o slug antigo antes (dois produtos podem trocar de slug entre si).
        for id_la, (slug, id_aqui) in casamento.items():
            if id_aqui:
                await conexao.execute(
                    "update agentesia_biblioteca_produtos set slug = '__importando__' || id::text where id = $1::uuid and slug <> $2",
                    id_aqui, slug)
        # Primeiro os que já existem, depois os novos (o novo pode usar o slug que outro acabou de soltar).
        for p in sorted(produtos, key=lambda x: casamento[_id_la(x)][1] is None):
            id_la = _id_la(p)
            n = normalizar_produto(p)
            _, id_aqui = casamento[id_la]
            # Follow-up por etapa mora em padrao_followup.agentes: vem da tabela de follow-ups; sem ela, fica o daqui.
            seguimento = dict(n["padrao_followup"]) if "padrao_followup" in n else dict(followup_aqui.get(id_aqui or "", {}))
            linhas_fup = [u for u in dados.get("sistemaia_biblioteca_followups", [])
                          if _txt(u.get("id_produto_biblioteca")) == id_la and _txt(u.get("etapa"))]
            if "sistemaia_biblioteca_followups" in dados:
                if linhas_fup:
                    seguimento["agentes"] = {_txt(u["etapa"]): {"nome_agente": _txt(u.get("nome_agente")), "prompt": _txt(u.get("prompt")),
                                                                "habilitado_padrao": _verdadeiro(u.get("habilitado_padrao"), True),
                                                                "ordem": _int(u.get("ordem"))} for u in linhas_fup}
                else:
                    seguimento.pop("agentes", None)
            elif id_aqui and "agentes" in followup_aqui.get(id_aqui, {}):
                seguimento["agentes"] = followup_aqui[id_aqui]["agentes"]
            if "padrao_followup" in n or seguimento or id_aqui:
                n["padrao_followup"] = seguimento
            n["id_origem"] = id_la
            colunas = list(n)
            valores = [_j(n[c]) if c in JSONB_ORIGEM else n[c] for c in colunas]
            if id_aqui:
                sets = ", ".join(f"{c} = ${i + 2}{'::jsonb' if c in JSONB_ORIGEM else ''}" for i, c in enumerate(colunas))
                await conexao.execute(
                    f"update agentesia_biblioteca_produtos p set {sets} where p.id = $1::uuid and {_distinto(colunas, 'p', 2)}",
                    id_aqui, *valores)
            else:
                marcas = ", ".join(f"${i + 3}{'::jsonb' if c in JSONB_ORIGEM else ''}" for i, c in enumerate(colunas))
                usa_id = _UUID.match(id_la) and id_la.lower() not in ids_aqui
                id_aqui = str(await conexao.fetchval(
                    f"""insert into agentesia_biblioteca_produtos (id, criado_por, {', '.join(colunas)}, criado_em)
                        values (coalesce($1::uuid, gen_random_uuid()), $2::uuid, {marcas}, coalesce(${len(colunas) + 3}::timestamptz, now()))
                        returning id""",
                    id_la if usa_id else None, criado_por, *valores, _data(p.get("created_at"))))
            mapa[id_la] = id_aqui
        # Variante "· Mídia" aponta para o produto-base (texto): no arquivo, pelo id de lá guardado, ou o mesmo id aqui.
        for p in produtos:
            if "id_produto_base" not in p:
                continue
            base = _txt(p.get("id_produto_base"))
            id_aqui = mapa[_id_la(p)]
            alvo = (mapa.get(base) or por_origem.get(base) or (base.lower() if base.lower() in ids_aqui else None)) if base else None
            if alvo == id_aqui:
                alvo = None
            # Base nula lá, base que não está no arquivo nem aqui, ou o próprio produto: sem vínculo aqui (como a prévia avisa).
            await conexao.execute(
                """update agentesia_biblioteca_produtos set id_produto_base = $2::uuid
                   where id = $1::uuid and id_produto_base is distinct from $2::uuid""", id_aqui, alvo)
        # Agentes do funil: um por papel; papéis que não vieram no arquivo saem do produto (como ao salvar no admin).
        if "sistemaia_biblioteca_agentes" in dados:
            por_produto: dict[str, list[dict]] = {mapa[_id_la(p)]: [] for p in produtos}
            for a in dados.get("sistemaia_biblioteca_agentes", []):
                if _txt(a.get("id_produto_biblioteca")) in mapa and a.get("papel") in PAPEIS:
                    por_produto[mapa[_txt(a["id_produto_biblioteca"])]].append(a)
            for id_produto, agentes in por_produto.items():
                papeis = []
                for a in sorted(agentes, key=lambda x: _int(x.get("ordem"))):
                    n = normalizar_agente(a)
                    papeis.append(a["papel"])
                    colunas = list(n)
                    valores = [_j(n[c]) if c in JSONB_ORIGEM else n[c] for c in colunas]
                    marcas = ", ".join(f"${i + 3}{'::jsonb' if c in JSONB_ORIGEM else ''}" for i, c in enumerate(colunas))
                    atualiza = ", ".join(f"{c} = excluded.{c}" for c in colunas)
                    mudou = (f"({', '.join('agentesia_biblioteca_agentes.' + c for c in colunas)}) is distinct from "
                             f"({', '.join('excluded.' + c for c in colunas)})")
                    await conexao.execute(
                        f"""insert into agentesia_biblioteca_agentes (id_produto_biblioteca, papel, {', '.join(colunas)})
                            values ($1::uuid, $2, {marcas})
                            on conflict (id_produto_biblioteca, papel) do update set {atualiza} where {mudou}""",
                        id_produto, a["papel"], *valores)
                apagados = await conexao.execute(
                    "delete from agentesia_biblioteca_agentes where id_produto_biblioteca = $1::uuid and not (papel = any($2::text[]))",
                    id_produto, papeis)
                if apagados.split()[-1] != "0":
                    # Como no PUT do admin: papel que saiu muda o carimbo do produto, e o rascunho de ativação antigo
                    # (que ainda tem esse papel) é descartado no painel em vez de voltar com um agente que não existe mais.
                    await conexao.execute("update agentesia_biblioteca_produtos set atualizado_em = now() where id = $1::uuid", id_produto)
        # Frases de transferência (por produto ou gerais), casadas por destino; as que sumiram de lá saem daqui.
        if "sistemaia_frases_troca" in dados:
            frases = dados.get("sistemaia_frases_troca", [])
            tem_gerais = any(not _txt(f.get("id_produto_biblioteca")) for f in frases)
            destinos_por_produto: dict[str | None, set[str]] = {i: set() for i in mapa.values()}
            if tem_gerais:
                destinos_por_produto[None] = set()
            for f in frases:
                origem = _txt(f.get("id_produto_biblioteca")) or None
                destino = _txt(f.get("etapa_destino"))
                if (origem and origem not in mapa) or not destino:
                    continue
                id_produto = mapa.get(origem) if origem else None
                destinos_por_produto[id_produto].add(destino)     # frase fora do padrão não apaga a daqui
                frase = _txt(f.get("frase"))
                if not _frase_valida(frase):
                    continue
                anterior = await conexao.fetchval(
                    "select frase from agentesia_frases_troca where id_produto_biblioteca is not distinct from $1::uuid and etapa_destino = $2",
                    id_produto, destino)
                await conexao.execute(
                    """insert into agentesia_frases_troca (id_produto_biblioteca, etapa_destino, nome, frase, descricao, ordem)
                       values ($1::uuid, $2, $3, $4, $5, $6)
                       on conflict ((coalesce(id_produto_biblioteca, '00000000-0000-0000-0000-000000000000'::uuid)), etapa_destino)
                       do update set nome = excluded.nome, frase = excluded.frase, descricao = excluded.descricao, ordem = excluded.ordem
                       where (agentesia_frases_troca.nome, agentesia_frases_troca.frase, agentesia_frases_troca.descricao, agentesia_frases_troca.ordem)
                             is distinct from (excluded.nome, excluded.frase, excluded.descricao, excluded.ordem)""",
                    id_produto, destino, _txt(f.get("nome")) or destino, frase, _txt(f.get("descricao")) or None, _int(f.get("ordem")))
                if anterior and anterior != frase:
                    # Como no PUT de frases do admin: o texto novo entra nos prompts dos agentes já ativados daquele produto.
                    await conexao.execute(
                        """update agentesia_agente_etapas e set instrucao = replace(e.instrucao, $1, $2)
                           from agentesia_agentes a where a.id = e.id_agente and a.produto = 'catalogo'
                             and position($1 in e.instrucao) > 0
                             and ($3::uuid is null or a.config -> 'catalogo' ->> 'id_produto_biblioteca' = $3::text)""",
                        anterior, frase, id_produto)
            for id_produto, destinos in destinos_por_produto.items():
                await conexao.execute(
                    """delete from agentesia_frases_troca where id_produto_biblioteca is not distinct from $1::uuid
                       and not (etapa_destino = any($2::text[]))""", id_produto, sorted(destinos))
        # Conhecimento padrão do produto (travado; copiado para o agente quando o escritório ativa).
        if "sistemaia_biblioteca_conhecimento" in dados:
            # Pelo id (estável a partir do id de lá), não pelo produto: o documento pode ter mudado de produto lá.
            ja_importados = {str(r["id"]) for r in await conexao.fetch(
                "select id from agentesia_documentos where id_externo is not null and id_produto_biblioteca is not null and id = any($1::uuid[])",
                [_id_documento(d) for d in dados.get("sistemaia_biblioteca_conhecimento", [])])}
            ativos_por_produto: dict[str, list[str]] = {i: [] for i in mapa.values()}
            documentos = [d for d in dados.get("sistemaia_biblioteca_conhecimento", []) if _txt(d.get("id_produto_biblioteca")) in mapa]
            # Lá a lista sai por (ordem, id); a posição pelo id desempata a mesma ordem aqui.
            documentos.sort(key=lambda d: (_txt(d.get("id_produto_biblioteca")), _int(d.get("ordem")), _int(d.get("id"), 0), _txt(d.get("id"))))
            posicao: dict[str, int] = {}
            for d in documentos:
                id_produto = mapa[_txt(d["id_produto_biblioteca"])]
                posicao[id_produto] = posicao.get(id_produto, -1) + 1
                id_doc = _id_documento(d)
                if not _documento_ativo(d):
                    continue
                texto = _txt(d.get("conteudo"))
                formato = formato_do_documento(d)
                if not texto and _txt(d.get("id")) in baixados:
                    texto, formato = baixados[_txt(d.get("id"))]
                if not texto:
                    if id_doc in ja_importados:
                        # Mantém a versão que já tinha vindo — no produto de agora (o documento pode ter mudado de produto lá).
                        ativos_por_produto[id_produto].append(id_doc)
                        await conexao.execute(
                            """update agentesia_documentos set id_produto_biblioteca = $2::uuid, ordem = $3, ativo = true
                               where id = $1::uuid and (id_produto_biblioteca, ordem, ativo) is distinct from ($2::uuid, $3, true)""",
                            id_doc, id_produto, posicao[id_produto])
                        if _txt(d.get("arquivo_url")) and baixar_arquivos:
                            plano.avisos.append(f"Documento '{_txt(d.get('nome'))}': o arquivo não baixou agora; mantida a versão já importada.")
                    elif _txt(d.get("arquivo_url")) and baixar_arquivos:
                        plano.avisos.append(f"Não consegui ler o arquivo do documento '{_txt(d.get('nome'))}'; ficou de fora.")
                    continue
                texto = texto[:LIMITE_DOCUMENTO]
                ativos_por_produto[id_produto].append(id_doc)
                nome = (_txt(d.get("nome")) or _txt(d.get("arquivo_nome")) or "Documento")[:200]
                await conexao.execute(
                    """insert into agentesia_documentos (id, id_produto_biblioteca, id_externo, tipo, nome, formato, tamanho_bytes, texto,
                                                         caracteres, situacao, origem, travado, ordem, criado_por, criado_em)
                       values ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, length($8), 'pronto', 'produto', true, $9, $10::uuid,
                               coalesce($11::timestamptz, now()))
                       on conflict (id) do update set id_produto_biblioteca = excluded.id_produto_biblioteca, nome = excluded.nome,
                         texto = excluded.texto, caracteres = excluded.caracteres, tamanho_bytes = excluded.tamanho_bytes,
                         ordem = excluded.ordem, formato = excluded.formato, tipo = excluded.tipo, id_externo = excluded.id_externo, ativo = true
                       where (agentesia_documentos.id_produto_biblioteca, agentesia_documentos.nome, agentesia_documentos.texto,
                              agentesia_documentos.ordem, agentesia_documentos.formato, agentesia_documentos.tipo, agentesia_documentos.ativo)
                             is distinct from (excluded.id_produto_biblioteca, excluded.nome, excluded.texto, excluded.ordem,
                                               excluded.formato, excluded.tipo, true)""",
                    id_doc, id_produto, _txt(d.get("id")), "arquivo" if _txt(d.get("tipo")) == "arquivo" else "texto", nome, formato,
                    _int(d.get("arquivo_tamanho")) or len(texto.encode()), texto, posicao[id_produto], criado_por, _data(d.get("created_at")))
            # Documento desligado ou que sumiu de lá: desligado aqui. Só os que vieram da importação (id_externo);
            # os documentos padrão criados aqui pelo admin nunca são tocados.
            for id_produto, ativos in ativos_por_produto.items():
                await conexao.execute(
                    """update agentesia_documentos set ativo = false
                       where id_produto_biblioteca = $1::uuid and id_externo is not null and ativo and not (id = any($2::uuid[]))""",
                    id_produto, ativos)
    plano.aplicado = True
    return plano


# ---------------------------------------------------------------------------- linha de comando
async def _principal(argumentos: list[str]) -> int:
    simular = "--simular" in argumentos
    caminhos = [a for a in argumentos if not a.startswith("--")]
    if not caminhos:
        print(__doc__)
        return 2
    url = os.environ.get("AGENTESIA_BANCO_URL")
    if not url:
        print("Defina AGENTESIA_BANCO_URL (o banco do LawChat IA).")
        return 2
    arquivos = [(c, open(c, "rb").read()) for c in caminhos]
    try:
        dados = ler_arquivos(arquivos)
    except ErroImportacao as erro:
        print("Erro:", erro)
        return 1
    pool = await asyncpg.create_pool(url, min_size=1, max_size=1, statement_cache_size=0)
    try:
        plano = await importar(pool, dados, simular=simular)
    except ErroImportacao as erro:
        print("Erro:", erro)
        return 1
    finally:
        await pool.close()
    print(("SIMULAÇÃO (nada gravado)" if simular else "IMPORTADO") + f": {len(plano.produtos)} produto(s)")
    for p in plano.produtos:
        print(f"  - {p['acao']:9} {p['status']:9} {p['nome']} · agentes {p['agentes']} ({', '.join(p['papeis'])}) · "
              f"documentos {p['documentos']} · frases {p['frases']} · follow-ups {p['followups']}")
    if plano.frases_globais:
        print(f"  frases de transferência globais: {plano.frases_globais}")
    for aviso in plano.avisos:
        print("  ! " + aviso)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_principal(sys.argv[1:])))
