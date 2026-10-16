"""Guarda os resultados da busca no Google para não pagar a mesma busca duas vezes.

A busca é a parte cara e a IA é a parte que mais falha (saldo, modelo indisponível, resposta
fora do formato). Com o cache, quando a IA falha, a próxima execução reaproveita os resultados
já pagos e só chama a IA de novo.

Um arquivo JSON por busca (consulta + local + idioma + profundidade), válido por algumas horas:
corridas mudam, então um resultado de ontem não deve substituir uma busca nova.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .coleta import slug

log = logging.getLogger(__name__)

VALIDADE_PADRAO = timedelta(hours=24)


class CacheBusca:
    def __init__(self, pasta: Path, validade: timedelta = VALIDADE_PADRAO, agora=datetime.now):
        self.pasta = pasta
        self.validade = validade
        self.agora = agora

    def _arquivo(self, consulta: str, local: str, idioma: str, profundidade: int) -> Path:
        chave = json.dumps([consulta, local, idioma, profundidade], ensure_ascii=False)
        resumo = hashlib.sha256(chave.encode("utf-8")).hexdigest()[:10]
        return self.pasta / f"{slug(consulta, 60)}-{resumo}.json"

    def ler(self, consulta: str, local: str, idioma: str, profundidade: int) -> tuple[list[dict], datetime] | None:
        """Devolve (itens, quando foi salvo) se houver busca guardada e ainda válida."""
        arquivo = self._arquivo(consulta, local, idioma, profundidade)
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            salvo_em = datetime.fromisoformat(dados["salvo_em"])
            itens = dados["itens"]
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("  Busca guardada ilegível (%s); será feita de novo.", arquivo.name)
            return None
        if not isinstance(itens, list) or self.agora() - salvo_em > self.validade:
            return None
        return [i for i in itens if isinstance(i, dict)], salvo_em

    def gravar(self, consulta: str, local: str, idioma: str, profundidade: int, itens: list[dict]) -> None:
        arquivo = self._arquivo(consulta, local, idioma, profundidade)
        dados = {"salvo_em": self.agora().isoformat(timespec="seconds"), "consulta": consulta, "local": local,
                 "idioma": idioma, "profundidade": profundidade, "itens": itens}
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            temporario = arquivo.with_suffix(".tmp")
            temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            temporario.replace(arquivo)  # troca de uma vez: um arquivo pela metade nunca vira "busca guardada"
        except OSError as erro:
            log.warning("  Não foi possível guardar a busca (%s); a coleta continua.", erro)
