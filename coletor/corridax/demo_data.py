"""Modo demonstração: busca e IA simuladas, sem chave e sem custo.

As provas são as da "Amostra de calendário de São Paulo" do projeto piloto (cronograma da
Prefeitura atualizado em 08/10/2026), mais alguns casos inventados para mostrar a triagem
(ciclismo, outra cidade, prova que já passou, local desconhecido).

As páginas de resultado são FICTÍCIAS: usam os domínios reservados para exemplo
(agenda.example e inscricoes.example), então nenhum link leva a um site real.
O "hoje" da demonstração é fixo para a amostra não envelhecer.
"""

from __future__ import annotations

import json
from datetime import date

from .regioes import normalizar

HOJE_DEMO = date(2026, 10, 15)

# (data, nome, local, organizador, distâncias, horário, tem link de inscrição?, cidade)
PROVAS_DEMO: list[tuple[str, str, str, str, list[str], str | None, bool, str | None]] = [
    ("2026-10-18", "Corrida Cartoon", "PAMA, Campo de Marte", "Yescom", ["5 km"], "07:00", True, "São Paulo"),
    ("2026-10-18", "STFRS Center Norte III (Santander Track&Field)", "Shopping Center Norte", "TF Sports", ["5 km", "10 km"], "06:30", True, "São Paulo"),
    ("2026-10-18", "Athenas Run Longer", "Parque do Povo, Marginal Pinheiros", "Iguana Sports", ["10 km", "15 km"], None, True, "São Paulo"),
    ("2026-10-18", "8ª Corrida do Trigo", "Praça Charles Miller", "Sindustrigo", ["5 km", "10 km"], "07:00", False, "São Paulo"),
    ("2026-10-18", "Smart Fit Run", "Parque da Independência", "Smart Fit e TTK", ["5 km", "10 km"], "07:00", True, "São Paulo"),
    ("2026-10-18", "6ª SporTV Run, Super 10K", "Obelisco do Ibirapuera", "Yescom", ["10 km"], "07:00", True, "São Paulo"),
    ("2026-10-24", "Night Run, etapa 2", "PAMA, Campo de Marte", "TTK", ["5 km", "10 km"], "19:00", True, "São Paulo"),
    ("2026-11-01", "Correndo Contra o Câncer", "Ponte Estaiada, Marginal Pinheiros", "Yescom", ["5 km", "10 km"], None, True, "São Paulo"),
    ("2026-11-01", "Corrida Dorina", "Parque da Independência", "Fundação Dorina", ["5 km"], "07:30", True, "São Paulo"),
    ("2026-11-01", "Circuito Mais Mulher 2026", "Praça Charles Miller", "Secretaria Municipal de Esportes e Lazer", ["5 km"], None, False, "São Paulo"),
    ("2026-11-08", "Circuito Popular de Corridas de Rua", "Praça do Patriarca", "FENATS", ["5 km"], "07:00", False, "São Paulo"),
    ("2026-11-08", "Eco Run", "Parque Villa-Lobos", "Instituto Imaginação", ["5 km", "10 km"], None, True, "São Paulo"),
    ("2026-11-15", "Meia de Sampa", "Parque do Povo, Marginal Pinheiros", "Ação Correta", ["10 km", "21 km"], "06:00", True, "São Paulo"),
    ("2026-11-15", "Circuito de Corridas Caixa, etapa SP", "Parque da Independência", "HT Sports", ["5 km", "10 km"], "06:30", True, "São Paulo"),
    ("2026-11-15", "4ª edição do Desafio Minalba", "Obelisco do Ibirapuera", "Minalba Brasil", ["5 km", "10 km"], None, True, "São Paulo"),
    ("2026-11-15", "Corrida Live! Run", "Praça Charles Miller", "Instituto Eu Vivo Esporte", ["5 km", "10 km"], None, True, "São Paulo"),
    ("2026-11-15", "Corrida Tom & Jerry", "PAMA, Campo de Marte", "Yescom", ["3 km", "5 km"], "07:00", True, "São Paulo"),
    ("2026-11-20", "Corre Kilombo", "Vale do Anhangabaú", "Vega Sports", ["5 km"], None, False, "São Paulo"),
    ("2026-11-22", "12ª Corrida Mulher Maravilha", "Praça do Patriarca", "Yescom", ["5 km", "10 km"], "07:00", True, "São Paulo"),
    ("2026-11-22", "Corrida Volta de Santana", "Clube Esperia", "Clube Esperia", ["5 km", "10 km"], None, True, "São Paulo"),
    ("2026-11-22", "Disney Magic Run", "Obelisco do Ibirapuera", "Global Vita", ["5 km", "10 km"], None, True, "São Paulo"),
    ("2026-11-29", "Venus Women's Half Marathon", "Parque do Povo, Marginal Pinheiros", "Iguana Sports", ["5 km", "10 km", "21 km"], "06:00", True, "São Paulo"),
    ("2026-12-12", "São Silvestrinha", "Centro Olímpico", "Vega Sports", ["infantil"], None, True, "São Paulo"),
    ("2026-12-20", "Circuito das Estações, edição Verão", "Praça Charles Miller", "TTK", ["5 km", "10 km"], None, True, "São Paulo"),
    ("2026-12-31", "101ª Corrida Internacional de São Silvestre", "Avenida Paulista e Centro", "FCL Vega Sports", ["15 km"], "08:00", True, "São Paulo"),
    # --- casos inventados para mostrar a triagem ---
    ("2026-08-02", "Circuito Sesc de Corridas, etapa Interlagos", "Sesc Interlagos", "Sesc", ["5 km"], None, True, "São Paulo"),
    ("2026-11-08", "Pedal Noturno da Zona Sul", "Parque Ibirapuera", "Grupo fictício", ["30 km"], "20:00", True, "São Paulo"),
    ("2026-11-15", "Corrida da Lagoa de Exemplo", "Lagoa do Taquaral", "Organizador fictício", ["5 km"], None, True, "Campinas"),
    ("2026-11-29", "Corrida do Bairro Fictício", "Praça Fictícia, Jardim Exemplo", "Associação fictícia", ["5 km"], None, False, "São Paulo"),
]


