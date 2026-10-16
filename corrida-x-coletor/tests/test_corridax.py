"""Testes do núcleo (sem internet e sem chave): python -m unittest discover -s tests -t . -v"""

from __future__ import annotations

import dataclasses
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path

from corridax.aisa_client import AisaError, extrair_itens
from corridax.cache import CacheBusca
from corridax.cli import main as cli_main
from corridax.coleta import buscar_consulta, chave, coletar, juntar_repetidas, meses_da_janela, nao_e_corrida, triar
from corridax.config import Config
from corridax.demo_data import HOJE_DEMO, ClienteDemo
from corridax.extracao import (
    encontrar_data, extrair_corridas, extrair_json, extrair_por_regras, interpretar_resultados, validar_corridas,
)
from corridax.models import Corrida, ResultadoBusca
from corridax.regioes import classificar, consultas_da_regiao, validar_regiao
from corridax.relatorio import calendario_json, csv_bytes

HOJE = date(2026, 10, 15)
FIM = date(2026, 12, 10)


def cfg(**ajustes) -> Config:
    base = Config(
        api_key="", base_url="https://api.aisa.one", model="gpt-4.1-mini", city_name="São Paulo",
        search_location="Sao Paulo,State of Sao Paulo,Brazil", search_language="pt", search_depth=20,
        regions=("zona sul",), window_weeks=8, output_dir=Path(tempfile.gettempdir()) / "cx-testes",
    )
    return dataclasses.replace(base, **ajustes)


def corrida(**campos) -> Corrida:
    padrao = dict(nome="Corrida Teste", data="2026-11-01", local="Parque Ibirapuera", cidade="São Paulo",
                  link_inscricao="https://www.ticketsports.com.br/e/teste", fonte_url="https://agenda.example/x")
    padrao.update(campos)
    return Corrida(**padrao)


class TestRegioes(unittest.TestCase):
    def test_locais_conhecidos(self):
        self.assertEqual(classificar("Obelisco do Ibirapuera")[0], ("zona sul",))
        self.assertEqual(classificar("PAMA, Campo de Marte")[0], ("zona norte",))
        self.assertEqual(classificar("Praça Charles Miller")[0], ("centro", "zona oeste"))

    def test_local_citado_primeiro_vence(self):
        self.assertEqual(classificar("Ponte Estaiada, Marginal Pinheiros")[1], "Sul/oeste")

    def test_bairro_e_desconhecido(self):
        self.assertEqual(classificar("Rua das Flores, Moema")[0], ("zona sul",))
        self.assertEqual(classificar("Lagoa do Taquaral"), ((), None))
        self.assertEqual(classificar(None), ((), None))

    def test_locais_da_busca_real(self):
        self.assertEqual(classificar("Parque Burle Marx")[0], ("zona sul",))
        self.assertEqual(classificar("JD. BOTÂNICO")[0], ("zona sul",))
        self.assertEqual(classificar("Obelisco aos Heróis de 32 - Parque do Ibirapuera")[0], ("zona sul",))
        self.assertEqual(classificar("Rua X, Jardim Sul")[0], ("zona sul",))
        self.assertEqual(classificar("Sambódromo do Anhembi")[0], ("zona norte",))

    def test_bairro_citado_primeiro_vence(self):
        self.assertEqual(classificar("Barra Funda, perto de Santana")[0], ("zona oeste",))

    def test_nome_da_prova_quando_o_local_nao_diz(self):
        self.assertEqual(classificar("São Paulo", "Circuito Popular - Etapa 45 - Butanta")[0], ("zona oeste",))
        self.assertEqual(classificar(None, "Woman Run&dance Jardim Sul")[0], ("zona sul",))
        # o local, quando diz algo, vence o nome
        self.assertEqual(classificar("Parque Villa-Lobos", "Corrida do Butantã")[0], ("zona oeste",))
        self.assertEqual(classificar("Parque do Carmo", "Corrida Butantã")[0], ("zona leste",))

    def test_nome_ambiguo_nao_vira_regiao(self):
        self.assertEqual(classificar("São Paulo", "Corrida da Saúde"), ((), None))
        self.assertEqual(classificar(None, "Corrida da Liberdade"), ((), None))
        self.assertEqual(classificar(None, "Meia Maratona de Sumaré"), ((), None))
        self.assertEqual(classificar("Rua da Saúde, 100")[0], ("zona sul",))  # no local, vale

    def test_nao_confunde_palavra_dentro_de_outra(self):
        # "usp" não pode casar com "suspensa"
        self.assertEqual(classificar("Prova suspensa"), ((), None))

    def test_validar_regiao(self):
        self.assertEqual(validar_regiao("Zona Sul"), "zona sul")
        self.assertEqual(validar_regiao("leste"), "zona leste")
        with self.assertRaises(ValueError):
            validar_regiao("zona central")

    def test_consultas(self):
        termos = consultas_da_regiao("zona sul", meses_da_janela(HOJE, 8))
        self.assertIn("corrida de rua zona sul São Paulo outubro 2026", termos)
        self.assertIn("corrida de rua zona sul São Paulo dezembro 2026", termos)
        self.assertEqual(len(termos), len(set(termos)))

    def test_meses_virada_de_ano(self):
        self.assertEqual(meses_da_janela(date(2026, 12, 20), 4), [(2026, 12), (2027, 1)])


