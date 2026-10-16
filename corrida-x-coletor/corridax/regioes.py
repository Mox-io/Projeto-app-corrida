"""Regiões de São Paulo: de que região é um local de prova e o que pesquisar em cada uma.

A região é decidida AQUI, no código, e não pelo LLM: os locais conhecidos vêm da tabela
"Onde acontecem as corridas em São Paulo" do projeto piloto. Um local que não está na tabela
fica com região "a confirmar" e a prova vai para a lista "conferir", em vez de ser
encaixada num palpite.
"""

from __future__ import annotations

import re
import unicodedata

REGIOES = ("zona sul", "zona norte", "zona leste", "zona oeste", "centro")


def normalizar(texto: str | None) -> str:
    """Minúsculas, sem acentos e com espaços simples: 'Anhangabaú' == 'anhangabau'."""
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).split())


# (apelidos do local, regiões a que pertence, rótulo). Locais na divisa ficam em duas regiões,
# para aparecer no filtro de qualquer uma delas. Fonte: tabela do projeto piloto (aproximada).
LOCAIS_CONHECIDOS: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
    (("sesc interlagos",), ("zona sul",), "Zona sul"),
    (("autodromo de interlagos", "autodromo interlagos", "autodromo jose carlos pace"), ("zona sul",), "Zona sul"),
    (("obelisco do ibirapuera", "obelisco", "parque ibirapuera", "parque do ibirapuera", "ibirapuera"), ("zona sul",), "Zona sul"),
    (("parque da independencia", "museu do ipiranga"), ("zona sul",), "Sul/sudeste (Ipiranga)"),
    (("ponte estaiada",), ("zona sul", "zona oeste"), "Sul/oeste"),
    (("morumbi", "estadio do morumbi", "morumbis"), ("zona sul", "zona oeste"), "Sul/oeste"),
    (("praca charles miller", "charles miller", "pacaembu"), ("centro", "zona oeste"), "Centro/oeste"),
    (("vale do anhangabau", "anhangabau"), ("centro",), "Centro"),
    (("praca do patriarca",), ("centro",), "Centro"),
    (("avenida paulista", "av paulista"), ("centro",), "Centro"),
    (("campo de marte", "pama"), ("zona norte",), "Zona norte"),
    (("shopping center norte", "center norte"), ("zona norte",), "Zona norte"),
    (("clube esperia", "esperia"), ("zona norte",), "Zona norte"),
    (("parque anhanguera", "parque do trote"), ("zona norte",), "Norte/noroeste"),
    (("parque do carmo",), ("zona leste",), "Zona leste"),
    (("shopping aricanduva", "aricanduva"), ("zona leste",), "Zona leste"),
    (("cidade universitaria", "usp"), ("zona oeste",), "Zona oeste"),
    (("parque do povo", "marginal pinheiros"), ("zona oeste",), "Oeste"),
    (("parque villa lobos", "villa lobos", "vila lobos"), ("zona oeste",), "Oeste"),
    # Locais que apareceram nas buscas reais ou são largadas comuns (região pela subprefeitura).
    (("parque burle marx", "burle marx"), ("zona sul",), "Zona sul"),
    (("jardim botanico", "jd botanico", "zoologico de sao paulo", "parque do estado"), ("zona sul",), "Zona sul"),
    (("represa de guarapiranga", "represa guarapiranga", "guarapiranga"), ("zona sul",), "Zona sul"),
    (("plaza sul", "shopping plaza sul"), ("zona sul",), "Zona sul"),
    (("parque das bicicletas",), ("zona sul",), "Zona sul"),
    (("shopping ibirapuera", "shopping morumbi", "shopping interlagos"), ("zona sul",), "Zona sul"),
    (("jockey club", "hipodromo de cidade jardim"), ("zona oeste",), "Oeste"),
    (("parque da agua branca", "agua branca"), ("zona oeste",), "Oeste"),
    (("memorial da america latina", "allianz parque"), ("zona oeste",), "Oeste"),
    (("parque candido portinari", "ceagesp"), ("zona oeste",), "Oeste"),
    (("parque da luz", "praca da se", "teatro municipal", "minhocao", "elevado joao goulart"), ("centro",), "Centro"),
    (("parque da aclimacao",), ("centro",), "Centro"),
    (("sambodromo do anhembi", "anhembi"), ("zona norte",), "Zona norte"),
    (("parque da juventude", "horto florestal", "parque estadual alberto lofgren"), ("zona norte",), "Zona norte"),
    (("parque ecologico do tiete",), ("zona leste",), "Zona leste"),
    (("neo quimica arena", "arena corinthians", "arena de itaquera"), ("zona leste",), "Zona leste"),
    (("parque do piqueri", "ceret", "parque ceret"), ("zona leste",), "Zona leste"),
]

