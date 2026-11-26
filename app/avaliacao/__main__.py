"""CLI do teste do agente. Exemplos (rodar da raiz do projeto):

  python -m app.avaliacao listar
  python -m app.avaliacao estimar --rodadas 3 [--juiz] [--lead ia]
  python -m app.avaliacao rodar                       # toca os cassetes (sem chave, sem custo)
  python -m app.avaliacao rodar --falso               # modelo roteirizado: prova o motor
  python -m app.avaliacao rodar --real --rodadas 3 --teto-usd 2 [--lead cartao|ia] [--cenario 01,04] [--juiz]
  python -m app.avaliacao gravar 01 04 --teto-usd 1   # modelo real gravando o cassete e a transcrição
  python -m app.avaliacao estabilidade 01 --rodadas 10 --teto-usd 2
  python -m app.avaliacao comparar --agente-a a.json --agente-b b.json --cenario 01 --teto-usd 1
  python -m app.avaliacao exportar-agente <id_agente> --escritorio <id> --saida avaliacao/agentes/x.json

Outra bateria: --cenarios <pasta> (padrão avaliacao/cenarios) lê os cenários de outra pasta, e --agente <snapshot.json>
troca o agente de todos os casos (como o `comparar` faz). Ex.: a bateria do Sousa e Costa
  python -m app.avaliacao estimar --cenarios avaliacao/cenarios_sousa_costa --rodadas 1 --juiz
  python -m app.avaliacao rodar --real --cenarios avaliacao/cenarios_sousa_costa --teto-usd 3 --juiz

Sem --real nada chama a API. O modo real exige --teto-usd e a chave do provedor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from app.avaliacao import cenario as cenarios
from app.avaliacao import executar, relatorio


def _ids(texto: str | None) -> list[str] | None:
    return [i.strip() for i in texto.split(",") if i.strip()] if texto else None


def _pasta(args: argparse.Namespace) -> Path:
    """A pasta dos cenários (--cenarios), relativa à raiz do projeto quando não for absoluta."""
    valor = getattr(args, "cenarios", None)
    if not valor:
        return cenarios.PASTA_CENARIOS
    pasta = Path(valor)
    pasta = pasta if pasta.is_absolute() or pasta.exists() else cenarios.RAIZ / pasta
    if not pasta.is_dir():
        raise cenarios.ErroDeCenario(f"pasta de cenários não existe: {pasta}")
    return pasta


def _casos(args: argparse.Namespace, ids: list[str] | None) -> list[cenarios.Cenario]:
    """Os casos da pasta escolhida; com --agente, todos apontam para esse snapshot."""
    casos = cenarios.casos(ids, pasta=_pasta(args))
    agente = getattr(args, "agente", None)
    if agente:
        caminho = Path(agente)
        caminho = caminho if caminho.is_absolute() or caminho.exists() else cenarios.RAIZ / caminho
        if not caminho.is_file():
            raise cenarios.ErroDeCenario(f"snapshot do agente não existe: {caminho}")
        casos = [c.model_copy(update={"agente": str(caminho.resolve())}) for c in casos]
    return casos


def _imprimir(texto: str) -> None:
    sys.stdout.buffer.write((texto + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def _resumo(bateria: relatorio.Bateria, pasta: Path | None) -> int:
    for c in bateria.cenarios:
        situacao = "PULADO" if c.aprovado is None else ("ok" if c.aprovado else "REPROVADO")
        _imprimir(f"{situacao:<10} {c.id:<42} {c.taxa:>5}  {c.pulado or ', '.join(f'{k} {v}' for k, v in c.por_checagem.items())}")
    _imprimir(f"\nCusto total: US$ {bateria.custo_total_usd:.4f} {json.dumps(bateria.custo_por_papel)}")
    if bateria.parou_no_teto:
        _imprimir("A bateria parou antes de passar do teto de custo.")
    if pasta:
        _imprimir(f"Relatório: {pasta / 'relatorio.md'}")
    return 0 if bateria_verde(bateria) else 1


def bateria_verde(bateria: relatorio.Bateria) -> bool:
    """Verde só se todo cenário rodou e passou: parar no teto ou pular cenário não é sucesso."""
    pulados = [c.id for c in bateria.cenarios if c.aprovado is None]
    if pulados:
        _imprimir(f"Não rodaram até o fim: {', '.join(pulados)} (não conta como aprovado).")
    return bool(bateria.cenarios) and not bateria.parou_no_teto and not pulados and all(c.aprovado for c in bateria.cenarios)


def _estimativa_antes(casos: list[cenarios.Cenario], rodadas: int, juiz: bool, lead: str) -> None:
    estimativa = executar.estimar(casos, rodadas, juiz=juiz, lead=lead)
    _imprimir(estimativa.texto() + "\n")


def cmd_listar(args: argparse.Namespace) -> int:
    for caso in _casos(args, _ids(args.cenario)):
        cassete = "cassete" if executar.caminho_do_cassete(caso).exists() else "sem cassete"
        _imprimir(f"{caso.id:<42} {caso.lead.tipo:<8} {cassete:<12} {' > '.join(caso.esperado.trajetoria or [])}")
        _imprimir(f"    {caso.descricao}")
    return 0


def cmd_estimar(args: argparse.Namespace) -> int:
    _estimativa_antes(_casos(args, _ids(args.cenario)), args.rodadas, args.juiz, args.lead)
    return 0


def cmd_rodar(args: argparse.Namespace) -> int:
    casos = _casos(args, _ids(args.cenario))
    modo = "real" if args.real else ("falso" if args.falso else "cassete")
    if modo == "real":
        executar.exigir_modo_real(casos, args.teto_usd, juiz=args.juiz, lead=args.lead)
        _estimativa_antes(casos, args.rodadas, args.juiz, args.lead)
    bateria = asyncio.run(executar.rodar_bateria(casos, modo, args.rodadas, args.teto_usd, args.paralelo,
                                                 args.lead, args.juiz))
    pasta = None if args.sem_relatorio else relatorio.gravar(bateria, Path(args.saida) if args.saida else None)
    return _resumo(bateria, pasta)


def cmd_gravar(args: argparse.Namespace) -> int:
    casos = _casos(args, args.ids or None)
    executar.exigir_modo_real(casos, args.teto_usd)
    _estimativa_antes(casos, 1, False, "cartao")
    bateria = asyncio.run(executar.rodar_bateria(casos, "gravar", 1, args.teto_usd))
    pasta = relatorio.gravar(bateria)
    _imprimir("Cassetes em avaliacao/cassetes/ e transcrições em avaliacao/transcricoes/: revise o diff antes do commit.")
    return _resumo(bateria, pasta)


def cmd_estabilidade(args: argparse.Namespace) -> int:
    casos = _casos(args, [args.id])
    modo = "falso" if args.falso else "real"
    if modo == "real":
        executar.exigir_modo_real(casos, args.teto_usd, lead=args.lead)
        _estimativa_antes(casos, args.rodadas, False, args.lead)
    bateria = asyncio.run(executar.rodar_bateria(casos, modo, args.rodadas, args.teto_usd, args.paralelo, args.lead))
    for c in bateria.cenarios:
        _imprimir(f"{c.id}: {c.taxa} aprovadas")
        for trajetoria, n in Counter(" > ".join(r.trajetoria) for r in c.rodadas).most_common():
            _imprimir(f"  {n:>3}x  {trajetoria}")
        for parada, n in Counter(r.parada for r in c.rodadas).most_common():
            _imprimir(f"  parada {parada}: {n}")
    return _resumo(bateria, relatorio.gravar(bateria))


def cmd_comparar(args: argparse.Namespace) -> int:
    from app.avaliacao import juiz, simulador
    from app.modelo import ModeloPorNome

    casos = cenarios.casos(_ids(args.cenario), pasta=_pasta(args))
    executar.exigir_modo_real(casos, args.teto_usd, juiz=True)
    _estimativa_antes(casos, 2, True, "cartao")
    modelo = ModeloPorNome()

    async def rodar() -> list[dict[str, Any]]:
        from app.avaliacao import custo

        teto = custo.Teto(args.teto_usd)
        saida = []
        for caso in casos:
            conversas = []
            for arquivo in (args.agente_a, args.agente_b):
                versao = caso.model_copy(update={"agente": str(Path(arquivo).resolve())})
                conversas.append(await simulador.rodar_conversa(versao, modelo, real=True, teto=teto))
            reserva = teto.reservar(custo.previsto_juiz(transcricoes=2))
            if reserva is None:
                break
            resultado: dict[str, Any] = {}
            try:
                resultado = await juiz.comparar_ab(modelo, conversas[0], conversas[1])
            finally:
                teto.registrar(resultado.get("chamadas") or [], turnos=0, reserva=reserva)   # o juiz entra no teto
            saida.append({"cenario": caso.id, "aprovadas": [c.aprovada for c in conversas], **resultado})
        if teto.parou:
            _imprimir("A comparação parou antes de passar do teto de custo.")
        return saida

    for item in asyncio.run(rodar()):
        _imprimir(f"{item['cenario']}: checagens A={'ok' if item['aprovadas'][0] else 'reprovado'} "
                  f"B={'ok' if item['aprovadas'][1] else 'reprovado'} | juiz {item['placar']} (ordem {item['ordem_sorteada']})")
        for c in item["criterios"]:
            _imprimir(f"    {c['nome']:<18} {c['preferida']:<7} {c['motivo']}")
    return 0


SEGREDOS = ("token", "segredo", "senha", "chave", "api_key", "apikey", "secret", "password")
PESSOAIS = ("numeros_teste", "numeros_bloqueados", "telefone", "email_", "id_conta_helena", "id_segredo")


def _limpar(valor: Any) -> Any:
    """Tira segredos, tokens e números de telefone da configuração exportada."""
    if isinstance(valor, dict):
        return {k: _limpar(v) for k, v in valor.items()
                if not any(s in k.lower() for s in SEGREDOS + PESSOAIS)}
    if isinstance(valor, list):
        return [_limpar(v) for v in valor]
    return valor


def cmd_exportar(args: argparse.Namespace) -> int:
    import asyncpg

    from app.config import carregar
    from app.gestao.repositorio import RepositorioGestao

    cfg = carregar()
    if not cfg.banco_url:
        _imprimir("Defina AGENTESIA_BANCO_URL (no .env) para exportar um agente do Postgres.")
        return 2

    async def ler() -> dict[str, Any]:
        pool = await asyncpg.create_pool(cfg.banco_url, min_size=1, max_size=1)
        try:
            repo = RepositorioGestao(pool)
            agente = await repo.agente(args.escritorio, args.id_agente)
            escritorio = await repo.escritorio(args.escritorio)
        finally:
            await pool.close()
        if not agente or not escritorio:
            raise SystemExit("agente ou escritório não encontrado")
        etapas = [{"id": str(e["id"]), "codigo": e["codigo"], "principal": bool(e.get("principal")),
                   "instrucao": e.get("instrucao") or "", "modelo": e.get("modelo")} for e in agente["etapas"]]
        return {"versao": 1, "origem": f"exportado do agente {agente['id']} (sem segredos nem telefones)",
                "escritorio": {"nome": escritorio["nome"], "config": _limpar(escritorio.get("config") or {})},
                "agente": {"id": str(agente["id"]), "nome": agente["nome"], "produto": agente["produto"],
                           "config": _limpar(agente.get("config") or {}), "etapas": etapas}}

    snapshot = asyncio.run(ler())
    destino = Path(args.saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    _imprimir(f"Snapshot em {destino}. Confira se não ficou nenhum dado pessoal antes de versionar.")
    return 0


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.avaliacao", description="Teste do agente (docs/TESTE_DO_AGENTE.md)")
    sub = parser.add_subparsers(dest="comando", required=True)

    def bateria(p: argparse.ArgumentParser, *, agente: bool = True) -> None:
        p.add_argument("--cenarios", help="pasta dos cenários (padrão avaliacao/cenarios; ex.: avaliacao/cenarios_sousa_costa)")
        if agente:
            p.add_argument("--agente", help="snapshot do agente para todos os casos (ex.: avaliacao/agentes/sousa_costa.json)")

    def comuns(p: argparse.ArgumentParser, *, rodadas: int = 1) -> None:
        p.add_argument("--cenario", help="ids separados por vírgula (ex.: 01,04)")
        p.add_argument("--rodadas", type=int, default=rodadas)
        p.add_argument("--lead", choices=("cartao", "ia"), default="cartao")
        p.add_argument("--teto-usd", type=float, dest="teto_usd")
        p.add_argument("--paralelo", type=int, default=1)
        bateria(p)

    p = sub.add_parser("listar", help="lista os cenários")
    p.add_argument("--cenario")
    bateria(p)
    p.set_defaults(func=cmd_listar)

    p = sub.add_parser("estimar", help="estima o custo do modo real sem chamar a API")
    comuns(p)
    p.add_argument("--juiz", action="store_true")
    p.set_defaults(func=cmd_estimar)

    p = sub.add_parser("rodar", help="roda a bateria (cassete por padrão)")
    comuns(p)
    p.add_argument("--real", action="store_true", help="chama o modelo de verdade (custa; exige --teto-usd)")
    p.add_argument("--falso", action="store_true", help="usa o modelo roteirizado (prova o motor)")
    p.add_argument("--juiz", action="store_true", help="juiz de IA (só no modo real)")
    p.add_argument("--saida", help="pasta do relatório (padrão avaliacao/resultados/AAAA-MM-DD_HHMM_<agente>)")
    p.add_argument("--sem-relatorio", action="store_true", dest="sem_relatorio")
    p.set_defaults(func=cmd_rodar)

    p = sub.add_parser("gravar", help="grava os cassetes com o modelo real (custa; exige --teto-usd)")
    p.add_argument("ids", nargs="*")
    p.add_argument("--teto-usd", type=float, dest="teto_usd")
    bateria(p)
    p.set_defaults(func=cmd_gravar)

    p = sub.add_parser("estabilidade", help="distribuição de trajetórias em N rodadas reais")
    p.add_argument("id")
    comuns(p, rodadas=10)
    p.add_argument("--falso", action="store_true")
    p.set_defaults(func=cmd_estabilidade)

    p = sub.add_parser("comparar", help="A/B de dois snapshots com o juiz (ordem sorteada)")
    p.add_argument("--agente-a", required=True, dest="agente_a")
    p.add_argument("--agente-b", required=True, dest="agente_b")
    p.add_argument("--cenario")
    p.add_argument("--teto-usd", type=float, dest="teto_usd")
    bateria(p, agente=False)
    p.set_defaults(func=cmd_comparar)

    p = sub.add_parser("exportar-agente", help="snapshot de um agente do Postgres, sem segredos")
    p.add_argument("id_agente")
    p.add_argument("--escritorio", required=True)
    p.add_argument("--saida", required=True)
    p.set_defaults(func=cmd_exportar)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = montar_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (executar.ErroDeExecucao, cenarios.ErroDeCenario) as erro:
        _imprimir(f"erro: {erro}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