class TestAisa(unittest.TestCase):
    def test_envelope(self):
        dados = {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"items": [{"type": "organic"}]}]}]}
        self.assertEqual(extrair_itens(dados), [{"type": "organic"}])

    def test_erro_da_tarefa(self):
        with self.assertRaises(AisaError):
            extrair_itens({"tasks": [{"status_code": 40501, "status_message": "Invalid Field"}]})


class TestExtracao(unittest.TestCase):
    def setUp(self):
        self.resultados = [
            ResultadoBusca("Agenda de corridas SP", "18/10 SporTV Run no Ibirapuera", "https://agenda.example/a", "agenda.example"),
            ResultadoBusca("SporTV Run - Ticket Sports", "Inscrições abertas", "https://www.ticketsports.com.br/e/sportv", "ticketsports.com.br"),
        ]

    def test_interpretar_ignora_anuncios_e_repetidos(self):
        itens = [
            {"type": "paid", "title": "Anúncio", "url": "https://x.example"},
            {"type": "organic", "title": "A", "description": "d", "url": "https://a.example/1"},
            {"type": "organic", "title": "A de novo", "url": "https://a.example/1"},
            {"type": "organic", "title": "Sem URL"},
            {"type": "events", "items": [{"title": "Corrida E", "url": "https://e.example",
                                          "event_dates": {"displayed_dates": "dom., 18 de out."}}]},
        ]
        resultados = interpretar_resultados(itens)
        self.assertEqual([r.url for r in resultados], ["https://a.example/1", "https://e.example"])
        self.assertIn("18 de out", resultados[1].description)

    def test_valida_e_nao_aceita_link_inventado(self):
        dados = {"corridas": [
            {"nome": "SporTV Run", "data": "2026-10-18", "local": "Ibirapuera", "resultado": 0,
             "link_inscricao": "https://site-inventado.example/inscricao"},
        ]}
        [c] = validar_corridas(dados, self.resultados, HOJE)
        self.assertIsNone(c.link_inscricao)
        self.assertEqual(c.fonte_url, "https://agenda.example/a")

    def test_link_da_lista_e_aceito_e_vira_plataforma(self):
        dados = {"corridas": [{"nome": "SporTV Run", "data": "2026-10-18", "resultado": 0,
                               "link_inscricao": "https://www.ticketsports.com.br/e/sportv"}]}
        [c] = validar_corridas(dados, self.resultados, HOJE)
        self.assertEqual(c.plataforma, "Ticket Sports")

    def test_fonte_que_e_plataforma_vira_link(self):
        [c] = validar_corridas({"corridas": [{"nome": "SporTV Run", "data": "2026-10-18", "resultado": 1}]},
                               self.resultados, HOJE)
        self.assertEqual(c.link_inscricao, "https://www.ticketsports.com.br/e/sportv")

    def test_descarta_indice_invalido_e_corrige_campos(self):
        dados = {"corridas": [
            {"nome": "Sem fonte", "data": "2026-10-18", "resultado": 9},
            {"nome": "Índice booleano", "data": "2026-10-18", "resultado": True},
            {"nome": "Data ruim", "data": "2026-02-30", "horario": "7h", "distancias": [5, "10 km"], "resultado": 0},
        ]}
        [c] = validar_corridas(dados, self.resultados, HOJE)
        self.assertEqual(c.nome, "Data ruim")
        self.assertIsNone(c.data)
        self.assertEqual(c.horario, "07:00")
        self.assertEqual(c.distancias, ["5 km", "10 km"])

    def test_extrair_json_com_cercas(self):
        self.assertEqual(extrair_json('```json\n{"corridas": []}\n```'), {"corridas": []})
        self.assertEqual(extrair_json('Claro! {"corridas": []} pronto'), {"corridas": []})
        with self.assertRaises(ValueError):
            extrair_json("sem json")

    def test_datas_por_regras(self):
        self.assertEqual(encontrar_data("Domingo, 18/10/2026", HOJE), date(2026, 10, 18))
        self.assertEqual(encontrar_data("dia 1º de novembro", HOJE), date(2026, 11, 1))
        self.assertEqual(encontrar_data("em 10/03", HOJE), date(2027, 3, 10))  # sem ano: próxima ocorrência
        self.assertIsNone(encontrar_data("sem data aqui", HOJE))

    def test_regras(self):
        resultados = [
            ResultadoBusca("Meia de Sampa 2026 | Inscrições", "15/11/2026 no Parque do Povo, 10k e 21 km",
                           "https://www.ticketsports.com.br/e/meia", "ticketsports.com.br"),
            ResultadoBusca("Pedal noturno", "corrida? não: ciclismo em 15/11", "https://p.example", "p.example"),
            ResultadoBusca("Notícia sem data", "corrida de rua", "https://n.example", "n.example"),
        ]
        [c] = extrair_por_regras(resultados, HOJE)
        self.assertEqual((c.nome, c.data, c.local), ("Meia de Sampa 2026", "2026-11-15", "Parque Do Povo"))
        self.assertEqual(c.distancias, ["10 km", "21 km"])
        self.assertEqual(c.link_inscricao, "https://www.ticketsports.com.br/e/meia")

    def test_llm_fora_do_formato_cai_nas_regras(self):
        class Cliente:
            chamadas = 0

            def conversar(self, *a, **k):
                Cliente.chamadas += 1
                return "não sei"

        corridas, origem = extrair_corridas(Cliente(), self.resultados, cfg(), HOJE)
        self.assertEqual((origem, Cliente.chamadas), ("heuristica", 2))
        self.assertEqual(corridas[0].data, "2026-10-18")

    def test_erro_de_conta_no_llm_nao_e_escondido(self):
        class Cliente:
            def conversar(self, *a, **k):
                raise AisaError("sem saldo", status=402)

        with self.assertRaises(AisaError):
            extrair_corridas(Cliente(), self.resultados, cfg(), HOJE)


