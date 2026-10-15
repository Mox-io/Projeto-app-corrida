"""Leitura e validação da configuração (arquivo .env + variáveis de ambiente)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """Configuração ausente ou inválida (a mensagem já diz o que corrigir)."""


def _texto(nome: str, padrao: str) -> str:
    valor = os.getenv(nome)
    return valor.strip() if valor and valor.strip() else padrao


def _inteiro(nome: str, padrao: int, minimo: int, maximo: int) -> int:
    bruto = _texto(nome, str(padrao))
    try:
        valor = int(bruto)
    except ValueError:
        raise ConfigError(f"{nome} deve ser um número inteiro (valor atual: {bruto!r}).") from None
    if not minimo <= valor <= maximo:
        raise ConfigError(f"{nome} deve estar entre {minimo} e {maximo} (valor atual: {valor}).")
    return valor


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    city_name: str
    # Local da busca no Google, no formato do DataForSEO ("Sao Paulo,State of Sao Paulo,Brazil").
    search_location: str
    search_language: str
    search_depth: int
    regions: tuple[str, ...]  # regiões pesquisadas quando nenhuma é informada
    window_weeks: int  # quantas semanas à frente entram no calendário
    output_dir: Path

    @classmethod
    def from_env(cls, require_api_key: bool = True) -> "Config":
        # override=False: uma variável já definida no terminal vence o arquivo .env.
        load_dotenv(RAIZ_PROJETO / ".env", override=False)

        api_key = _texto("AISA_API_KEY", "")
        if api_key == "cole-sua-chave-aqui":
            api_key = ""
        if require_api_key and not api_key:
            raise ConfigError(
                "AISA_API_KEY não configurada. Copie .env.example para .env e cole sua chave "
                "da AIsa (console em https://aisa.one). Para testar sem chave, use --demo."
            )

        regioes = tuple(r.strip().lower() for r in _texto("REGIONS", "zona sul").split(",") if r.strip())
        if not regioes:
            raise ConfigError("REGIONS está vazia. Informe ao menos uma região (ex.: zona sul).")

        saida = Path(_texto("OUTPUT_DIR", "output"))
        if not saida.is_absolute():
            saida = RAIZ_PROJETO / saida

        return cls(
            api_key=api_key,
            base_url=_texto("AISA_BASE_URL", "https://api.aisa.one").rstrip("/"),
            model=_texto("AISA_MODEL", "gpt-4.1-mini"),
            city_name=_texto("CITY_NAME", "São Paulo"),
            search_location=_texto("SEARCH_LOCATION", "Sao Paulo,State of Sao Paulo,Brazil"),
            search_language=_texto("SEARCH_LANGUAGE", "pt"),
            search_depth=_inteiro("SEARCH_DEPTH", 20, 1, 200),
            regions=regioes,
            window_weeks=_inteiro("WINDOW_WEEKS", 8, 1, 52),
            output_dir=saida,
        )
