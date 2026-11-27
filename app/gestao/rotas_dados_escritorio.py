"""Dados do escritório e as etapas do CRM marcadas pelo próprio cliente (Primeiros passos do Início).

Dados do escritório: informações da firma guardadas UMA vez (agentesia_escritorios.config -> 'dados_escritorio') e
aplicadas a todos os agentes: na ativação, cada campo preenche os {{...}} do prompt que pedem a mesma coisa (a lista
`campos` diz quais nomes cada um preenche). Abre pelo passo "Dados do escritório" e por Ajustes › Dados do escritório.

Etapas do CRM: o cliente cria o painel na plataforma, volta e marca qual coluna é cada etapa da IA (as 6 colunas fixas
de app/gestao/painel_crm_padrao). Grava no mesmo lugar que o CRM automático e as automações leem
(integração "crm": id_painel, titulo_painel, etapas_por_tipo), via onboarding.guardar_painel.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gestao.rotas import GESTAO, Contexto, _repo

api = APIRouter(prefix="/api")

# chave, rótulo, ajuda, exemplo, e os {{nomes}} do prompt que este campo preenche (como aparecem no catálogo).
CAMPOS: list[dict[str, Any]] = [
    {"chave": "nome", "rotulo": "Escritório", "ajuda": "Nome comercial, como o cliente conhece", "exemplo": "Silva & Associados",
     "preenche": ["NOME ESCRITORIO", "Nome do Escritório", "escritorio", "NOME DO ESCRITORIO"]},
    {"chave": "responsavel", "rotulo": "Responsável", "ajuda": "Advogado(a) responsável", "exemplo": "Dra. Ana Silva",
     "preenche": ["ADVOGADO RESPONSAVEL", "Advogado responsável", "Nome do advogado"]},
    {"chave": "cnpj", "rotulo": "CNPJ", "ajuda": "Cadastro nacional", "exemplo": "00.000.000/0000-00", "preenche": ["CNPJ"]},
    {"chave": "oab", "rotulo": "OAB", "ajuda": "Registro (se houver)", "exemplo": "OAB/SP 123456", "preenche": ["OAB"]},
    {"chave": "telefone", "rotulo": "Telefone", "ajuda": "Telefone de contato do escritório", "exemplo": "(31) 3333-4444",
     "preenche": ["Telefone", "TELEFONE"]},
    {"chave": "email", "rotulo": "E-mail", "ajuda": "E-mail de contato", "exemplo": "contato@escritorio.com.br",
     "preenche": ["E-mail", "EMAIL"]},
    {"chave": "endereco", "rotulo": "Endereço", "ajuda": "Rua, número, bairro, cidade/UF, CEP",
     "exemplo": "Rua X, 100, Centro, Belo Horizonte/MG, 30000-000",
     "preenche": ["Endereço completo, cidade/UF, CEP", "Endereço", "ENDERECO"]},
    {"chave": "cidade", "rotulo": "Cidade", "ajuda": "Cidade/UF do escritório", "exemplo": "Belo Horizonte/MG",
     "preenche": ["CIDADE DO ESCRITORIO", "Cidade"]},
    {"chave": "instagram", "rotulo": "Instagram", "ajuda": "Perfil na rede social", "exemplo": "@escritorio",
     "preenche": ["@instagram", "Instagram"]},
    {"chave": "facebook", "rotulo": "Facebook", "ajuda": "Página ou perfil", "exemplo": "https://facebook.com/...",
     "preenche": ["Facebook"]},
    {"chave": "site", "rotulo": "Site", "ajuda": "Site oficial", "exemplo": "https://...",
     "preenche": ["Site oficial do escritório", "SITE ESCRITÓRIO", "SITE ESCRITORIO", "Site"]},
    {"chave": "youtube", "rotulo": "YouTube", "ajuda": "Canal do escritório", "exemplo": "https://youtube.com/@...",
     "preenche": ["Canal no YouTube"]},
    {"chave": "google", "rotulo": "Google Meu Negócio", "ajuda": "Link do perfil no Google", "exemplo": "https://g.page/...",
     "preenche": ["Google Meu Negócio"]},
    {"chave": "avaliacao_google", "rotulo": "Link de avaliação do Google", "ajuda": "Link para o cliente avaliar",
     "exemplo": "https://g.page/r/.../review", "preenche": ["LINK AVALIACAO GOOGLE", "Link de avaliação do Google"]},
    {"chave": "logo", "rotulo": "Logo", "ajuda": "Link da imagem do logo (Biblioteca de mídia ou site)", "exemplo": "https://...",
     "preenche": []},
]
CHAVES = {c["chave"] for c in CAMPOS}
MAX_CAMPO = 300


def _obj(valor: Any) -> dict[str, Any]:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor or "{}")
        except ValueError:
            return {}
    return valor if isinstance(valor, dict) else {}


async def ler_dados(pool: Any, id_escritorio: str) -> dict[str, str]:
    config = await pool.fetchval("select config from agentesia_escritorios where id = $1::uuid", id_escritorio)
    dados = _obj(_obj(config).get("dados_escritorio"))
    return {k: str(v) for k, v in dados.items() if k in CHAVES and isinstance(v, (str, int, float)) and str(v).strip()}


@api.get("/escritorio/dados")
async def ver_dados(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    valores = await ler_dados(_repo(pedido).pool, ctx.escritorio())
    return {"campos": CAMPOS, "valores": valores, "preenchido": bool(valores.get("nome"))}


class DadosEscritorio(BaseModel):
    valores: dict[str, str | None] = Field(default_factory=dict)


@api.put("/escritorio/dados")
async def salvar_dados(dados: DadosEscritorio, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    desconhecidas = set(dados.valores) - CHAVES
    if desconhecidas:
        raise HTTPException(400, f"Campo desconhecido: {', '.join(sorted(desconhecidas))}.")
    limpos = {k: " ".join(str(v).split())[:MAX_CAMPO] for k, v in dados.valores.items() if v and str(v).strip()}
    if not limpos.get("nome"):
        raise HTTPException(400, "Preencha pelo menos o nome do escritório.")
    repo = _repo(pedido)
    antes = await ler_dados(repo.pool, ctx.escritorio())
    await repo.pool.execute(
        """update agentesia_escritorios
              set config = coalesce(config, '{}'::jsonb) || jsonb_build_object('dados_escritorio', $2::jsonb)
            where id = $1::uuid""", ctx.escritorio(), json.dumps(limpos, ensure_ascii=False))
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_escritorios",
                                   id_registro=ctx.escritorio(), acao="alterou", resumo="Dados do escritório atualizados",
                                   antes=antes or None, depois=limpos)
    return {"campos": CAMPOS, "valores": limpos, "preenchido": True}


# ------------------------------------------------------------------ etapas do CRM
class EtapasCrm(BaseModel):
    id_painel: str = Field(min_length=1, max_length=100)
    titulo_painel: str = Field(default="", max_length=200)
    etapas_por_tipo: dict[str, str]


@api.put("/integracoes/crm/etapas")
async def salvar_etapas_crm(dados: EtapasCrm, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """O cliente marcou qual coluna do painel é cada etapa da IA. As colunas têm de ser do painel escolhido (lido de
    novo na plataforma) e todas as 6 etapas precisam de coluna."""
    from app.gestao import onboarding, painel_crm_padrao
    from app.gestao.rotas import paineis_crm
    tipos = set(painel_crm_padrao.TIPOS_NA_ORDEM)
    mapa = {t: str(c) for t, c in dados.etapas_por_tipo.items() if t in tipos and c}
    if set(dados.etapas_por_tipo) - tipos:
        raise HTTPException(400, "Etapa da IA desconhecida.")
    if len(mapa) != len(tipos):
        raise HTTPException(400, "Marque uma coluna do painel para cada etapa.")
    paineis = (await paineis_crm(pedido, ctx)).get("paineis") or []
    painel = next((p for p in paineis if str(p.get("id")) == dados.id_painel), None)
    if not painel:
        raise HTTPException(404, "Painel não encontrado no CRM desta conta. Leia os painéis de novo.")
    colunas = {str(e.get("id")) for e in painel.get("etapas") or []}
    if not set(mapa.values()) <= colunas:
        raise HTTPException(400, "Alguma coluna marcada não é deste painel.")
    repo = _repo(pedido)
    antes = (await repo.integracao(ctx.escritorio(), "crm") or {}).get("config")
    config = await onboarding.guardar_painel(repo, ctx.escritorio(), {"id": str(painel["id"]), "titulo": painel.get("titulo") or ""},
                                             mapa, titulo=dados.titulo_painel or painel.get("titulo"))
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_integracoes",
                                   id_registro=None, acao="alterou", resumo="Etapas do CRM marcadas nos Primeiros passos",
                                   antes=antes, depois=config)
    return config