# Bairros: menos preciso que o local exato, mas ainda decidido no código (divisão por subprefeitura).
BAIRROS: dict[str, tuple[str, ...]] = {
    "zona sul": ("moema", "vila mariana", "santo amaro", "jabaquara", "ipiranga", "saude", "campo belo",
                 "brooklin", "interlagos", "vila clementino", "cursino", "socorro", "capao redondo",
                 "jardim sul", "vila andrade", "campo limpo", "cidade dutra", "grajau", "parelheiros",
                 "agua funda", "chacara santo antonio", "cidade ademar", "pedreira", "jardim angela",
                 "jardim sao luis", "americanopolis", "sacoma"),
    "zona norte": ("santana", "tucuruvi", "casa verde", "vila guilherme", "mandaqui", "tremembe", "freguesia do o",
                   "vila maria", "jacana", "pirituba", "perus", "brasilandia", "vila medeiros", "limao", "jaragua"),
    "zona leste": ("tatuape", "mooca", "itaquera", "penha", "vila prudente", "sao miguel", "guaianases", "analia franco",
                   "belem", "vila matilde", "ermelino matarazzo", "sao mateus", "cidade tiradentes", "vila formosa",
                   "carrao", "agua rasa", "sapopemba", "itaim paulista", "bras", "pari", "aricanduva"),
    "zona oeste": ("pinheiros", "lapa", "butanta", "perdizes", "vila leopoldina", "alto de pinheiros", "jaguare",
                   "barra funda", "vila madalena", "sumare", "pompeia", "rio pequeno", "raposo tavares",
                   "itaim bibi", "vila olimpia", "jardim paulista", "vila sonia", "jardins"),
    "centro": ("republica", "bela vista", "consolacao", "liberdade", "bom retiro", "luz", "santa cecilia",
               "higienopolis", "cambuci", "aclimacao"),
}

# No NOME da prova, estes termos querem dizer outra coisa com frequência ("Corrida da Saúde",
# "Corrida da Liberdade", "Sumaré" é também uma cidade), então só valem quando aparecem no LOCAL.
_SO_NO_LOCAL = {"saude", "luz", "socorro", "liberdade", "republica", "lapa", "penha", "pedreira", "belem",
                "sumare", "pari", "bras", "jardins", "limao", "obelisco", "pama", "esperia", "usp", "agua branca",
                "guarapiranga", "anhembi", "ceret", "morumbis"}

_ROTULO_BAIRRO = {"zona sul": "Zona sul", "zona norte": "Zona norte", "zona leste": "Zona leste",
                  "zona oeste": "Zona oeste", "centro": "Centro"}


def _posicao(texto: str, termo: str) -> int | None:
    m = re.search(rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])", texto)
    return m.start() if m else None


def _contem(texto: str, termo: str) -> bool:
    return _posicao(texto, termo) is not None


