"""Etiquetas das provas: temática (Barbie, Harry Potter...) e noturna.

Foi a dor citada pelo Diego: a pessoa descobre a "corrida da Barbie" em cima da hora. Com a
etiqueta, o app do corredor ganha o filtro "Temáticas" e pode avisar quando surgir uma.
Decidido no código, por palavras do nome, para o LLM não "achar" que uma prova é temática.
"""

from __future__ import annotations

import re

from .models import Corrida
from .regioes import normalizar

# Personagens, filmes, marcas de entretenimento e fantasias. Lista aberta: acrescente o que aparecer.
TEMAS = (
    "barbie", "power rangers", "harry potter", "senhor dos aneis", "hobbit", "disney", "marvel", "star wars",
    "mulher maravilha", "super heroi", "super herois", "batman", "superman", "homem aranha", "cartoon",
    "tom jerry", "looney tunes", "mickey", "minions", "pokemon", "turma da monica", "hello kitty", "frozen",
    "zumbi", "zombie", "halloween", "fantasia", "color run", "neon", "galinha pintadinha", "patrulha canina",
)
NOTURNA = ("night run", "noturna", "noturno", "night")


def _tem(texto: str, termos: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", texto) for t in termos)


def etiquetas(corrida: Corrida) -> list[str]:
    """['tematica', 'noturna'] conforme o nome (e o horário, para a noturna)."""
    nome = normalizar(corrida.nome)
    saida = []
    if _tem(nome, TEMAS):
        saida.append("tematica")
    hora = int(corrida.horario[:2]) if corrida.horario and corrida.horario[:2].isdigit() else None
    if _tem(nome, NOTURNA) or (hora is not None and hora >= 18):
        saida.append("noturna")
    return saida
