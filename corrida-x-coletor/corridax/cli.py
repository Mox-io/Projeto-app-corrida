"""Linha de comando: orquestra consultas -> busca -> extração -> triagem -> planilha."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from .aisa_client import AisaClient, AisaError
from .coleta import (
    MOTIVOS_LEGIVEIS, buscar_consulta, fim_da_janela, meses_da_janela, resumo_por_motivo, resumo_por_situacao,
    triar_todas,
)
from .config import Config, ConfigError
from .demo_data import CONSULTA_DEMO, HOJE_DEMO, ClienteDemo
from .regioes import REGIOES, consultas_da_regiao, validar_regiao
from .relatorio import salvar_csv, salvar_json

log = logging.getLogger("corridax")

ERROS_FATAIS = (401, 402, 403, 404)


def criar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m corridax",
        description="Pesquisa corridas de rua por região de São Paulo e monta a planilha-piloto do Corrida X.",
    )
    p.add_argument("-r", "--regiao", action="append", metavar="REGIAO",
                   help=f"Região a pesquisar (pode repetir). Uma de: {', '.join(REGIOES)}. Padrão: REGIONS do .env")
    p.add_argument("-q", "--consulta", action="append", metavar="TERMO",
                   help="Termo de busca extra, além dos gerados para cada região (pode repetir)")
    p.add_argument("--so-consultas", action="store_true", help="Usa só os termos de --consulta (não gera os da região)")
    p.add_argument("--semanas", type=int, help="Semanas à frente no calendário (padrão: WINDOW_WEEKS do .env)")
    p.add_argument("--profundidade", type=int, help="Resultados do Google por consulta (padrão: SEARCH_DEPTH do .env)")
    p.add_argument("--limite-consultas", type=int, default=12, help="Máximo de consultas pagas por execução (padrão: 12)")
    p.add_argument("--sem-llm", action="store_true", help="Extrai as provas por regras, sem chamar o LLM (tudo vai para 'conferir')")
    p.add_argument("--listar-consultas", action="store_true", help="Só mostra as consultas que seriam feitas e sai (sem custo)")
    p.add_argument("--demo", action="store_true", help="Busca e IA simuladas com a amostra do projeto piloto (sem custo)")
    p.add_argument("-y", "--yes", action="store_true", help="Não pedir confirmação antes de gastar créditos")
    p.add_argument("--saida", type=Path, help="Pasta de saída (padrão: OUTPUT_DIR do .env)")
    return p


def _confirmar(plano: str, sem_perguntar: bool) -> bool:
    print(plano)
    if sem_perguntar:
        return True
    if not sys.stdin.isatty():
        print("Execução sem terminal interativo: use --yes para confirmar.")
        return False
    return input("Continuar? [s/N] ").strip().lower() in ("s", "sim", "y", "yes")


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    precisa_chave = not args.demo and not args.listar_consultas
    try:
        cfg = Config.from_env(require_api_key=precisa_chave)
    except ConfigError as erro:
        print(f"Erro de configuração: {erro}")
        return 1

    try:
        regioes = tuple(dict.fromkeys(validar_regiao(r) for r in (args.regiao or cfg.regions)))
    except ValueError as erro:
        print(f"Erro: {erro}")
        return 1
    semanas = args.semanas or cfg.window_weeks
    profundidade = args.profundidade or cfg.search_depth
    if not 1 <= semanas <= 52:
        print("Erro: --semanas deve estar entre 1 e 52.")
        return 1
    if not 1 <= profundidade <= 200:
        print("Erro: --profundidade deve estar entre 1 e 200.")
        return 1
    if args.limite_consultas < 1:
        print("Erro: --limite-consultas deve ser pelo menos 1.")
        return 1

    hoje = HOJE_DEMO if args.demo else date.today()
    if args.demo:
        consultas = [CONSULTA_DEMO]
    else:
        consultas = [] if args.so_consultas else [
            c for r in regioes for c in consultas_da_regiao(r, meses_da_janela(hoje, semanas), cfg.city_name)
        ]
        consultas = list(dict.fromkeys(consultas + [" ".join(q.split()) for q in (args.consulta or []) if q.strip()]))
    if not consultas:
        print("Erro: nenhuma consulta para fazer (use --consulta junto com --so-consultas).")
        return 1
    if len(consultas) > args.limite_consultas:
        print(f"{len(consultas)} consultas geradas; usando as {args.limite_consultas} primeiras (use --limite-consultas).")
        consultas = consultas[: args.limite_consultas]

    if args.listar_consultas:
        print("\n".join(f"  - {c}" for c in consultas))
        return 0

    usa_llm = not args.sem_llm
    fim = fim_da_janela(hoje, semanas)
    modo = "DEMONSTRAÇÃO (busca e IA simuladas)" if args.demo else f"busca real em {cfg.city_name}"
    plano = (
        f"\nModo: {modo}\n"
        f"Regiões: {', '.join(regioes)}\n"
        f"Janela: {hoje:%d/%m/%Y} a {fim:%d/%m/%Y} ({semanas} semanas)\n"
        f"Consultas: {len(consultas)}\n"
    )
    if not args.demo:
        plano += f"Custo: {len(consultas)} busca(s) no Google (até {profundidade} resultados cada)"
        plano += f" + até {len(consultas)} chamada(s) ao LLM" if usa_llm else ""
        plano += " — consome créditos da AIsa.\n"
    if not _confirmar(plano, sem_perguntar=args.yes or args.demo):
        print("Cancelado.")
        return 0

    cliente = ClienteDemo() if args.demo else AisaClient(cfg.api_key, cfg.base_url)
    saida = (args.saida.resolve() if args.saida else cfg.output_dir) / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    encontradas = []
    codigo = 0
    try:
        for consulta in consultas:
            print(f"Buscando: {consulta}")
            try:
                corridas, origem = buscar_consulta(cliente, cfg, consulta, profundidade, hoje, usa_llm)
            except AisaError as erro:
                if erro.status in ERROS_FATAIS:
                    raise
                print(f"  ! falhou: {erro}")  # uma consulta com problema não derruba as outras
                continue
            print(f"  {len(corridas)} prova(s) {'(regras, sem IA)' if origem == 'heuristica' else ''}".rstrip())
            encontradas.extend((c, consulta, origem) for c in corridas)
    except AisaError as erro:
        print(f"\nErro na AIsa: {erro}")
        codigo = 1

    itens = triar_todas(encontradas, cfg, regioes, hoje, semanas)
    if args.demo:  # o JSON simulado passou pela mesma conferência do LLM; só muda o rótulo
        for item in itens:
            item.origem = "demo"

    if not itens:
        print("\nNenhuma prova encontrada.")
        return codigo or 2

    resumo = resumo_por_situacao(itens)
    print(f"\nTriagem: {resumo['aprovada']} aprovada(s), {resumo['conferir']} a conferir, {resumo['descartada']} descartada(s)")
    for motivo, qtd in sorted(resumo_por_motivo(itens).items(), key=lambda x: -x[1]):
        print(f"  {qtd:3d}  {MOTIVOS_LEGIVEIS.get(motivo, motivo)}")

    print("\nPróximas provas:")
    for item in [i for i in itens if i.situacao != "descartada"][:15]:
        c = item.corrida
        marca = "  " if item.situacao == "aprovada" else "? "
        print(f"  {marca}{c.data[8:]}/{c.data[5:7]}  {c.nome} — {c.local or 'local?'} ({c.regiao})")

    csv_path = salvar_csv(itens, saida / "calendario.csv")
    json_path = salvar_json(itens, saida / "calendario.json", hoje.isoformat(), cfg.city_name)
    print(f"\nPlanilha-piloto: {csv_path}\nCalendário (JSON): {json_path}")
    print("Confira cada prova no site oficial antes de publicar: datas mudam e provas são canceladas.")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