class TestCacheBusca(unittest.TestCase):
    """A busca paga fica guardada antes da IA: se a IA falhar, a próxima execução não paga a busca de novo."""

    ITENS = [{"type": "organic", "title": "Corrida do Parque Ibirapuera", "url": "https://agenda.example/a",
              "description": "Domingo, 18/10/2026, 7h, Obelisco do Ibirapuera. 5 km e 10 km."}]

    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.agora = datetime(2026, 10, 16, 9, 0)
        self.cache = CacheBusca(self.pasta, agora=lambda: self.agora)

    def cliente(self, ia_falha: bool):
        teste = self

        class Cliente:
            buscas = 0

            def buscar_google(self, *a):
                Cliente.buscas += 1
                return teste.ITENS

            def conversar(self, *a, **k):
                if ia_falha:
                    raise AisaError("sem saldo", status=402)
                return '{"corridas": []}'

        return Cliente

    def test_falha_da_ia_nao_perde_a_busca(self):
        Falha = self.cliente(ia_falha=True)
        with self.assertRaises(AisaError):
            buscar_consulta(Falha(), cfg(), "corrida zona sul", 20, HOJE, cache=self.cache)
        Ok = self.cliente(ia_falha=False)
        corridas, origem = buscar_consulta(Ok(), cfg(), "corrida zona sul", 20, HOJE, cache=self.cache)
        self.assertEqual((Falha.buscas, Ok.buscas, origem), (1, 0, "llm"))  # a segunda vez não buscou

    def test_reaproveitar_false_busca_de_novo_e_guarda(self):
        Ok = self.cliente(ia_falha=False)
        buscar_consulta(Ok(), cfg(), "corrida zona sul", 20, HOJE, cache=self.cache)
        buscar_consulta(Ok(), cfg(), "corrida zona sul", 20, HOJE, cache=self.cache, reaproveitar=False)
        self.assertEqual(Ok.buscas, 2)
        self.assertIsNotNone(self.cache.ler("corrida zona sul", cfg().search_location, "pt", 20))

    def test_validade_e_parametros(self):
        self.cache.gravar("corrida", "SP", "pt", 20, self.ITENS)
        self.assertEqual(self.cache.ler("corrida", "SP", "pt", 20)[0], self.ITENS)
        self.assertIsNone(self.cache.ler("corrida", "SP", "pt", 50))  # outra profundidade é outra busca
        self.agora += timedelta(hours=25)
        self.assertIsNone(self.cache.ler("corrida", "SP", "pt", 20))  # vencida

    def test_arquivo_estragado_vira_busca_nova(self):
        self.cache.gravar("corrida", "SP", "pt", 20, self.ITENS)
        for arquivo in self.pasta.glob("*.json"):
            arquivo.write_text("{pela metade", encoding="utf-8")
        with self.assertLogs("corridax.cache", level="WARNING"):
            self.assertIsNone(self.cache.ler("corrida", "SP", "pt", 20))


