"""Formatos de entrada e saída da API.

O servidor NÃO guarda estado entre chamadas (a Vercel roda funções sem memória
compartilhada). Por isso o navegador devolve, a cada chamada, as provas já encontradas, e o
servidor valida tudo de novo aqui: tamanhos e tipos limitados, mesmo que a página seja
alterada por quem a estiver usando.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator

from corridax.cidades import CIDADE_PADRAO, nome_da_cidade, validar_uf
from corridax.coleta import MOTIVOS_LEGIVEIS
from corridax.models import Corrida, Item
from corridax.regioes import validar_regiao
from corridax.tags import etiquetas

MAX_PROVAS = 600  # teto de provas por chamada de triagem/planilha


def _regioes(valores: list[str]) -> list[str]:
    try:
        return list(dict.fromkeys(validar_regiao(v) for v in valores))
    except ValueError as erro:
        raise ValueError(str(erro)) from None


class _ComCidade(BaseModel):
    """Cidade do calendário. São Paulo usa zonas (regions); as outras cidades, não."""

    city: str = CIDADE_PADRAO
    uf: str | None = None

    @field_validator("city")
    @classmethod
    def _cidade(cls, v: str) -> str:
        return nome_da_cidade(v)

    @field_validator("uf")
    @classmethod
    def _uf(cls, v: str | None) -> str | None:
        return validar_uf(v or None)


class PedidoConsultas(_ComCidade):
    regions: list[str] = Field(default_factory=list, max_length=5)
    weeks: int = Field(ge=1, le=52)
    extra: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("regions")
    @classmethod
    def _r(cls, v: list[str]) -> list[str]:
        return _regioes(v)

    @field_validator("extra")
    @classmethod
    def _e(cls, v: list[str]) -> list[str]:
        limpos = [" ".join(t.split()) for t in v]
        if any(len(t) > 100 for t in limpos):
            raise ValueError("Cada termo extra deve ter até 100 caracteres.")
        return [t for t in limpos if t]


class PedidoBusca(_ComCidade):
    query: str = Field(min_length=1)
    depth: int = Field(ge=1, le=200)
    use_llm: bool = True
    demo: bool = False

    @field_validator("query")
    @classmethod
    def _q(cls, valor: str) -> str:
        limpa = " ".join(valor.split())
        if not limpa or len(limpa) > 120:
            raise ValueError("A consulta deve ter de 1 a 120 caracteres.")
        return limpa


_DATA = re.compile(r"\d{4}-\d{2}-\d{2}")
_URL = re.compile(r"https?://\S+")


class CorridaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    data: str | None = Field(default=None, max_length=10)
    horario: str | None = Field(default=None, max_length=5)
    local: str | None = Field(default=None, max_length=200)
    cidade: str | None = Field(default=None, max_length=80)
    distancias: list[str] = Field(default_factory=list, max_length=8)
    organizador: str | None = Field(default=None, max_length=120)
    plataforma: str | None = Field(default=None, max_length=80)
    preco: str | None = Field(default=None, max_length=120)
    porte: str | None = Field(default=None, max_length=120)
    link_inscricao: str | None = Field(default=None, max_length=500)
    fonte_url: str = Field(default="", max_length=500)
    fonte_nome: str = Field(default="", max_length=120)
    coletado_em: str = Field(default="", max_length=10)
    consulta: str = Field(default="", max_length=120)
    origem: str = Field(default="llm", pattern="^(llm|heuristica|demo)$")

    @field_validator("data")
    @classmethod
    def _data(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not _DATA.fullmatch(v):
            raise ValueError("data deve estar no formato AAAA-MM-DD")
        date.fromisoformat(v)  # levanta erro para 2026-02-30
        return v

    @field_validator("link_inscricao")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        if not v:
            return None
        if not _URL.fullmatch(v):
            raise ValueError("link de inscrição deve começar com http:// ou https://")
        return v

    @field_validator("fonte_url")
    @classmethod
    def _fonte(cls, v: str) -> str:
        if v and not _URL.fullmatch(v):
            raise ValueError("a URL da fonte deve começar com http:// ou https://")
        return v

    @field_validator("distancias")
    @classmethod
    def _dist(cls, v: list[str]) -> list[str]:
        if any(not isinstance(d, str) or len(d) > 30 for d in v):
            raise ValueError("cada distância deve ser um texto de até 30 caracteres")
        return v

    def para_corrida(self) -> Corrida:
        dados = self.model_dump(exclude={"consulta", "origem"})
        return Corrida(**dados)


class PedidoTriagem(_ComCidade):
    corridas: list[CorridaEntrada] = Field(max_length=MAX_PROVAS)
    regions: list[str] = Field(default_factory=list, max_length=5)
    weeks: int = Field(ge=1, le=52)
    demo: bool = False

    @field_validator("regions")
    @classmethod
    def _r(cls, v: list[str]) -> list[str]:
        return _regioes(v)


# ---------- Saída ----------


def corrida_para_json(c: Corrida, consulta: str, origem: str) -> dict:
    return {
        "nome": c.nome, "data": c.data, "horario": c.horario, "local": c.local, "cidade": c.cidade,
        "distancias": c.distancias, "organizador": c.organizador, "plataforma": c.plataforma, "preco": c.preco,
        "porte": c.porte, "link_inscricao": c.link_inscricao, "fonte_url": c.fonte_url, "fonte_nome": c.fonte_nome,
        "coletado_em": c.coletado_em, "consulta": consulta, "origem": origem,
    }


def item_para_json(item: Item) -> dict:
    dados = corrida_para_json(item.corrida, item.consulta, item.origem)
    dados.update(
        regiao=item.corrida.regiao,
        situacao=item.situacao,
        motivo=item.motivo,
        motivo_texto=MOTIVOS_LEGIVEIS.get(item.motivo, item.motivo),
        tags=etiquetas(item.corrida),
    )
    return dados