def _classificar_texto(texto: str, ignorar: frozenset[str] | set[str] = frozenset()) -> tuple[tuple[str, ...], str | None]:
    if not texto:
        return (), None
    candidatos = []
    for apelidos, regioes, rotulo in LOCAIS_CONHECIDOS:
        for apelido in apelidos:
            if apelido in ignorar:
                continue
            posicao = _posicao(texto, apelido)
            if posicao is not None:
                candidatos.append((posicao, -len(apelido), regioes, rotulo))
    if candidatos:
        _, _, regioes, rotulo = min(candidatos, key=lambda c: (c[0], c[1]))
        return regioes, rotulo
    # Bairro: vence o citado primeiro e, na mesma posição, o nome mais longo ("jardim sul" antes de "sul...").
    achados = [(_posicao(texto, b), -len(b), regiao) for regiao, bairros in BAIRROS.items()
               for b in bairros if b not in ignorar]
    achados = [a for a in achados if a[0] is not None]
    if achados:
        _, _, regiao = min(achados)
        return (regiao,), _ROTULO_BAIRRO[regiao]
    return (), None


def classificar(local: str | None, nome: str | None = None) -> tuple[tuple[str, ...], str | None]:
    """Devolve (regiões, rótulo) do local. ((), None) quando não dá para saber.

    Vence o local citado primeiro ("Ponte Estaiada, Marginal Pinheiros" -> Ponte Estaiada) e,
    na mesma posição, o apelido mais longo ("obelisco do ibirapuera" antes de "obelisco").
    Se o local não diz nada ("São Paulo", vazio), tenta o NOME da prova ("Circuito Popular -
    Butantã"), sem os termos ambíguos de _SO_NO_LOCAL.
    """
    achado = _classificar_texto(normalizar(local))
    if achado[0]:
        return achado
    return _classificar_texto(normalizar(nome), _SO_NO_LOCAL)


def validar_regiao(regiao: str) -> str:
    """'Zona Sul' -> 'zona sul'. Levanta ValueError se não for uma das regiões conhecidas."""
    chave = normalizar(regiao)
    if chave in ("sul", "norte", "leste", "oeste"):
        chave = f"zona {chave}"
    if chave not in REGIOES:
        raise ValueError(f"Região desconhecida: {regiao!r}. Use uma de: {', '.join(REGIOES)}.")
    return chave


# Nome "bonito" de cada local, para montar as consultas.
_LOCAIS_PARA_BUSCA = {
    "zona sul": ("Parque Ibirapuera", "Parque da Independência", "Interlagos"),
    "zona norte": ("Campo de Marte", "Santana"),
    "zona leste": ("Parque do Carmo", "Aricanduva"),
    "zona oeste": ("Parque Villa-Lobos", "Marginal Pinheiros", "USP"),
    "centro": ("Praça Charles Miller", "Vale do Anhangabaú"),
}

_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")


def consultas_da_regiao(regiao: str, meses: list[tuple[int, int]], cidade: str = "São Paulo") -> list[str]:
    """Termos de busca para uma região: um por mês da janela + um por local conhecido.

    `meses` é uma lista de (ano, mês). Ex.: zona sul, [(2026, 10), (2026, 11)] ->
      "corrida de rua zona sul São Paulo outubro 2026", ..., "corrida Parque Ibirapuera 2026 inscrições", ...
    """
    regiao = validar_regiao(regiao)
    termos = [f"corrida de rua {regiao} {cidade} {_MESES[m - 1]} {a}" for a, m in meses]
    anos = sorted({a for a, _ in meses}) or []
    for local in _LOCAIS_PARA_BUSCA[regiao]:
        for ano in anos:
            termos.append(f"corrida {local} {ano} inscrições")
    # Remove repetidos mantendo a ordem.
    return list(dict.fromkeys(termos))


def consultas_da_cidade(cidade: str, meses: list[tuple[int, int]]) -> list[str]:
    """Termos para uma cidade sem divisão em zonas: um por mês da janela + um de calendário por ano.

    Ex.: Campinas, [(2026, 11)] -> "corrida de rua Campinas novembro 2026", "calendário de corridas Campinas 2026".
    """
    termos = [f"corrida de rua {cidade} {_MESES[m - 1]} {a}" for a, m in meses]
    termos += [f"calendário de corridas {cidade} {a}" for a in sorted({a for a, _ in meses})]
    return list(dict.fromkeys(termos))
