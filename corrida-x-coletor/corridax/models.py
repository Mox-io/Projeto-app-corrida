"""Estruturas de dados compartilhadas entre os módulos.

Os campos de `Corrida` são os definidos no projeto piloto ("Informações de cada prova no
calendário"): nome, data, horário, local, distâncias, organizador, plataforma, preço/lote,
porte, link oficial e fonte com data da última atualização.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResultadoBusca:
    """Um resultado orgânico do Google (o que o LLM lê para extrair as provas)."""

    title: str
    description: str
    url: str
    domain: str


@dataclass
class Corrida:
    """Uma prova encontrada, já normalizada."""

    nome: str
    data: str | None  # "AAAA-MM-DD"
    horario: str | None = None  # "07:00"
    local: str | None = None
    cidade: str | None = None
    regiao: str | None = None  # calculada no código a partir do local (ver regioes.py)
    distancias: list[str] = field(default_factory=list)  # ex.: ["5 km", "10 km"]
    organizador: str | None = None
    plataforma: str | None = None  # ex.: "Ticket Sports" (deduzida do domínio do link)
    preco: str | None = None  # texto livre, como veio da fonte ("1º lote R$ 129,90")
    porte: str | None = None  # ex.: "Permit Ouro", "5 mil participantes"
    link_inscricao: str | None = None  # site oficial ou plataforma de inscrição
    fonte_url: str = ""  # de onde a informação veio (sempre um dos resultados da busca)
    fonte_nome: str = ""
    coletado_em: str = ""  # "AAAA-MM-DD"


@dataclass
class Item:
    """Resultado da triagem de uma prova."""

    corrida: Corrida
    situacao: str  # "aprovada", "conferir" ou "descartada"
    motivo: str  # "ok" quando aprovada; senão o motivo
    consulta: str = ""  # termo pesquisado que trouxe esta prova
    origem: str = ""  # "llm", "heuristica" ou "demo"
