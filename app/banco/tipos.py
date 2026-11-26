"""Tipos e contrato do repositório. O pipeline só conhece isto, não o Postgres."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.modelo import Chamada


@dataclass
class Escritorio:
    id: str
    nome: str
    ia_desligada: bool = False
    situacao: str = "ativo"            # ativo | suspenso | encerrado (cliente da LawChat)
    id_segredo_helena: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Canal:
    id: str
    id_escritorio: str
    numero_normalizado: str
    id_canal_helena: str | None = None
    ativo: bool = True
    tipo: str = "nao_oficial"          # oficial (API da Meta: janela de 24 h) | nao_oficial


@dataclass
class Etapa:
    id: str
    codigo: str
    principal: bool = False
    instrucao: str | None = None
    modelo: str | None = None


@dataclass
class Agente:
    id: str
    id_escritorio: str
    id_canal: str
    nome: str
    produto: str = "auxilio_acidente"
    situacao: str = "pausado"            # ativo | pausado
    modo: str = "teste"                  # teste | producao
    minutos_pausa_humano: int = 15
    config: dict[str, Any] = field(default_factory=dict)
    etapas: list[Etapa] = field(default_factory=list)
    numeros_teste: list[str] = field(default_factory=list)   # quem a IA responde em modo teste

    def etapa(self, codigo: str) -> Etapa | None:
        return next((e for e in self.etapas if e.codigo == codigo), None)

    def etapa_por_id(self, id_etapa: str | None) -> Etapa | None:
        return next((e for e in self.etapas if e.id == id_etapa), None)

    def principal(self) -> Etapa | None:
        return next((e for e in self.etapas if e.principal), None)


@dataclass
class Lead:
    id: str
    id_escritorio: str
    id_canal: str
    id_agente: str | None
    id_etapa: str | None
    telefone: str | None
    estado: str = "ativo"                # ativo | pausado | encerrado
    motivo_estado: str | None = None
    pausado_ate: datetime | None = None
    id_sessao_helena: str | None = None
    novo: bool = False                   # acabou de ser criado


@dataclass
class Mensagem:
    id: str
    autor: str
    tipo: str
    texto: str | None
    texto_extraido: str | None
    enviada_em: datetime
    id_turno: str | None = None
    id_externo: str | None = None
    url_midia: str | None = None
    midia_pendente_desde: datetime | None = None   # leitura de mídia em andamento (marca no banco, ver 005)

    def para_a_ia(self) -> str:
        return (self.texto_extraido or self.texto or "").strip()


class Repositorio(Protocol):
    async def registrar_recebido(self, *, origem: str, id_externo: str | None, tipo: str,
                                 payload: dict[str, Any], id_escritorio: str | None) -> bool: ...
    async def escritorio_por_conta(self, id_conta: str) -> Escritorio | None: ...
    async def escritorio(self, id_escritorio: str) -> Escritorio | None: ...
    async def canal_por_numero(self, id_escritorio: str, numero: str) -> Canal | None: ...
    async def canal(self, id_canal: str) -> Canal | None: ...
    async def agente_do_canal(self, id_canal: str) -> Agente | None: ...
    async def achar_ou_criar_lead(self, *, escritorio: Escritorio, canal: Canal, agente: Agente | None, nome: str | None = None,
                                  telefone: str, id_sessao: str | None) -> Lead: ...
    async def lead(self, id_lead: str) -> Lead | None: ...
    async def lead_por_sessao(self, id_escritorio: str, id_sessao: str) -> Lead | None: ...
    async def lead_do_contato(self, id_escritorio: str, id_canal: str, *, id_contato_helena: str | None = None,
                              telefone: str | None = None) -> Lead | None: ...
    async def ligar_eco_a_ia(self, id_escritorio: str, id_lead: str, *, id_externo: str, texto: str | None,
                             url_midia: str | None, minutos: int = 15) -> bool: ...
    async def eco_sem_dono(self, id_lead: str, *, texto: str | None, url_midia: str | None,
                           minutos: int = 15) -> str | None: ...
    async def atualizar_lead(self, id_lead: str, **campos: Any) -> None: ...
    async def gravar_mensagem(self, *, lead: Lead, autor: str, tipo: str, texto: str | None,
                              texto_extraido: str | None, url_midia: str | None, enviada_em: datetime,
                              id_externo: str | None, id_turno: str | None = None,
                              situacao_envio: str = "recebida", erro: str | None = None) -> str | None: ...
    async def registrar_fala_do_atendente(self, *, lead: Lead, tipo: str, texto: str | None, texto_extraido: str | None,
                                          url_midia: str | None, enviada_em: datetime, id_externo: str | None,
                                          pausa: dict[str, Any] | None, motivo_followup: str) -> str | None: ...
    async def esquecer_recebido(self, *, origem: str, id_externo: str | None, tipo: str) -> None: ...
    async def mensagem_e_da_ia(self, id_escritorio: str, id_externo: str) -> bool: ...
    async def lead_ja_escreveu(self, id_lead: str, *, antes_de: str | None = None) -> bool: ...
    async def ultima_mensagem_do_lead(self, id_lead: str) -> datetime | None: ...
    async def token_helena(self, id_escritorio: str) -> str | None: ...
    async def marcar_envio_falhou(self, *, id_escritorio: str, id_externo: str, erro: str) -> dict[str, Any] | None: ...
    async def mensagens_pendentes(self, id_lead: str) -> list[Mensagem]: ...
    async def historico(self, id_lead: str, limite: int = 40) -> list[Mensagem]: ...
    async def comeco_da_conversa(self, id_lead: str, *, janela: int = 40, limite: int = 60,
                                 corte: int = 600) -> dict[str, Any]: ...
    async def trecho_para_resumir(self, id_lead: str, *, janela: int = 40, limite: int = 150,
                                  corte: int = 1500) -> dict[str, Any]: ...
    async def gravar_resumo(self, *, id_lead: str, resumo: str, ate_id_mensagem: str, quantidade: int,
                            modelo: str, tokens: int | None) -> None: ...
    async def marcar_no_turno(self, ids_mensagens: list[str], id_turno: str) -> None: ...
    async def fatos_vigentes(self, id_lead: str) -> dict[str, Any]: ...
    async def gravar_fatos(self, *, lead: Lead, id_turno: str, fatos: list[dict[str, Any]]) -> None: ...
    async def abrir_turno(self, *, lead: Lead, modo: str, etapa_antes: str | None) -> str: ...
    async def fechar_turno(self, id_turno: str, *, situacao: str, motivo: str, etapa_depois: str | None,
                           contexto: dict[str, Any] | None, resposta: dict[str, Any] | None) -> None: ...
    async def gravar_chamadas(self, *, id_escritorio: str, id_turno: str | None, chamadas: list[Chamada],
                              id_lead: str | None = None) -> None: ...
    async def bloqueado_por_saldo(self, id_escritorio: str) -> bool: ...
    async def gasto_desde(self, id_escritorio: str, desde: datetime) -> float: ...
    async def gravar_origem(self, id_lead: str, origem: dict[str, Any]) -> bool: ...
    async def documentos_do_agente(self, id_agente: str) -> list[tuple[str, str]]: ...
    async def trechos_do_agente(self, id_agente: str) -> list[dict[str, Any]]: ...
    # Opcionais (o pipeline usa getattr): pergunta sem resposta na base e reindexação por modelo/dimensão diferente.
    # async def registrar_lacuna(self, *, id_escritorio, id_agente, papel, pergunta, id_lead=None, id_turno=None) -> dict | None
    # async def reindexar_base(self, id_agente, modelo, dimensoes) -> int
    # Robustez (o pipeline usa getattr quando é opcional):
    async def mensagem_por_id_externo(self, id_escritorio: str, id_externo: str) -> Mensagem | None: ...
    # async def responder_apos(self, id_lead) -> datetime | None            prazo de resposta gravado no banco
    # async def renovar_reserva(self, id_lead, segundos) -> None            estende processando_ate durante o envio
    # async def fechar_turnos_interrompidos(self, minutos) -> list[dict]     turnos 'processando' antigos viram 'erro'
    # async def marcar_midia_pendente(self, id_mensagem) / limpar_midia_pendente(self, id_mensagem)
    # async def nota_recente(self, id_lead, padroes, horas) -> bool          nota do lead com chave LIKE padrão nas últimas h
    # async def credito_restante(self, id_escritorio) -> float | None        % dos créditos da IA que ainda restam (pré-pago)
    async def nota_de_problema(self, *, id_escritorio: str, id_lead: str, tipo: str, texto: str) -> bool: ...
    async def atualizar_texto_extraido(self, id_mensagem: str, texto: str) -> None: ...
    async def eventos_com_aviso(self, id_escritorio: str) -> set[str]: ...
    async def agendar_followup(self, id_lead: str, base: datetime) -> None: ...
    async def marcar_resposta(self, id_lead: str, quando: datetime | None) -> None: ...
    async def fatos_do_sistema(self, id_lead: str) -> dict[str, Any]: ...
    async def reservar_lead(self, id_lead: str, segundos: int) -> bool: ...
    async def liberar_lead(self, id_lead: str) -> None: ...
    async def leads_aguardando(self, limite: int = 200) -> list[tuple[str, datetime]]: ...
    async def cancelar_followups(self, id_lead: str, motivo: str) -> None: ...
    async def gravar_eventos(self, *, id_escritorio: str | None, id_lead: str | None, id_turno: str | None,
                             eventos: list[dict[str, Any]]) -> None: ...
    async def segredo(self, id_segredo: str | None) -> str | None: ...
    async def config_crm(self, id_escritorio: str) -> dict[str, Any] | None: ...
    async def config_zapsign(self, id_escritorio: str) -> dict[str, Any]: ...
    async def enfileirar_acoes(self, *, id_escritorio: str, id_lead: str, id_turno: str,
                               acoes: list[dict[str, Any]]) -> None: ...
