"""Planilha-piloto (CSV) e calendário (JSON).

CSV: todas as provas triadas, inclusive descartadas, com fonte e data da coleta em cada linha
(o projeto piloto pede "a fonte registrada em cada prova"). Abre direto no Excel em português.
JSON: só as aprovadas e as a conferir, no formato que o site do piloto (fase 2) pode ler.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .cidades import eh_sao_paulo
from .coleta import MOTIVOS_LEGIVEIS, slug
from .models import Corrida, Item
from .regioes import classificar
from .tags import etiquetas

COLUNAS = [
    "data", "horario", "prova", "local", "regiao", "cidade", "distancias", "organizador", "plataforma",
    "preco_lote", "porte", "link_inscricao", "fonte", "fonte_url", "coletado_em", "situacao", "motivo",
    "consulta", "extraido_por", "etiquetas",
]

_NOMES_ETIQUETAS = {"tematica": "temática", "noturna": "noturna"}


def id_da_prova(c: Corrida) -> str:
    """Identificador estável (data + nome): o app do corredor usa como id do documento da prova."""
    return f"{c.data or 'sem-data'}-{slug(c.nome, 60)}"


def _data_br(iso: str | None) -> str:
    if not iso:
        return ""
    ano, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{ano}"


def _escrever(itens: list[Item], arquivo) -> None:
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow(COLUNAS)
    for item in itens:
        c = item.corrida
        escritor.writerow([
            _data_br(c.data), c.horario or "", c.nome, c.local or "", c.regiao or "", c.cidade or "",
            ", ".join(c.distancias), c.organizador or "", c.plataforma or "", c.preco or "", c.porte or "",
            c.link_inscricao or "", c.fonte_nome, c.fonte_url, _data_br(c.coletado_em), item.situacao,
            MOTIVOS_LEGIVEIS.get(item.motivo, item.motivo), item.consulta,
            {"llm": "IA", "heuristica": "regras", "demo": "demonstração"}.get(item.origem, item.origem),
            ", ".join(_NOMES_ETIQUETAS[t] for t in etiquetas(c)),
        ])


def salvar_csv(itens: list[Item], destino: Path) -> Path:
    """Grava com ';' e BOM, o formato que o Excel em português abre sem importação."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
        _escrever(itens, arquivo)
    return destino


def csv_bytes(itens: list[Item]) -> bytes:
    buffer = io.StringIO(newline="")
    _escrever(itens, buffer)
    return buffer.getvalue().encode("utf-8-sig")


def calendario_json(itens: list[Item], gerado_em: str, cidade: str = "São Paulo") -> dict:
    """`cidade` é a do calendário (CITY_NAME): a triagem já descartou as provas de outras cidades,
    então todas saem com a mesma grafia, que é a que o app do corredor usa para filtrar."""
    provas = []
    for item in itens:
        if item.situacao == "descartada":
            continue
        c = item.corrida
        provas.append({
            "id": id_da_prova(c),
            "nome": c.nome, "data": c.data, "horario": c.horario, "local": c.local, "cidade": cidade, "regiao": c.regiao,
            # chaves para filtrar: ["zona sul", "zona oeste"]; fora de São Paulo não há zonas
            "regioes": list(classificar(c.local, c.nome)[0]) if eh_sao_paulo(cidade) else [],
            "distancias": c.distancias, "organizador": c.organizador, "plataforma": c.plataforma,
            "preco": c.preco, "porte": c.porte, "link_inscricao": c.link_inscricao,
            "fonte": {"nome": c.fonte_nome, "url": c.fonte_url, "coletado_em": c.coletado_em},
            "tags": etiquetas(c),
            "conferido": item.situacao == "aprovada",
        })
    provas.sort(key=lambda p: (p["data"] or "9999", p["horario"] or "99"))
    return {"gerado_em": gerado_em, "cidade": cidade, "provas": provas}


def salvar_json(itens: list[Item], destino: Path, gerado_em: str, cidade: str = "São Paulo") -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(calendario_json(itens, gerado_em, cidade), ensure_ascii=False, indent=2), encoding="utf-8")
    return destino
