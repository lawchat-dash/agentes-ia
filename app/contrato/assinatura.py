"""Quem assinou e em que pé está a assinatura: identificar o lead entre os assinantes e ler o documento. Puro."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from app.canal.zapsign import Assinante, DocumentoZapSign

RECUSADO = ("refused", "rejected", "recusado", "cancelado", "canceled", "cancelled")
EXPIRADO = ("expired", "expirado")


def _ultimos8(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")[-8:]


def _nome(valor: str | None) -> str:
    texto = unicodedata.normalize("NFD", str(valor or ""))
    return " ".join("".join(c for c in texto if unicodedata.category(c) != "Mn").lower().split())


def identificar_lead(doc: DocumentoZapSign, token_assinante: str | None, telefone_lead: str | None,
                     id_externo: str | None = None, nome_lead: str | None = None) -> tuple[Assinante | None, str | None]:
    """Pelo token guardado na geração; senão pelos 8 últimos dígitos do telefone; senão pelo external_id do signatário;
    senão pelo nome (quando só um bate); senão o assinante único. Nunca 'o primeiro da lista'."""
    if token_assinante:
        achado = next((a for a in doc.assinantes if a.token == token_assinante), None)
        if achado:
            return achado, "token"
    fim = _ultimos8(telefone_lead)
    if len(fim) == 8:
        achados = [a for a in doc.assinantes if _ultimos8(a.telefone) == fim]
        if len(achados) == 1:
            return achados[0], "telefone"
    if id_externo:
        achados = [a for a in doc.assinantes if a.id_externo and a.id_externo == id_externo]
        if len(achados) == 1:
            return achados[0], "external_id"
    if nome_lead and _nome(nome_lead):
        achados = [a for a in doc.assinantes if _nome(a.nome) == _nome(nome_lead)]
        if len(achados) == 1:
            return achados[0], "nome"
    if len(doc.assinantes) == 1:
        return doc.assinantes[0], "unico"
    return None, None


def assinante_do_lead_na_geracao(doc: DocumentoZapSign, *, nome: str | None, telefone: str | None,
                                 id_externo: str | None) -> Assinante | None:
    """O signatário que criamos para o lead no create-doc (o modelo pode trazer o advogado antes dele)."""
    quem, _ = identificar_lead(doc, None, telefone, id_externo, nome)
    if quem is None and doc.assinantes:
        # Sem como diferenciar: o que não assinou ainda (o advogado do modelo às vezes já vem assinado) ou o primeiro.
        pendentes = [a for a in doc.assinantes if a.status != "signed"]
        quem = pendentes[0] if len(pendentes) == 1 else doc.assinantes[0]
    return quem


def _expirou(doc: DocumentoZapSign, agora: datetime | None) -> bool:
    if doc.status in EXPIRADO:
        return True
    if doc.prazo is None or doc.status == "signed":
        return False
    prazo = doc.prazo if doc.prazo.tzinfo else doc.prazo.replace(tzinfo=timezone.utc)
    return prazo < (agora or datetime.now(timezone.utc))


def situacao_da_assinatura(doc: DocumentoZapSign, lead: Assinante | None, agora: datetime | None = None) -> str:
    """assinado | excluido | cancelado | expirado | so_o_escritorio_assinou | pendente | nao_reconhecido.

    O lead assinado vale mais que tudo (assinou e depois alguém cancelou: a assinatura existe, a equipe decide).
    Excluído, cancelado/recusado e expirado vêm antes de 'pendente': nunca mandar o link de um documento morto."""
    if lead is not None and lead.status == "signed":
        return "assinado"
    if doc.excluido:
        return "excluido"
    if doc.status in RECUSADO or (lead is not None and lead.status in RECUSADO):
        return "cancelado"
    if _expirou(doc, agora):
        return "expirado"
    if lead is None:
        return "nao_reconhecido" if any(a.status == "signed" for a in doc.assinantes) else "pendente"
    if any(a.status == "signed" for a in doc.assinantes if a.token != lead.token):
        return "so_o_escritorio_assinou"
    return "pendente"


@dataclass(frozen=True)
class Leitura:
    """O que a releitura do documento diz, pronto para decidir a resposta e para a linha (sistema) da IA."""
    situacao: str                 # a de situacao_da_assinatura
    abertura: str                 # nunca_abriu | abriu_sem_assinar | assinou | desconhecida
    vezes_visto: int = 0
    ultimo_acesso: datetime | None = None
    motivo: str | None = None     # rejected_reason, quando cancelado

    def abriu_ha_menos_de(self, minutos: float, agora: datetime | None = None) -> bool:
        if self.ultimo_acesso is None:
            return False
        ultimo = self.ultimo_acesso if self.ultimo_acesso.tzinfo else self.ultimo_acesso.replace(tzinfo=timezone.utc)
        return ((agora or datetime.now(timezone.utc)) - ultimo).total_seconds() < minutos * 60

    def como_dict(self) -> dict[str, object]:
        return {"situacao": self.situacao, "abertura": self.abertura, "vezes_visto": self.vezes_visto,
                "ultimo_acesso": self.ultimo_acesso.isoformat() if self.ultimo_acesso else None, "motivo": self.motivo}


def ler(doc: DocumentoZapSign, lead: Assinante | None, agora: datetime | None = None) -> Leitura:
    situacao = situacao_da_assinatura(doc, lead, agora)
    if lead is None:
        abertura = "desconhecida"
    elif lead.status == "signed":
        abertura = "assinou"
    elif lead.vezes_visto > 0 or lead.ultimo_acesso is not None or lead.status == "link-opened":
        abertura = "abriu_sem_assinar"
    else:
        abertura = "nunca_abriu"
    return Leitura(situacao, abertura, lead.vezes_visto if lead else 0, lead.ultimo_acesso if lead else None,
                   doc.motivo_recusa)


def linha_para_ia(leitura: Leitura, quando: str | None = None) -> str:
    """Linha 'ASSINATURA DO CONTRATO (sistema)' para a IA responder certo, sem inventar."""
    em = f" (conferido na ZapSign {quando})" if quando else " (conferido na ZapSign)"
    s, a = leitura.situacao, leitura.abertura
    if s == "assinado":
        texto = "o lead JÁ ASSINOU. Confirme e agradeça; não mande link."
    elif s in ("cancelado", "excluido", "expirado"):
        nome = {"cancelado": "foi CANCELADO/RECUSADO", "excluido": "foi EXCLUÍDO", "expirado": "VENCEU"}[s]
        texto = (f"o contrato {nome} na ZapSign e não pode mais ser assinado. NÃO mande o link antigo e não prometa "
                 "um contrato novo: diga que a equipe vai falar com o lead por aqui.")
    elif s == "so_o_escritorio_assinou":
        texto = "o escritório já assinou; FALTA a assinatura do lead. O sistema reenvia o link; não diga que está assinado."
    elif s == "nao_reconhecido":
        texto = "houve uma assinatura que o sistema não reconheceu como do lead; a equipe vai conferir. Não confirme a assinatura."
    elif a == "abriu_sem_assinar":
        vezes = f" {leitura.vezes_visto} vez(es)" if leitura.vezes_visto else ""
        texto = (f"o lead ABRIU o link{vezes}, mas NÃO concluiu a assinatura. Pergunte onde travou (selfie, foto do "
                 "documento, código por SMS/WhatsApp) e ajude; não diga que está assinado.")
    elif a == "nunca_abriu":
        texto = "o lead AINDA NÃO ABRIU o link. O sistema reenvia o link; não diga que está assinado."
    else:
        texto = "a assinatura do lead AINDA NÃO consta. Não diga que está assinado."
    return f"ASSINATURA DO CONTRATO (sistema){em}: {texto}"
