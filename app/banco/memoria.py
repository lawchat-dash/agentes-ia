"""Repositório em memória: usado nos testes e no Laboratório, sem banco nenhum."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.banco.tipos import Agente, Canal, Escritorio, Lead, Mensagem
from app.modelo import Chamada


class RepositorioMemoria:
    def __init__(self) -> None:
        self._seq = itertools.count(1)
        self.escritorios: dict[str, Escritorio] = {}
        self.contas: dict[str, str] = {}                 # id_conta_helena -> id_escritorio
        self.canais: dict[str, Canal] = {}
        self.agentes: dict[str, Agente] = {}             # por id_canal
        self.leads: dict[str, Lead] = {}
        self.mensagens: dict[str, list[Mensagem]] = {}   # por id_lead
        self.fatos: dict[str, list[dict[str, Any]]] = {} # por id_lead (histórico completo)
        self.turnos: dict[str, dict[str, Any]] = {}
        self.chamadas: list[dict[str, Any]] = []
        self.eventos: list[dict[str, Any]] = []
        self.recebidos: set[tuple[str, str]] = set()
        self.segredos: dict[str, str] = {}
        self.crm: dict[str, dict[str, Any]] = {}          # config do CRM por escritório
        self.acoes: list[dict[str, Any]] = []
        self.etapas: list[dict[str, Any]] = []            # histórico de etapa (como agentesia_lead_etapas)

    def _id(self, prefixo: str) -> str:
        return f"{prefixo}-{next(self._seq)}"

    # ---- cadastro (usado para montar o cenário) ----
    def cadastrar(self, escritorio: Escritorio, canal: Canal, agente: Agente, id_conta: str | None = None) -> None:
        self.escritorios[escritorio.id] = escritorio
        if id_conta:
            self.contas[id_conta] = escritorio.id
        self.canais[canal.id] = canal
        self.agentes[canal.id] = agente

    # ---- contrato do repositório ----
    async def registrar_recebido(self, *, origem, id_externo, tipo, payload, id_escritorio) -> bool:
        if id_externo is None:
            return True
        chave = (origem, f"{tipo}:{id_externo}")
        if chave in self.recebidos:
            return False
        self.recebidos.add(chave)
        return True

    async def escritorio_por_conta(self, id_conta):
        return self.escritorios.get(self.contas.get(id_conta, ""))

    async def escritorio(self, id_escritorio):
        return self.escritorios.get(id_escritorio)

    async def canal_por_numero(self, id_escritorio, numero):
        return next((c for c in self.canais.values()
                     if c.id_escritorio == id_escritorio and c.numero_normalizado == numero and c.ativo), None)

    async def canal(self, id_canal):
        return self.canais.get(id_canal)

    async def agente_do_canal(self, id_canal):
        return self.agentes.get(id_canal)

    async def achar_ou_criar_lead(self, *, escritorio, canal, agente, telefone, id_sessao, nome=None) -> Lead:
        if nome:
            self.__dict__.setdefault("nomes", {}).setdefault(telefone, nome)     # como no banco: não sobrescreve
        for lead in self.leads.values():
            if lead.id_canal == canal.id and lead.telefone == telefone:
                if id_sessao and lead.id_sessao_helena != id_sessao:
                    lead.id_sessao_helena = id_sessao
                return replace(lead, novo=False)
        principal = agente.principal() if agente else None
        lead = Lead(
            id=self._id("lead"), id_escritorio=escritorio.id, id_canal=canal.id,
            id_agente=agente.id if agente else None, id_etapa=principal.id if principal else None,
            telefone=telefone, id_sessao_helena=id_sessao,
        )
        self.leads[lead.id] = lead
        self.mensagens[lead.id] = []
        self.fatos[lead.id] = []
        return replace(lead, novo=True)

    async def lead(self, id_lead):
        lead = self.leads.get(id_lead)
        return replace(lead) if lead else None

    async def lead_por_sessao(self, id_escritorio, id_sessao):
        lead = next((l for l in reversed(list(self.leads.values()))
                     if l.id_escritorio == id_escritorio and l.id_sessao_helena == id_sessao), None)
        return replace(lead) if lead else None

    async def lead_do_contato(self, id_escritorio, id_canal, *, id_contato_helena=None, telefone=None):
        # contatos_helena: {id_contato_helena: telefone}, o que agentesia_contatos.id_contato_helena guarda no banco.
        por_id = self.__dict__.get("contatos_helena", {}).get(id_contato_helena) if id_contato_helena else None
        for alvo in (por_id, telefone):
            if not alvo:
                continue
            lead = next((l for l in reversed(list(self.leads.values()))
                         if l.id_escritorio == id_escritorio and l.id_canal == id_canal and l.telefone == alvo), None)
            if lead:
                return replace(lead)
        return None

    async def atualizar_lead(self, id_lead, **campos) -> None:
        lead = self.leads[id_lead]
        if "id_etapa" in campos and campos["id_etapa"] != lead.id_etapa:
            self._registrar_etapa(lead, campos["id_etapa"], None)
        for nome, valor in campos.items():
            setattr(lead, nome, valor)

    def _registrar_etapa(self, lead, id_etapa, origem, id_turno=None) -> None:
        """Como o gatilho do banco: sem origem declarada, o turno da IA em andamento neste lead é quem trocou."""
        if origem is None:
            id_turno = next((i for i, t in reversed(list(self.turnos.items()))
                             if t["id_lead"] == lead.id and t["situacao"] == "processando"), None)
            origem = "ia" if id_turno else None
        self.etapas.append({"id_lead": lead.id, "de": lead.id_etapa, "para": id_etapa, "origem": origem,
                            "id_turno": id_turno, "criado_em": datetime.now(timezone.utc)})

    async def desfazer_turno(self, *, lead, id_turno, id_etapa) -> None:
        """B7: etapa de volta e cada fato do turno devolve a vigência à versão que ele substituiu."""
        atual = self.leads[lead.id]
        if atual.id_etapa != id_etapa:
            self._registrar_etapa(atual, id_etapa, "desfazer", id_turno)
            atual.id_etapa = id_etapa
        for novo in [f for f in self.fatos[lead.id] if f.get("id_turno") == id_turno and not f["substituido"]]:
            novo["substituido"] = True
            anterior, alvo = None, novo
            while True:              # a versão de ANTES do turno (o turno pode ter gravado a chave duas vezes)
                anterior = next((f for f in self.fatos[lead.id] if f.get("substituido_por") is alvo), None)
                if anterior is None or anterior.get("id_turno") != id_turno:
                    break
                alvo = anterior
            if anterior is not None:
                anterior["substituido"], anterior["substituido_por"] = False, None

    async def trocas_da_ia(self, id_lead, horas: int = 24) -> int:
        from datetime import timedelta as _td
        corte = datetime.now(timezone.utc) - _td(hours=horas)
        por_turno: dict[str, list[str | None]] = {}
        for linha in self.etapas:
            if linha["id_lead"] == id_lead and linha["id_turno"] and linha["criado_em"] > corte:
                por_turno.setdefault(linha["id_turno"], []).append(linha["origem"])
        return sum(1 for origens in por_turno.values() if origens == ["ia"])

    async def gravar_mensagem(self, *, lead, autor, tipo, texto, texto_extraido, url_midia, enviada_em,
                              id_externo, id_turno=None, situacao_envio="recebida", erro=None):
        lista = self.mensagens[lead.id]
        if id_externo and (existente := next((m for m in lista if m.id_externo == id_externo), None)):
            if autor == "ia" and existente.autor == "automacao":     # o eco do envio chegou antes: a linha é da IA
                existente.autor, existente.id_turno = "ia", id_turno
                existente.texto = texto if texto is not None else existente.texto
                existente.texto_extraido = texto_extraido if texto_extraido is not None else existente.texto_extraido
                self.__dict__.setdefault("situacoes", {})[existente.id] = (situacao_envio, erro)
                return existente.id
            return None
        mensagem = Mensagem(id=self._id("msg"), autor=autor, tipo=tipo, texto=texto, texto_extraido=texto_extraido,
                            enviada_em=enviada_em, id_turno=id_turno, id_externo=id_externo, url_midia=url_midia)
        lista.append(mensagem)
        lista.sort(key=lambda m: m.enviada_em)
        self.__dict__.setdefault("situacoes", {})[mensagem.id] = (situacao_envio, erro)
        return mensagem.id

    async def lead_ja_escreveu(self, id_lead, *, antes_de=None) -> bool:
        mensagens = self.mensagens.get(id_lead, [])
        if antes_de is None:
            return any(m.autor == "lead" for m in mensagens)
        atual = next((m for m in mensagens if m.id == antes_de), None)
        if atual is None:
            return any(m.autor == "lead" and m.id != antes_de for m in mensagens)
        ordem = {m.id: i for i, m in enumerate(mensagens)}            # chegada (a lista já vem por enviada_em)
        chave = lambda m: (m.enviada_em, ordem[m.id])                  # noqa: E731
        return any(m.autor == "lead" and m.id != antes_de and chave(m) < chave(atual) for m in mensagens)

    async def ultima_mensagem_do_lead(self, id_lead):
        return max((m.enviada_em for m in self.mensagens.get(id_lead, []) if m.autor == "lead"), default=None)

    async def token_helena(self, id_escritorio):
        escritorio = self.escritorios.get(id_escritorio)
        return self.segredos.get(escritorio.id_segredo_helena or "") if escritorio else None

    async def marcar_envio_falhou(self, *, id_escritorio, id_externo, erro):
        for lead in self.leads.values():
            if lead.id_escritorio != id_escritorio:
                continue
            for m in self.mensagens[lead.id]:
                situacoes = self.__dict__.setdefault("situacoes", {})
                if m.id_externo == id_externo and m.autor == "ia" and situacoes.get(m.id, ("",))[0] != "falhou":
                    situacoes[m.id] = ("falhou", erro)
                    return {"id": m.id, "id_lead": lead.id, "id_turno": m.id_turno, "texto": m.texto, "url_midia": None}
        return None

    async def registrar_fala_do_atendente(self, *, lead, tipo, texto, texto_extraido, url_midia, enviada_em,
                                          id_externo, pausa, motivo_followup):
        id_mensagem = await self.gravar_mensagem(lead=lead, autor="humano", tipo=tipo, texto=texto,
                                                 texto_extraido=texto_extraido, url_midia=url_midia,
                                                 enviada_em=enviada_em, id_externo=id_externo)
        await self.cancelar_followups(lead.id, motivo_followup)
        if pausa:
            await self.atualizar_lead(lead.id, **pausa)
        return id_mensagem

    async def esquecer_recebido(self, *, origem, id_externo, tipo) -> None:
        if id_externo is not None:
            self.recebidos.discard((origem, f"{tipo}:{id_externo}"))

    async def mensagem_por_id_externo(self, id_escritorio, id_externo):
        return next((m for lead in self.leads.values() if lead.id_escritorio == id_escritorio
                     for m in self.mensagens[lead.id] if m.id_externo == id_externo), None)

    @staticmethod
    def _mesmo_conteudo(m, texto, url_midia) -> bool:
        return (texto is not None and (m.texto or "").strip() == texto.strip()) or \
            (url_midia is not None and m.url_midia == url_midia)

    async def ligar_eco_a_ia(self, id_escritorio, id_lead, *, id_externo, texto, url_midia, minutos=15) -> bool:
        from datetime import datetime, timedelta, timezone
        limite = datetime.now(timezone.utc) - timedelta(minutes=minutos)
        situacoes = self.__dict__.setdefault("situacoes", {})
        for m in self.mensagens.get(id_lead, []):
            if m.autor == "ia" and m.id_externo is None and situacoes.get(m.id, ("",))[0] == "pendente" \
                    and m.enviada_em >= limite and self._mesmo_conteudo(m, texto, url_midia):
                m.id_externo = id_externo
                situacoes[m.id] = ("enviada", None)
                return True
        return False

    async def eco_sem_dono(self, id_lead, *, texto, url_midia, minutos=15):
        from datetime import datetime, timedelta, timezone
        limite = datetime.now(timezone.utc) - timedelta(minutes=minutos)
        achadas = [m for m in self.mensagens.get(id_lead, []) if m.autor == "automacao" and m.id_externo
                   and m.enviada_em >= limite and self._mesmo_conteudo(m, texto, url_midia)]
        return achadas[-1].id_externo if achadas else None

    async def mensagem_e_da_ia(self, id_escritorio, id_externo) -> bool:
        return any(m.id_externo == id_externo and m.autor == "ia"
                   for lead in self.leads.values() if lead.id_escritorio == id_escritorio
                   for m in self.mensagens[lead.id])

    async def mensagens_pendentes(self, id_lead):
        return [m for m in self.mensagens[id_lead] if m.autor == "lead" and m.id_turno is None]

    async def historico(self, id_lead, limite=40):
        antigas = [m for m in self.mensagens[id_lead] if not (m.autor == "lead" and m.id_turno is None)]
        return antigas[-limite:]

    # ---- memória longa (ficha da conversa antiga), como no Postgres ----
    def _antigas_sem_resumo(self, id_lead, janela, limite, corte, recentes=False) -> tuple[list[dict[str, str]], int]:
        from app.memoria import AUTORES
        conversa = [m for m in self.mensagens.get(id_lead, []) if not (m.autor == "lead" and m.id_turno is None)]
        fora = conversa[:-janela] if janela else list(conversa)
        marca = (self.__dict__.get("resumos", {}).get(id_lead) or {}).get("ate_id_mensagem")
        posicao = next((i for i, m in enumerate(fora) if m.id == marca), None)
        if marca and posicao is None and any(m.id == marca for m in conversa):
            fora = []                                    # a marca já está dentro da janela
        elif posicao is not None:
            fora = fora[posicao + 1:]
        antigas = [{"id": m.id, "autor": m.autor, "texto": m.para_a_ia()[:corte]}
                   for m in fora if m.autor in AUTORES and m.para_a_ia()]
        return (antigas[-limite:] if recentes and limite else antigas[:limite]), len(antigas)

    async def comeco_da_conversa(self, id_lead, *, janela=40, limite=60, corte=600) -> dict:
        ficha = self.__dict__.get("resumos", {}).get(id_lead) or {}
        antigas, pendentes = self._antigas_sem_resumo(id_lead, janela, limite, corte, recentes=True)
        return {"resumo": ficha.get("resumo", ""), "ate_id_mensagem": ficha.get("ate_id_mensagem"),
                "antigas": [{"autor": m["autor"], "texto": m["texto"]} for m in antigas], "pendentes": pendentes}

    async def trecho_para_resumir(self, id_lead, *, janela=40, limite=150, corte=1500) -> dict:
        ficha = self.__dict__.get("resumos", {}).get(id_lead) or {}
        antigas, _ = self._antigas_sem_resumo(id_lead, janela, limite, corte)
        return {"resumo": ficha.get("resumo", ""), "mensagens": antigas}

    async def gravar_resumo(self, *, id_lead, resumo, ate_id_mensagem, quantidade, modelo, tokens) -> None:
        resumos = self.__dict__.setdefault("resumos", {})
        anterior = resumos.get(id_lead) or {}
        ordem = [m.id for m in self.mensagens.get(id_lead, [])]
        marca = ate_id_mensagem
        if anterior.get("ate_id_mensagem") in ordem and ate_id_mensagem in ordem \
                and ordem.index(anterior["ate_id_mensagem"]) > ordem.index(ate_id_mensagem):
            marca = anterior["ate_id_mensagem"]          # a marca só anda para a frente
        resumos[id_lead] = {"resumo": resumo, "ate_id_mensagem": marca, "modelo": modelo, "tokens": tokens,
                            "mensagens_resumidas": anterior.get("mensagens_resumidas", 0) + quantidade}

    async def marcar_no_turno(self, ids_mensagens, id_turno) -> None:
        for lista in self.mensagens.values():
            for m in lista:
                if m.id in ids_mensagens:
                    m.id_turno = id_turno

    async def fatos_vigentes(self, id_lead):
        return {f["chave"]: f["valor"] for f in self.fatos[id_lead] if not f["substituido"]}

    async def gravar_fatos(self, *, lead, id_turno, fatos) -> None:
        for novo in fatos:
            linha = {**novo, "id_turno": id_turno, "substituido": False}
            for antigo in self.fatos[lead.id]:
                if antigo["chave"] == novo["chave"] and not antigo["substituido"]:
                    antigo["substituido"], antigo["substituido_por"] = True, linha
            self.fatos[lead.id].append(linha)

    async def abrir_turno(self, *, lead, modo, etapa_antes) -> str:
        id_turno = self._id("turno")
        self.turnos[id_turno] = {"id_lead": lead.id, "modo": modo, "etapa_antes": etapa_antes,
                                 "situacao": "processando", "iniciado_em": datetime.now().astimezone()}
        return id_turno

    async def fechar_turno(self, id_turno, *, situacao, motivo, etapa_depois, contexto, resposta) -> None:
        self.turnos[id_turno].update(situacao=situacao, motivo=motivo, etapa_depois=etapa_depois,
                                     contexto=contexto, resposta=resposta)

    async def fatos_do_sistema(self, id_lead) -> dict:
        lead = self.leads.get(id_lead)
        return {"telefone": lead.telefone, "contrato": "não gerado"} if lead else {}

    async def marcar_resposta(self, id_lead, quando) -> None:
        esperas = self.__dict__.setdefault("esperas", {})
        if quando is None:
            esperas.pop(id_lead, None)
        else:
            esperas[id_lead] = quando

    async def reservar_lead(self, id_lead, segundos) -> bool:
        from datetime import datetime, timedelta, timezone
        reservas = self.__dict__.setdefault("reservas", {})
        agora = datetime.now(timezone.utc)
        if reservas.get(id_lead) and reservas[id_lead] > agora:
            return False
        reservas[id_lead] = agora + timedelta(seconds=segundos)
        return True

    async def renovar_reserva(self, id_lead, segundos) -> None:
        from datetime import timedelta
        self.__dict__.setdefault("reservas", {})[id_lead] = datetime.now(timezone.utc) + timedelta(seconds=segundos)

    async def responder_apos(self, id_lead):
        return self.__dict__.get("esperas", {}).get(id_lead)

    async def fechar_turnos_interrompidos(self, minutos=10, orfao_s=20) -> list[dict]:
        from datetime import timedelta
        agora_ = datetime.now().astimezone()
        reservas = self.__dict__.setdefault("reservas", {})
        fechados = []
        for id_turno, turno in self.turnos.items():
            if turno["situacao"] != "processando":
                continue
            reserva = reservas.get(turno["id_lead"])
            orfao = (turno.get("modo") != "laboratorio" and turno["id_lead"] is not None
                     and turno["iniciado_em"] < agora_ - timedelta(seconds=orfao_s) and not (reserva and reserva > agora_))
            if not (orfao or turno["iniciado_em"] < agora_ - timedelta(minutes=minutos)):
                continue
            turno.update(situacao="erro", motivo="turno_interrompido")
            lead = self.leads.get(turno["id_lead"])
            msgs = self.mensagens.get(turno["id_lead"], [])
            enviadas = sum(1 for m in msgs if m.autor == "ia" and m.id_turno == id_turno)
            devolvidas = 0
            if not enviadas:
                for m in msgs:
                    if m.autor == "lead" and m.id_turno == id_turno:
                        m.id_turno, devolvidas = None, devolvidas + 1
            pendentes = [m for m in msgs if m.autor == "lead" and m.id_turno is None]
            novas = sum(1 for m in pendentes if getattr(m, "registrada_em", None) is None
                        or m.registrada_em > turno["iniciado_em"]) - devolvidas
            if pendentes:
                esperas = self.__dict__.setdefault("esperas", {})
                esperas[turno["id_lead"]] = min(esperas.get(turno["id_lead"]) or agora_, agora_)
            fechados.append({"id_turno": id_turno, "id_lead": turno["id_lead"],
                             "id_escritorio": lead.id_escritorio if lead else None,
                             "enviadas": enviadas, "devolvidas": devolvidas, "novas": max(0, novas)})
        return fechados

    async def liberar_lead(self, id_lead) -> None:
        self.__dict__.setdefault("reservas", {}).pop(id_lead, None)

    async def leads_aguardando(self, limite=200):
        from datetime import datetime, timezone
        reservas = self.__dict__.setdefault("reservas", {})
        agora = datetime.now(timezone.utc)
        return [(i, q) for i, q in self.__dict__.get("esperas", {}).items() if not (reservas.get(i) and reservas[i] > agora)][:limite]

    async def agendar_followup(self, id_lead, base) -> None:
        self.__dict__.setdefault("followups", []).append(("agendar", id_lead, base))

    async def cancelar_followups(self, id_lead, motivo) -> None:
        self.__dict__.setdefault("followups", []).append(("cancelar", id_lead, motivo))

    async def eventos_com_aviso(self, id_escritorio) -> set[str]:
        return set(getattr(self, "avisos", {}).get(id_escritorio, ()))

    async def atualizar_texto_extraido(self, id_mensagem, texto) -> None:
        for mensagens in self.mensagens.values():
            for m in mensagens:
                if m.id == id_mensagem:
                    m.texto_extraido = texto
                    m.midia_pendente_desde = None

    async def marcar_midia_pendente(self, id_mensagem) -> None:
        for mensagens in self.mensagens.values():
            for m in mensagens:
                if m.id == id_mensagem:
                    m.midia_pendente_desde = datetime.now(timezone.utc)

    async def limpar_midia_pendente(self, id_mensagem) -> None:
        for mensagens in self.mensagens.values():
            for m in mensagens:
                if m.id == id_mensagem:
                    m.midia_pendente_desde = None

    async def gravar_chamadas(self, *, id_escritorio, id_turno, chamadas: list[Chamada], id_lead=None) -> None:
        self.chamadas.extend({"id_turno": id_turno, "id_escritorio": id_escritorio, "id_lead": id_lead, **vars(c)}
                             for c in chamadas)

    async def bloqueado_por_saldo(self, id_escritorio) -> bool:
        """Nos testes: escritórios em `sem_saldo` estão no pré-pago sem saldo."""
        return id_escritorio in self.__dict__.get("sem_saldo", set())

    async def nota_de_problema(self, *, id_escritorio, id_lead, tipo, texto) -> bool:
        from datetime import timedelta as _td
        prefixo = f"{id_lead}:problema:{tipo}:"
        notas = [a for a in self.acoes if a["chave_unica"].startswith(prefixo)]
        agora_ = datetime.now(timezone.utc)
        if notas and notas[-1]["criada_em"] > agora_ - _td(hours=6):
            return False
        if notas:
            ocorrencias = sum(1 for e in self.eventos if e.get("id_lead") == id_lead and e["tipo"] == tipo)
            texto += f"\n\nPrimeiro aviso deste problema: {notas[0]['criada_em']:%d/%m %H:%M}. Ocorrências desde então: {ocorrencias}"
        self.acoes.append({"tipo": "nota", "chave_unica": prefixo + str(len(notas) + 1), "dados": {"texto": texto},
                           "id_escritorio": id_escritorio, "id_lead": id_lead, "id_turno": None, "criada_em": agora_})
        return True

    async def documentos_do_agente(self, id_agente) -> list[tuple[str, str]]:
        return list(self.__dict__.get("documentos", {}).get(id_agente, []))

    async def trechos_do_agente(self, id_agente) -> list[dict]:
        return list(self.__dict__.get("trechos", {}).get(id_agente, []))

    async def registrar_lacuna(self, *, id_escritorio, id_agente, papel, pergunta, id_lead=None, id_turno=None) -> dict | None:
        """Pergunta sem resposta na base: a mesma dúvida aberta soma em "vezes" (como o índice único do Postgres)."""
        from app.conhecimento import normalizar_pergunta
        normalizada = normalizar_pergunta(pergunta)
        if not normalizada:
            return None
        lacunas = self.__dict__.setdefault("lacunas", [])
        achada = next((l for l in lacunas if l["id_agente"] == id_agente and l["pergunta_normalizada"] == normalizada
                       and l["situacao"] == "aberta"), None)
        if achada:
            achada.update(vezes=achada["vezes"] + 1, papel=papel, ultimo_lead=id_lead, ultimo_turno=id_turno)
            return {"id": achada["id"], "vezes": achada["vezes"]}
        nova = {"id": f"lacuna-{len(lacunas) + 1}", "id_escritorio": id_escritorio, "id_agente": id_agente, "papel": papel,
                "pergunta": pergunta.strip()[:500], "pergunta_normalizada": normalizada, "vezes": 1, "situacao": "aberta",
                "ultimo_lead": id_lead, "ultimo_turno": id_turno}
        lacunas.append(nova)
        return {"id": nova["id"], "vezes": 1}

    async def reindexar_base(self, id_agente, modelo, dimensoes) -> int:
        self.__dict__.setdefault("reindexar", []).append((id_agente, modelo, dimensoes))
        return 0

    async def gravar_origem(self, id_lead, origem) -> bool:
        origens = self.__dict__.setdefault("origens", {})
        if id_lead in origens:
            return False
        origens[id_lead] = origem
        return True

    async def gasto_desde(self, id_escritorio, desde) -> float:
        return float(sum(c.get("custo_usd") or 0 for c in self.chamadas if c.get("id_escritorio") == id_escritorio))

    async def gravar_eventos(self, *, id_escritorio, id_lead, id_turno, eventos) -> None:
        self.eventos.extend({"id_escritorio": id_escritorio, "id_lead": id_lead, "id_turno": id_turno, **e}
                            for e in eventos)

    async def segredo(self, id_segredo):
        return self.segredos.get(id_segredo or "")

    async def config_crm(self, id_escritorio):
        return self.crm.get(id_escritorio)

    async def config_zapsign(self, id_escritorio):
        return self.__dict__.setdefault("zapsign", {}).get(id_escritorio) or {}

    async def enfileirar_acoes(self, *, id_escritorio, id_lead, id_turno, acoes) -> None:
        conhecidas = {a["chave_unica"] for a in self.acoes}
        self.acoes.extend({**a, "id_escritorio": id_escritorio, "id_lead": id_lead, "id_turno": id_turno}
                          for a in acoes if a["chave_unica"] not in conhecidas)