def _url_pagina(nome: str) -> str:
    return "https://agenda.example/corridas/" + "-".join(normalizar(nome).split())


def _url_inscricao(nome: str) -> str:
    return "https://inscricoes.example/evento/" + "-".join(normalizar(nome).split())


def _dd_mm_aaaa(iso: str) -> str:
    ano, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{ano}"


def itens_google_demo() -> list[dict]:
    """O que a busca no Google devolveria (formato DataForSEO): uma página por prova, às vezes duas."""
    itens: list[dict] = []
    for data, nome, local, org, dist, hora, tem_link, cidade in PROVAS_DEMO:
        trecho = f"{_dd_mm_aaaa(data)}{' às ' + hora if hora else ''} · {local}, {cidade}. Distâncias: {', '.join(dist)}. Organização: {org}."
        itens.append({"type": "organic", "title": f"{nome} — agenda de corridas", "description": trecho,
                      "url": _url_pagina(nome)})
        if tem_link:
            itens.append({"type": "organic", "title": f"Inscrições: {nome}", "description": f"Inscreva-se. {trecho}",
                          "url": _url_inscricao(nome)})
    itens.insert(3, {"type": "paid", "title": "Anúncio de tênis", "url": "https://loja.example/tenis"})
    return itens


def resposta_llm_demo(resultados) -> str:
    """O JSON que o LLM devolveria para os resultados acima (já no formato pedido no prompt)."""
    indice_por_url = {r.url: i for i, r in enumerate(resultados)}
    corridas = []
    for data, nome, local, org, dist, hora, tem_link, cidade in PROVAS_DEMO:
        pagina = indice_por_url.get(_url_pagina(nome))
        if pagina is None:
            continue
        corridas.append({
            "nome": nome, "data": data, "horario": hora, "local": local, "cidade": cidade,
            "distancias": dist, "organizador": org, "preco": None, "porte": None,
            "link_inscricao": _url_inscricao(nome) if tem_link else None, "resultado": pagina,
        })
    return json.dumps({"corridas": corridas}, ensure_ascii=False)


class ClienteDemo:
    """Faz o papel do AisaClient: mesmas funções, respostas prontas, custo zero."""

    def buscar_google(self, palavra_chave, local, idioma, profundidade):
        return itens_google_demo()

    def conversar(self, modelo, mensagens, temperatura=0.4, max_tokens=1800):
        from .extracao import interpretar_resultados

        return resposta_llm_demo(interpretar_resultados(itens_google_demo()))


CONSULTA_DEMO = "corrida de rua São Paulo (demonstração)"