class TestTriagem(unittest.TestCase):
    def t(self, c, regioes=("zona sul",), origem="llm"):
        return triar(c, regioes, HOJE, FIM, "São Paulo", origem)

    def test_aprovada(self):
        c = corrida()
        self.assertEqual(self.t(c), ("aprovada", "ok"))
        self.assertEqual(c.regiao, "Zona sul")

    def test_motivos(self):
        self.assertEqual(self.t(corrida(data=None))[1], "sem_data")
        self.assertEqual(self.t(corrida(data="2026-10-01"))[1], "data_passada")
        self.assertEqual(self.t(corrida(data="2026-12-31"))[1], "fora_da_janela")
        self.assertEqual(self.t(corrida(nome="Pedal Noturno"))[1], "nao_e_corrida")
        self.assertEqual(self.t(corrida(cidade="Campinas"))[1], "fora_da_cidade")
        self.assertEqual(self.t(corrida(local="Campo de Marte"))[1], "fora_da_regiao")
        self.assertEqual(self.t(corrida(local="Praça Fictícia")), ("conferir", "regiao_a_confirmar"))
        self.assertEqual(self.t(corrida(link_inscricao=None)), ("conferir", "sem_link_oficial"))
        self.assertEqual(self.t(corrida(), origem="heuristica"), ("conferir", "extraida_por_regras"))

    def test_cidade_com_sigla(self):
        self.assertEqual(self.t(corrida(cidade="São Paulo - SP"))[0], "aprovada")

    def test_corrida_e_bike_juntas_nao_e_descartada(self):
        self.assertFalse(nao_e_corrida("Bike e Running Porto Autódromo"))
        self.assertTrue(nao_e_corrida("Desafio de Ciclismo"))

    def test_juntar_repetidas(self):
        a = corrida(nome="SporTV Run", link_inscricao=None)
        b = corrida(nome="6ª SporTV Run, Super 10K", horario="07:00", distancias=["10 km"])
        outra = corrida(nome="Night Run")
        mesmo_dia = corrida(nome="Smart Fit Night Run")
        unicas = juntar_repetidas([(a, "q1", "heuristica"), (b, "q2", "llm"), (outra, "q3", "llm"), (mesmo_dia, "q3", "llm")])
        self.assertEqual(len(unicas), 3)  # "Night Run" (1 palavra útil) não engole "Smart Fit Night Run"
        junta, consulta, origem = unicas[0]
        self.assertEqual((junta.horario, origem, consulta), ("07:00", "llm", "q1"))
        self.assertTrue(junta.link_inscricao)

    def test_chave_ignora_ano_e_ordinal(self):
        self.assertEqual(chave(corrida(nome="Corrida Dorina 2026")), chave(corrida(nome="Corrida Dorina")))


