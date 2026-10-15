"""Dos resultados do Google para provas estruturadas: LLM (via AIsa) com plano B por regras.

Regra de ouro (a mesma do Prospector): o LLM só LÊ o que veio da busca. Ele não pode
inventar data, local, preço nem link. O código confere tudo o que volta:
  - a data precisa estar no formato AAAA-MM-DD e ser uma data válida;
  - a fonte precisa ser um dos resultados enviados (índice), e vira a URL desse resultado;
  - o link de inscrição só é aceito se for uma das URLs enviadas.
O que não passa nessa conferência vira campo vazio, e a prova cai na lista "conferir".
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from urllib.parse import urlparse

from .aisa_client import AisaClient, AisaError
from .config import Config
from .models import Corrida, ResultadoBusca
from .regioes import LOCAIS_CONHECIDOS, normalizar

log = logging.getLogger(__name__)

MAX_TEXTO = 200


# ---------- Domínios ----------


def dominio_raiz(valor: str | None) -> str | None:
    """'https://www.ticketsports.com.br/e/x' -> 'ticketsports.com.br'."""
    if not valor:
        return None
    texto = valor.strip().lower()
    if not texto:
        return None
    if "//" not in texto:
        texto = "//" + texto
    host = (urlparse(texto).hostname or "").removeprefix("www.")
    return host or None


# Plataformas de inscrição e sites de organizadores: um link para eles conta como link oficial.
PLATAFORMAS = {
    "ticketsports.com.br": "Ticket Sports",
    "minhasinscricoes.com.br": "Minhas Inscrições",
    "sympla.com.br": "Sympla",
    "eventbrite.com.br": "Eventbrite",
    "doity.com.br": "Doity",
    "yescom.com.br": "Yescom",
    "iguanasports.com.br": "Iguana Sports",
    "tfsports.com.br": "TF Sports",
    "htsports.com.br": "HT Sports",
    "sagazesportes.com.br": "Sagaz",
    "runsports.com.br": "Run Sports",
    "ttkeventos.com.br": "TTK",
    "saosilvestre.com.br": "São Silvestre (site oficial)",
    "circuitobancodobrasil.com.br": "Circuito Banco do Brasil (site oficial)",
    # Domínio reservado para exemplos (RFC 2606): usado só pelo modo demonstração.
    "inscricoes.example": "Plataforma fictícia (demonstração)",
}

# Calendários e imprensa: boas FONTES, mas não são o link de inscrição.
AGREGADORES = {
    "prefeitura.sp.gov.br": "Prefeitura de São Paulo",
    "capital.sp.gov.br": "Prefeitura de São Paulo",
    "gazetasp.com.br": "Gazeta SP",
    "corridasbr.com.br": "CorridasBR",
    "ativo.com": "Ativo.com",
    "abraceo.com.br": "Abraceo",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
}


def _procurar(dominio: str | None, tabela: dict[str, str]) -> str | None:
    if not dominio:
        return None
    for base, nome in tabela.items():
        if dominio == base or dominio.endswith("." + base):
            return nome
    return None


def plataforma_do_link(url: str | None) -> str | None:
    return _procurar(dominio_raiz(url), PLATAFORMAS)


def nome_da_fonte(url: str) -> str:
    dominio = dominio_raiz(url) or ""
    return _procurar(dominio, PLATAFORMAS) or _procurar(dominio, AGREGADORES) or dominio


# ---------- Resultados da busca ----------


def interpretar_resultados(itens: list[dict]) -> list[ResultadoBusca]:
    """Pega os blocos úteis do DataForSEO (orgânicos e, se houver, o carrossel de eventos)."""
    resultados: list[ResultadoBusca] = []
    for item in itens:
        tipo = item.get("type")
        if tipo == "organic":
            candidatos = [item]
        elif tipo == "events" and isinstance(item.get("items"), list):
            candidatos = [i for i in item["items"] if isinstance(i, dict)]
        else:
            continue  # anúncios, "as pessoas também perguntam", vídeos...
        for c in candidatos:
            url = (c.get("url") or "").strip()
            titulo = " ".join(str(c.get("title") or "").split())
            if not url.startswith(("http://", "https://")) or not titulo:
                continue
            partes = [c.get("description"), c.get("pre_snippet")]
            datas = c.get("event_dates") if isinstance(c.get("event_dates"), dict) else {}
            if datas.get("displayed_dates"):
                partes.append(f"Data: {datas['displayed_dates']}")
            lugar = c.get("location_info") if isinstance(c.get("location_info"), dict) else {}
            if lugar.get("name") or lugar.get("address"):
                partes.append(f"Local: {', '.join(str(p) for p in (lugar.get('name'), lugar.get('address')) if p)}")
            descricao = " ".join(" ".join(str(p) for p in partes if p).split())
            resultados.append(
                ResultadoBusca(title=titulo[:300], description=descricao[:900], url=url[:500],
                               domain=dominio_raiz(url) or "")
            )
    # Mesma URL em dois blocos: fica a primeira.
    vistos: set[str] = set()
    unicos = []
    for r in resultados:
        if r.url not in vistos:
            vistos.add(r.url)
            unicos.append(r)
    return unicos


# ---------- LLM ----------

SISTEMA = (
    "Você organiza um calendário de corridas de rua. Recebe resultados de uma busca no Google "
    "(título, trecho e URL) e extrai as provas de corrida de rua citadas.\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "1. Use SOMENTE o que está escrito nos resultados. Não invente data, horário, local, distância, preço, "
    "organizador nem link. Campo que não aparece no texto vai como null (ou lista vazia).\n"
    "2. Só inclua uma prova se a DATA dela estiver escrita no texto. Converta para AAAA-MM-DD. Se o texto "
    "não trouxer o ano, use a próxima ocorrência a partir de hoje.\n"
    "3. Ignore provas que não são corrida a pé (ciclismo, triatlo, crossfit, natação, caminhada religiosa) e "
    "listas genéricas sem prova específica.\n"
    "4. 'resultado' é o número do resultado (índice) de onde você tirou a prova. 'link_inscricao' só pode ser "
    "uma das URLs listadas, e só quando ela for da página da prova ou da plataforma de inscrição.\n"
    "5. Uma página com várias provas (agenda, notícia) pode gerar várias provas, todas com o mesmo 'resultado'.\n"
    "6. Responda APENAS com um objeto JSON válido, sem texto antes ou depois, sem markdown."
)

FORMATO = {
    "corridas": [
        {
            "nome": "nome da prova",
            "data": "AAAA-MM-DD",
            "horario": "HH:MM ou null",
            "local": "local de largada como escrito, ou null",
            "cidade": "cidade, ou null",
            "distancias": ["5 km", "10 km"],
            "organizador": "ou null",
            "preco": "valor/lote como escrito, ou null",
            "porte": "permit ou nº de participantes, se escrito; senão null",
            "link_inscricao": "uma das URLs listadas, ou null",
            "resultado": 0,
        }
    ]
}


def montar_mensagens(resultados: list[ResultadoBusca], hoje: date, cidade: str) -> list[dict]:
    lista = [
        {"indice": i, "titulo": r.title, "trecho": r.description, "url": r.url}
        for i, r in enumerate(resultados)
    ]
    usuario = (
        f"Hoje é {hoje.isoformat()}. Cidade do calendário: {cidade}.\n\n"
        f"Resultados da busca:\n{json.dumps(lista, ensure_ascii=False, indent=1)}\n\n"
        f"Responda neste formato JSON exato:\n{json.dumps(FORMATO, ensure_ascii=False, indent=1)}"
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


_CERCA_MARKDOWN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extrair_json(texto: str) -> dict:
    """Aceita JSON puro, JSON dentro de ```cercas``` ou com texto ao redor."""
    limpo = _CERCA_MARKDOWN.sub("", texto.strip()).strip()
    try:
        dados = json.loads(limpo)
    except json.JSONDecodeError:
        inicio, fim = limpo.find("{"), limpo.rfind("}")
        if inicio == -1 or fim <= inicio:
            raise ValueError("resposta sem objeto JSON") from None
        try:
            dados = json.loads(limpo[inicio : fim + 1])
        except json.JSONDecodeError as erro:
            raise ValueError(f"JSON inválido: {erro.msg}") from None
    if not isinstance(dados, dict):
        raise ValueError("o JSON não é um objeto")
    return dados


def _texto(valor, limite: int = MAX_TEXTO) -> str | None:
    if not isinstance(valor, str):
        return None
    limpo = " ".join(valor.split())
    if not limpo or limpo.lower() in ("null", "none", "n/a", "-"):
        return None
    return limpo[:limite]


def _data(valor) -> str | None:
    texto = _texto(valor, 10)
    if not texto or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        return None
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        return None  # 2026-02-30


def _horario(valor) -> str | None:
    texto = _texto(valor, 10)
    m = re.fullmatch(r"(\d{1,2})[:h](\d{2})?", texto or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2) or '00'}"


def _distancias(valor) -> list[str]:
    if not isinstance(valor, list):
        return []
    saida = []
    for v in valor[:8]:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = f"{v:g} km"
        t = _texto(v, 30)
        if t:
            saida.append(t)
    return saida


def validar_corridas(dados: dict, resultados: list[ResultadoBusca], hoje: date) -> list[Corrida]:
    """Confere o que o LLM devolveu contra os resultados. Itens sem nome ou fonte válida são descartados."""
    lista = dados.get("corridas")
    if not isinstance(lista, list):
        raise ValueError("campo 'corridas' ausente ou não é lista")
    urls = {r.url for r in resultados}
    corridas: list[Corrida] = []
    for bruto in lista[:60]:
        if not isinstance(bruto, dict):
            continue
        nome = _texto(bruto.get("nome"))
        indice = bruto.get("resultado")
        if not nome or not isinstance(indice, int) or isinstance(indice, bool) or not 0 <= indice < len(resultados):
            continue  # sem nome ou com fonte inventada: não entra
        fonte = resultados[indice]
        link = _texto(bruto.get("link_inscricao"), 500)
        if link not in urls:
            link = None  # o LLM não pode criar links
        if link is None and plataforma_do_link(fonte.url):
            link = fonte.url  # a própria fonte é a página de inscrição
        corridas.append(
            Corrida(
                nome=nome,
                data=_data(bruto.get("data")),
                horario=_horario(bruto.get("horario")),
                local=_texto(bruto.get("local")),
                cidade=_texto(bruto.get("cidade"), 80),
                distancias=_distancias(bruto.get("distancias")),
                organizador=_texto(bruto.get("organizador"), 120),
                plataforma=plataforma_do_link(link),
                preco=_texto(bruto.get("preco"), 120),
                porte=_texto(bruto.get("porte"), 120),
                link_inscricao=link,
                fonte_url=fonte.url,
                fonte_nome=nome_da_fonte(fonte.url),
                coletado_em=hoje.isoformat(),
            )
        )
    return corridas


# ---------- Plano B (sem LLM) ----------

_MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
          "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_DATA_NUMERICA = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?!\d)")
_DATA_EXTENSO = re.compile(r"(?<!\d)(\d{1,2})(?:º|o)? de (" + "|".join(_MESES) + r")(?: de (\d{4}))?")
_DISTANCIA = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,3})?)\s?(?:km|k)(?![a-z])", re.IGNORECASE)
_PALAVRAS_CORRIDA = ("corrida", "run", "maratona", "meia maratona", "km", "circuito", "night run", "rustica")
_NAO_E_CORRIDA = ("ciclismo", "pedal", "triatlo", "triathlon", "crossfit", "natacao", "duathlon")


def _montar_data(dia: int, mes: int, ano: int | None, hoje: date) -> date | None:
    try:
        if ano is not None:
            return date(ano if ano > 100 else 2000 + ano, mes, dia)
        candidata = date(hoje.year, mes, dia)
        return candidata if candidata >= hoje else date(hoje.year + 1, mes, dia)
    except ValueError:
        return None


def encontrar_data(texto: str, hoje: date) -> date | None:
    """Primeira data reconhecível do texto ('18/10/2026', '18/10', '18 de outubro de 2026')."""
    normal = normalizar(texto)  # "1º de novembro" vira "1o de novembro"
    bruto = texto.lower()
    achadas: list[tuple[int, date]] = []
    for m in _DATA_NUMERICA.finditer(bruto):
        d = _montar_data(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None, hoje)
        if d and 1 <= int(m.group(2)) <= 12:
            achadas.append((m.start() / max(len(bruto), 1), d))
    for m in _DATA_EXTENSO.finditer(normal):
        d = _montar_data(int(m.group(1)), _MESES[m.group(2)], int(m.group(3)) if m.group(3) else None, hoje)
        if d:
            achadas.append((m.start() / max(len(normal), 1), d))
    if not achadas:
        return None
    return min(achadas, key=lambda a: a[0])[1]


def _local_conhecido(texto: str) -> str | None:
    normal = normalizar(texto)
    melhor = None
    for apelidos, _, _ in LOCAIS_CONHECIDOS:
        for apelido in apelidos:
            if re.search(rf"(?<![a-z0-9]){re.escape(apelido)}(?![a-z0-9])", normal):
                if melhor is None or len(apelido) > len(melhor):
                    melhor = apelido
    return melhor.title() if melhor else None


def extrair_por_regras(resultados: list[ResultadoBusca], hoje: date) -> list[Corrida]:
    """Uma prova por resultado que tenha cara de corrida E uma data. Sempre vai para "conferir"."""
    corridas = []
    for r in resultados:
        texto = f"{r.title}. {r.description}"
        normal = normalizar(texto)
        if not any(p in normal for p in _PALAVRAS_CORRIDA) or any(p in normal for p in _NAO_E_CORRIDA):
            continue
        quando = encontrar_data(texto, hoje)
        if quando is None:
            continue
        nome = re.split(r"\s[|\-–—]\s", r.title)[0].strip()[:MAX_TEXTO]
        distancias = list(dict.fromkeys(f"{d.replace('.', ',')} km" for d in _DISTANCIA.findall(texto)))[:6]
        corridas.append(
            Corrida(
                nome=nome or r.title[:MAX_TEXTO],
                data=quando.isoformat(),
                local=_local_conhecido(texto),
                distancias=distancias,
                plataforma=plataforma_do_link(r.url),
                link_inscricao=r.url if plataforma_do_link(r.url) else None,
                fonte_url=r.url,
                fonte_nome=nome_da_fonte(r.url),
                coletado_em=hoje.isoformat(),
            )
        )
    return corridas


# ---------- Ponto de entrada ----------


def extrair_corridas(
    cliente: AisaClient | None, resultados: list[ResultadoBusca], cfg: Config, hoje: date, usar_llm: bool = True
) -> tuple[list[Corrida], str]:
    """Devolve (corridas, origem). Tenta o LLM (até 2 vezes); se falhar, usa as regras."""
    if not resultados:
        return [], "llm" if usar_llm else "heuristica"
    if not usar_llm or cliente is None:
        return extrair_por_regras(resultados, hoje), "heuristica"

    mensagens = montar_mensagens(resultados, hoje, cfg.city_name)
    texto = ""
    for tentativa in (1, 2):
        try:
            texto = cliente.conversar(cfg.model, mensagens, temperatura=0.0, max_tokens=3500)
            return validar_corridas(extrair_json(texto), resultados, hoje), "llm"
        except ValueError as erro:
            log.warning("  Resposta do LLM fora do formato (%s) — tentativa %d/2.", erro, tentativa)
            mensagens = mensagens + [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": "Sua resposta não seguiu o formato. Responda SOMENTE com o JSON pedido."},
            ]
        except AisaError as erro:
            if erro.status in (401, 402, 403, 404):
                raise  # erro de conta/rota: usar as regras só esconderia o problema
            log.warning("  Falha ao chamar o LLM: %s", erro)
            break

    log.warning("  Usando a extração por regras.")
    return extrair_por_regras(resultados, hoje), "heuristica"
