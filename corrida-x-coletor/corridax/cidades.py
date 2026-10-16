"""Cidades do calendário: nome que vai no calendario.json e localização da busca no Google.

São Paulo é a cidade padrão e a única dividida em zonas (regioes.py). As outras cidades são
pesquisadas e triadas sem zona.

A busca do Google (DataForSEO) exige a localização no formato exato deles, ex.:
"Campinas,State of Sao Paulo,Brazil". A lista vem de dados/locais_busca_br.json, gerado a partir
do endpoint gratuito /serp/google/locations. Cidade fora da lista: usa o estado (com --uf) ou o
Brasil inteiro; o nome da cidade já está na consulta, então a busca continua focada nela.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .regioes import normalizar

CIDADE_PADRAO = "São Paulo"
_ARQUIVO = Path(__file__).with_name("dados") / "locais_busca_br.json"

# Grafia com acento das cidades mais pedidas; as outras ficam como a pessoa escreveu.
_GRAFIA = {normalizar(c): c for c in (
    "São Paulo", "Campinas", "Santos", "São José dos Campos", "Sorocaba", "Ribeirão Preto", "Jundiaí",
    "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Porto Alegre", "Brasília", "São Bernardo do Campo",
    "Santo André", "Guarulhos", "Osasco", "Niterói", "Florianópolis", "Goiânia", "Vitória", "Maceió",
    "São Luís", "Belém", "Cuiabá", "João Pessoa", "Uberlândia", "Londrina", "Maringá", "Piracicaba",
)}
_MINUSCULAS = {"de", "da", "do", "das", "dos", "e"}


@lru_cache(maxsize=1)
def _dados() -> dict:
    return json.loads(_ARQUIVO.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _indice() -> dict[str, list[tuple[str, str]]]:
    """'campinas' -> [('SP', 'Campinas')]; nomes repetidos em estados diferentes têm várias entradas."""
    indice: dict[str, list[tuple[str, str]]] = {}
    for uf, cidades in _dados()["cidades"].items():
        for cidade in cidades:
            indice.setdefault(normalizar(cidade), []).append((uf, cidade))
    return indice


def eh_sao_paulo(cidade: str | None) -> bool:
    return normalizar(cidade) in ("sao paulo", "sp", "sao paulo sp", "sao paulo capital")


def nome_da_cidade(texto: str) -> str:
    """'sao paulo' / 'SP' -> 'São Paulo'; 'SANTA MARIA' -> 'Santa Maria'. Levanta ValueError se vazio."""
    limpo = " ".join(str(texto or "").split())
    if len(limpo) < 2 or len(limpo) > 60:
        raise ValueError("Informe o nome da cidade (de 2 a 60 caracteres).")
    if eh_sao_paulo(limpo):
        return CIDADE_PADRAO
    if normalizar(limpo) in _GRAFIA:
        return _GRAFIA[normalizar(limpo)]
    if limpo.islower() or limpo.isupper():  # só ajusta quando a pessoa não escolheu maiúsculas
        palavras = limpo.lower().split()
        limpo = " ".join(p if i and p in _MINUSCULAS else p.capitalize() for i, p in enumerate(palavras))
    return limpo


def validar_uf(uf: str | None) -> str | None:
    if not uf:
        return None
    sigla = uf.strip().upper()
    if sigla not in _dados()["estados"]:  # {"SP": "State of Sao Paulo", ...}
        raise ValueError(f"UF desconhecida: {uf!r}. Use a sigla do estado (ex.: SP, RJ, MG).")
    return sigla


def local_da_busca(cidade: str, uf: str | None = None) -> str:
    """Localização para o Google: cidade da lista, senão o estado (com UF), senão o Brasil.

    Levanta ValueError quando o nome existe em mais de um estado e a UF não foi informada.
    """
    uf = validar_uf(uf)
    candidatos = _indice().get(normalizar(cidade), [])
    if uf:
        candidatos = [c for c in candidatos if c[0] == uf]
    if len(candidatos) > 1:
        ufs = ", ".join(sorted(c[0] for c in candidatos))
        raise ValueError(f"Existe mais de uma cidade chamada {cidade} ({ufs}). Informe a UF (ex.: --uf {candidatos[0][0]}).")
    estados = _dados()["estados"]
    if candidatos:
        sigla, nome = candidatos[0]
        return f"{nome},{estados[sigla]},Brazil"
    return f"{estados[uf]},Brazil" if uf else "Brazil"