class TestEtiquetas(unittest.TestCase):
    def test_tematica_e_noturna(self):
        from corridax.tags import etiquetas

        self.assertEqual(etiquetas(corrida(nome="Corrida da Barbie")), ["tematica"])
        self.assertEqual(etiquetas(corrida(nome="Corrida Tom & Jerry")), ["tematica"])
        self.assertEqual(etiquetas(corrida(nome="Night Run, etapa 2")), ["noturna"])
        self.assertEqual(etiquetas(corrida(nome="Corrida X", horario="19:30")), ["noturna"])
        self.assertEqual(etiquetas(corrida(nome="Meia de Sampa", horario="06:00")), [])

    def test_id_estavel(self):
        from corridax.relatorio import id_da_prova

        self.assertEqual(id_da_prova(corrida(nome="6ª SporTV Run, Super 10K", data="2026-10-18")),
                         "2026-10-18-6a-sportv-run-super-10k")


class TestDemoERelatorio(unittest.TestCase):
    def test_demo_completo(self):
        itens = coletar(ClienteDemo(), cfg(), ["demo"], ("zona sul",), HOJE_DEMO, 20)
        situacoes = {i.corrida.nome: (i.situacao, i.motivo) for i in itens}
        self.assertEqual(situacoes["6ª SporTV Run, Super 10K"], ("aprovada", "ok"))
        self.assertEqual(situacoes["Correndo Contra o Câncer"], ("aprovada", "ok"))  # Ponte Estaiada é sul/oeste
        self.assertEqual(situacoes["Corrida Cartoon"][1], "fora_da_regiao")
        self.assertEqual(situacoes["Pedal Noturno da Zona Sul"][1], "nao_e_corrida")
        self.assertEqual(situacoes["Corrida da Lagoa de Exemplo"][1], "fora_da_cidade")
        self.assertEqual(situacoes["Circuito Sesc de Corridas, etapa Interlagos"][1], "data_passada")
        self.assertEqual(situacoes["101ª Corrida Internacional de São Silvestre"][1], "fora_da_janela")
        aprovadas = [i.corrida.data for i in itens if i.situacao == "aprovada"]
        self.assertEqual(aprovadas, sorted(aprovadas))  # próxima prova primeiro

    def test_csv_e_json(self):
        itens = coletar(ClienteDemo(), cfg(), ["demo"], ("zona sul",), HOJE_DEMO, 20)
        texto = csv_bytes(itens).decode("utf-8-sig")
        linhas = texto.strip().splitlines()
        self.assertTrue(linhas[0].startswith("data;horario;prova"))
        self.assertEqual(len(linhas), len(itens) + 1)
        self.assertIn("18/10/2026", texto)
        cal = calendario_json(itens, "2026-10-15")
        self.assertTrue(all(p["fonte"]["url"] for p in cal["provas"]))
        self.assertEqual(len({p["id"] for p in cal["provas"]}), len(cal["provas"]))
        disney = next(p for p in cal["provas"] if p["nome"] == "Disney Magic Run")
        self.assertEqual((disney["tags"], disney["regioes"]), (["tematica"], ["zona sul"]))
        self.assertEqual(len(cal["provas"]), sum(i.situacao != "descartada" for i in itens))
        self.assertEqual(cal["cidade"], "São Paulo")
        self.assertTrue(all(p["cidade"] == "São Paulo" for p in cal["provas"]))

    def test_cli_demo_grava_arquivos(self):
        with tempfile.TemporaryDirectory() as pasta, redirect_stdout(io.StringIO()) as saida:
            codigo = cli_main(["--demo", "--saida", pasta])
            arquivos = sorted(p.name for p in Path(pasta).rglob("*") if p.is_file())
        self.assertEqual(codigo, 0)
        self.assertEqual(arquivos, ["calendario.csv", "calendario.json"])
        self.assertIn("aprovada(s)", saida.getvalue())

    def test_cli_listar_consultas_sem_chave(self):
        with redirect_stdout(io.StringIO()) as saida:
            codigo = cli_main(["--listar-consultas", "-r", "norte", "--semanas", "4"])
        self.assertEqual(codigo, 0)
        self.assertIn("Campo de Marte", saida.getvalue())

    def test_cli_regiao_invalida(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(["--demo", "-r", "marte"]), 1)


if __name__ == "__main__":
    unittest.main()
