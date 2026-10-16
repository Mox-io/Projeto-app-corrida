"""Busca no Google, extração, triagem e junção das provas repetidas.

Situações possíveis de cada prova:
  aprovada   -> tem data na janela, região conhecida dentro do filtro e link oficial
  conferir   -> provavelmente entra, mas falta algo (região, link) ou veio das regras sem IA
  descartada -> fora da janela, da cidade ou da região; não é corrida; sem data
Guardar as descartadas (com o motivo) deixa a planilha auditável, como no Prospector.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from .aisa_client import AisaClient
from .cidades import eh_sao_paulo
from .config import Config
from .extracao import extrair_corridas, interpretar_resultados
from .models import Corrida, Item
from .regioes import classificar, normalizar

if TYPE_CHECKING:  # cache.py importa slug() daqui; o import real criaria um ciclo
    from .cache import CacheBusca

log = logging.getLogger(__name__)

MOTIVOS_LEGIVEIS = {
    "ok": "aprovada",
    "sem_data": "sem data no texto da fonte",
    "data_passada": "a prova já aconteceu",
    "fora_da_janela": "depois do fim da janela do calendário",
    "nao_e_corrida": "não é corrida a pé",
    "fora_da_cidade": "fora da cidade do calendário",
    "fora_da_regiao": "fora das regiões escolhidas",
    "regiao_a_confirmar": "local sem região conhecida: conferir",
    "sem_link_oficial": "sem link oficial de inscrição: conferir",
    "extraida_por_regras": "extraída sem IA: conferir os dados",
}

_NAO_E_CORRIDA = ("ciclismo", "pedal", "bike", "triatlo", "triathlon", "crossfit", "natacao", "duathlon",
                  "mountain bike", "cicloturismo")
_E_CORRIDA = ("corrida", "run", "running", "maratona", "km", "rustica", "night run")


def nao_e_corrida(nome: str) -> bool:
    """'Pedal Noturno' -> True; 'Bike e Running Autódromo' -> False (tem corrida também)."""
    texto = normalizar(nome)
    tem_outro = any(re.search(rf"(?<![a-z]){p}(?![a-z])", texto) for p in _NAO_E_CORRIDA)
    tem_corrida = any(re.search(rf"(?<![a-z]){p}(?![a-z])", texto) for p in _E_CORRIDA)
    return tem_outro and not tem_corrida


def _mesma_cidade(cidade: str | None, alvo: str) -> bool:
    if not cidade:
        return True  # sem cidade no texto: não descarta por isso
    c, a = normalizar(cidade), normalizar(alvo)
    if eh_sao_paulo(alvo) and c in ("sp", "capital", "sao paulo capital"):
        return True  # "SP" e "capital" só querem dizer a cidade quando ela é São Paulo
    return c == a or c.startswith(a + " ")  # "Campinas SP", "Campinas - SP"


def fim_da_janela(hoje: date, semanas: int) -> date:
    return hoje + timedelta(weeks=semanas)


def triar(
    corrida: Corrida, regioes_alvo: tuple[str, ...], hoje: date, fim: date, cidade: str, origem: str
) -> tuple[str, str]:
    """Decide a situação da prova. Devolve (situacao, motivo). Também preenche corrida.regiao.

    A ordem importa: primeiro os descartes definitivos, depois o que só pede conferência.
    """
    tem_zonas = eh_sao_paulo(cidade)  # fora de São Paulo não há zonas: a prova é da cidade toda
    regioes, rotulo = classificar(corrida.local, corrida.nome) if tem_zonas else ((), None)
    corrida.regiao = (rotulo or "A confirmar") if tem_zonas else None

    if not corrida.data:
        return "descartada", "sem_data"
    quando = date.fromisoformat(corrida.data)
    if quando < hoje:
        return "descartada", "data_passada"
    if quando > fim:
        return "descartada", "fora_da_janela"
    if nao_e_corrida(corrida.nome):
        return "descartada", "nao_e_corrida"
    if not _mesma_cidade(corrida.cidade, cidade):
        return "descartada", "fora_da_cidade"
    if tem_zonas and regioes and regioes_alvo and not set(regioes) & set(regioes_alvo):
        return "descartada", "fora_da_regiao"
    if tem_zonas and not regioes:
        return "conferir", "regiao_a_confirmar"
    if not corrida.link_inscricao:
        return "conferir", "sem_link_oficial"
    if origem == "heuristica":
        return "conferir", "extraida_por_regras"
    return "aprovada", "ok"


# ---------- Provas repetidas ----------

_PALAVRAS_VAZIAS = {"a", "o", "de", "da", "do", "das", "dos", "e", "edicao", "corrida", "etapa", "sp", "sao", "paulo",
                    "2025", "2026", "2027", "2028"}


def chave(corrida: Corrida) -> str:
    """Identifica a mesma prova vinda de fontes diferentes: data + palavras principais do nome.

    'Corrida Dorina 2026' e 'Corrida Dorina' no mesmo dia -> mesma chave (ano, ordinal e
    palavras como "corrida" e "etapa" não contam). Nomes mais diferentes passam por _parecidas().
    """
    palavras = _palavras_uteis(corrida.nome)
    return f"{corrida.data}|{' '.join(sorted(palavras))}"


def _preenchidos(c: Corrida) -> int:
    return sum(bool(v) for v in (c.horario, c.local, c.cidade, c.distancias, c.organizador, c.preco, c.porte, c.link_inscricao))


def mesclar(a: Corrida, b: Corrida) -> Corrida:
    """Fica a versão mais completa; campos vazios dela são completados pela outra."""
    base, extra = (a, b) if _preenchidos(a) >= _preenchidos(b) else (b, a)
    for campo in ("horario", "local", "cidade", "organizador", "preco", "porte", "link_inscricao", "plataforma"):
        if not getattr(base, campo) and getattr(extra, campo):
            setattr(base, campo, getattr(extra, campo))
    if not base.distancias and extra.distancias:
        base.distancias = list(extra.distancias)
    return base


def _palavras_uteis(nome: str) -> list[str]:
    return [p for p in normalizar(nome).split() if p not in _PALAVRAS_VAZIAS and not re.fullmatch(r"\d+a?", p)]


def _parecidas(a: Corrida, b: Corrida) -> bool:
    """Mesmo dia e um nome é o começo do outro: 'SporTV Run' x '6ª SporTV Run, Super 10K'.

    Exige começo (e não "contido em") e ao menos 2 palavras úteis no nome menor: assim
    "Night Run" não engole "Smart Fit Night Run" do mesmo dia.
    """
    if a.data != b.data:
        return False
    pa, pb = _palavras_uteis(a.nome), _palavras_uteis(b.nome)
    menor, maior = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return len(menor) >= 2 and maior[: len(menor)] == menor


def juntar_repetidas(corridas: list[tuple[Corrida, str, str]]) -> list[tuple[Corrida, str, str]]:
    """Junta provas repetidas. Cada item é (corrida, consulta, origem). A ordem de chegada é mantida."""
    unicas: list[tuple[Corrida, str, str]] = []
    for corrida, consulta, origem in corridas:
        for i, (existente, consulta_ex, origem_ex) in enumerate(unicas):
            if chave(existente) == chave(corrida) or _parecidas(existente, corrida):
                # Se uma das versões veio do LLM, a junção conta como LLM.
                origem_final = "llm" if "llm" in (origem, origem_ex) else origem_ex
                unicas[i] = (mesclar(existente, corrida), consulta_ex, origem_final)
                break
        else:
            unicas.append((corrida, consulta, origem))
    return unicas


# ---------- Fluxo completo ----------


def buscar_consulta(
    cliente: AisaClient, cfg: Config, consulta: str, profundidade: int, hoje: date, usar_llm: bool = True,
    cache: CacheBusca | None = None, reaproveitar: bool = True,
) -> tuple[list[Corrida], str]:
    """Uma consulta: busca no Google + extração. Devolve (corridas, origem).

    Com `cache`, a busca paga é guardada ANTES de chamar a IA: se a IA falhar (saldo, modelo,
    formato), a próxima execução reaproveita os resultados sem pagar a busca de novo.
    `reaproveitar=False` força uma busca nova (que também fica guardada).
    """
    parametros = (consulta, cfg.search_location, cfg.search_language, profundidade)
    guardada = cache.ler(*parametros) if cache and reaproveitar else None
    if guardada:
        itens, salvo_em = guardada
        log.info("  Usando a busca guardada em %s (sem custo de busca).", salvo_em.strftime("%d/%m %H:%M"))
    else:
        itens = cliente.buscar_google(*parametros)
        if cache:
            cache.gravar(*parametros, itens)
    resultados = interpretar_resultados(itens)
    log.info("  %d resultado(s) úteis para '%s'.", len(resultados), consulta)
    return extrair_corridas(cliente, resultados, cfg, hoje, usar_llm=usar_llm)


def triar_todas(
    encontradas: list[tuple[Corrida, str, str]], cfg: Config, regioes_alvo: tuple[str, ...], hoje: date,
    semanas: int | None = None,
) -> list[Item]:
    """Junta as repetidas, faz a triagem e ordena: próxima prova primeiro (o que o piloto pede)."""
    fim = fim_da_janela(hoje, semanas or cfg.window_weeks)
    itens = []
    for corrida, consulta, origem in juntar_repetidas(encontradas):
        situacao, motivo = triar(corrida, regioes_alvo, hoje, fim, cfg.city_name, origem)
        itens.append(Item(corrida=corrida, situacao=situacao, motivo=motivo, consulta=consulta, origem=origem))
    ordem = {"aprovada": 0, "conferir": 1, "descartada": 2}
    itens.sort(key=lambda i: (ordem[i.situacao], i.corrida.data or "9999", i.corrida.horario or "99", i.corrida.nome))
    return itens


def coletar(
    cliente: AisaClient,
    cfg: Config,
    consultas: list[str],
    regioes_alvo: tuple[str, ...],
    hoje: date,
    profundidade: int,
    usar_llm: bool = True,
    semanas: int | None = None,
    progresso=None,
) -> list[Item]:
    """Roda todas as consultas e devolve todas as provas triadas (aprovadas, a conferir e descartadas)."""
    encontradas: list[tuple[Corrida, str, str]] = []
    for consulta in consultas:
        if progresso:
            progresso(f"Buscando '{consulta}'...")
        corridas, origem = buscar_consulta(cliente, cfg, consulta, profundidade, hoje, usar_llm)
        if progresso:
            progresso(f"'{consulta}': {len(corridas)} prova(s) encontrada(s).")
        encontradas.extend((c, consulta, origem) for c in corridas)
    return triar_todas(encontradas, cfg, regioes_alvo, hoje, semanas)


def resumo_por_situacao(itens: list[Item]) -> dict[str, int]:
    contagem = {"aprovada": 0, "conferir": 0, "descartada": 0}
    for i in itens:
        contagem[i.situacao] += 1
    return contagem


def resumo_por_motivo(itens: list[Item]) -> dict[str, int]:
    contagem: dict[str, int] = {}
    for i in itens:
        contagem[i.motivo] = contagem.get(i.motivo, 0) + 1
    return contagem


def meses_da_janela(hoje: date, semanas: int) -> list[tuple[int, int]]:
    """(ano, mês) de cada mês tocado pela janela: 15/10 + 8 semanas -> out, nov, dez."""
    fim = fim_da_janela(hoje, semanas)
    meses, atual = [], date(hoje.year, hoje.month, 1)
    while atual <= fim:
        meses.append((atual.year, atual.month))
        atual = date(atual.year + (atual.month == 12), atual.month % 12 + 1, 1)
    return meses


_SO_LETRAS_NUMEROS = re.compile(r"[^a-z0-9]+")


def slug(texto: str, limite: int = 50) -> str:
    base = _SO_LETRAS_NUMEROS.sub("-", normalizar(texto)).strip("-")[:limite].strip("-")
    return base or "prova"
