"""Testes do app web (sem internet e sem chave)."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import date

from fastapi.testclient import TestClient

from corridax.aisa_client import AisaError
from corridax.demo_data import ClienteDemo
from tests.test_corridax import cfg
from webapp.main import criar_app
from webapp.settings import WebSettings

HOJE = date(2026, 10, 15)


def settings(**ajustes) -> WebSettings:
    base = WebSettings(
        auth_mode="none", firebase_project_id="", firebase_api_key="", firebase_app_id="", firebase_auth_domain="",
        allowed_emails=frozenset(), max_queries=12, max_depth=50,
    )
    return dataclasses.replace(base, **ajustes)


class ClienteQueFalha:
    def __init__(self, status):
        self.status = status

    def buscar_google(self, *a, **k):
        raise AisaError("falhou", status=self.status)


def app_com(cliente=None, **ajustes_settings):
    return TestClient(criar_app(
        settings=settings(**ajustes_settings),
        cfg=cfg(api_key="sk-teste"),
        verificar_token=lambda t: {"tok-ok": "socio@exemplo.com", "tok-outro": "x@exemplo.com"}[t],
        fabrica_cliente=lambda c: cliente or ClienteDemo(),
        hoje=lambda: HOJE,
    ))


class TestApi(unittest.TestCase):
    def setUp(self):
        self.c = app_com()

    def test_config_e_pagina(self):
        dados = self.c.get("/api/config").json()
        self.assertEqual(dados["regions"][0], "zona sul")
        self.assertTrue(dados["hasApiKey"])
        self.assertNotIn("sk-teste", str(dados))  # a chave nunca vai para a página
        self.assertIn("Corrida X", self.c.get("/").text)

    def test_consultas(self):
        r = self.c.post("/api/queries", json={"regions": ["Zona Sul", "norte", "leste", "oeste", "centro"], "weeks": 12,
                                                  "extra": ["corrida noturna"]})
        dados = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(dados["queries"]), 12)
        self.assertGreater(dados["total"], len(dados["queries"]))
        r = self.c.post("/api/queries", json={"regions": ["marte"], "weeks": 4})
        self.assertEqual(r.status_code, 422)

    def test_fluxo_completo(self):
        busca = self.c.post("/api/search", json={"query": "corrida zona sul", "depth": 20}).json()
        self.assertEqual(busca["origem"], "llm")
        corridas = busca["corridas"]
        self.assertGreater(len(corridas), 20)
        triagem = self.c.post("/api/triage", json={"corridas": corridas, "regions": ["zona sul"], "weeks": 8}).json()
        self.assertGreater(triagem["summary"]["aprovada"], 3)
        self.assertEqual(triagem["items"][0]["situacao"], "aprovada")
        csv = self.c.post("/api/csv", json={"corridas": corridas, "regions": ["zona sul"], "weeks": 8})
        self.assertTrue(csv.content.startswith("﻿data;".encode("utf-8")))
        js = self.c.post("/api/json", json={"corridas": corridas, "regions": ["zona sul"], "weeks": 8}).json()
        self.assertEqual(js["gerado_em"], "2026-10-15")

    def test_outra_cidade_sem_zona(self):
        r = self.c.post("/api/queries", json={"city": "campinas", "weeks": 4}).json()
        self.assertEqual((r["city"], r["location"]), ("Campinas", "Campinas,State of Sao Paulo,Brazil"))
        self.assertIn("corrida de rua Campinas novembro 2026", r["queries"])
        # São Paulo continua exigindo zona; cidade repetida exige UF
        self.assertEqual(self.c.post("/api/queries", json={"city": "São Paulo", "weeks": 4}).status_code, 422)
        self.assertEqual(self.c.post("/api/queries", json={"city": "Palmas", "weeks": 4}).status_code, 422)
        self.assertEqual(self.c.post("/api/queries", json={"city": "Palmas", "uf": "TO", "weeks": 4}).status_code, 200)
        self.assertEqual(self.c.post("/api/queries", json={"city": "Campinas", "uf": "XX", "weeks": 4}).status_code, 422)

    def test_triagem_e_json_por_cidade(self):
        prova = {"nome": "Corrida do Taquaral", "data": "2026-11-08", "local": "Lagoa do Taquaral", "cidade": "Campinas",
                 "link_inscricao": "https://www.ticketsports.com.br/e/taquaral", "fonte_url": "https://agenda.example/t",
                 "origem": "llm"}
        de_sp = {**prova, "nome": "Corrida da Paulista", "cidade": "São Paulo", "local": "Avenida Paulista"}
        corpo = {"corridas": [prova, de_sp], "city": "Campinas", "weeks": 8}
        itens = {i["nome"]: i for i in self.c.post("/api/triage", json=corpo).json()["items"]}
        self.assertEqual(itens["Corrida do Taquaral"]["situacao"], "aprovada")  # sem zona, e mesmo assim aprovada
        self.assertEqual(itens["Corrida da Paulista"]["motivo"], "fora_da_cidade")
        js = self.c.post("/api/json", json=corpo).json()
        self.assertEqual(js["cidade"], "Campinas")
        self.assertEqual([(p["cidade"], p["regioes"]) for p in js["provas"]], [("Campinas", [])])

    def test_demo_marca_origem(self):
        busca = self.c.post("/api/search", json={"query": "x", "depth": 5, "demo": True, "use_llm": False}).json()
        self.assertEqual(busca["origem"], "demo")

    def test_limites(self):
        self.assertEqual(self.c.post("/api/search", json={"query": "x", "depth": 51}).status_code, 422)
        self.assertEqual(self.c.post("/api/search", json={"query": "x" * 121, "depth": 5}).status_code, 422)

    def test_valida_corridas_vindas_da_pagina(self):
        base = {"nome": "A", "data": "2026-11-01", "origem": "llm"}
        for ruim in ({"data": "01/11/2026"}, {"link_inscricao": "javascript:alert(1)"}, {"origem": "hacker"},
                     {"fonte_url": "ftp://x"}):
            r = self.c.post("/api/triage", json={"corridas": [{**base, **ruim}], "regions": ["zona sul"], "weeks": 8})
            self.assertEqual(r.status_code, 422, ruim)

    def test_erro_de_conta_da_aisa_vira_424(self):
        c = app_com(ClienteQueFalha(402))
        self.assertEqual(c.post("/api/search", json={"query": "x", "depth": 5}).status_code, 424)
        c = app_com(ClienteQueFalha(503))
        self.assertEqual(c.post("/api/search", json={"query": "x", "depth": 5}).status_code, 502)

    def test_sem_chave_so_demo(self):
        c = TestClient(criar_app(settings=settings(), cfg=cfg(), hoje=lambda: HOJE))
        self.assertEqual(c.post("/api/search", json={"query": "x", "depth": 5}).status_code, 400)
        self.assertEqual(c.post("/api/search", json={"query": "x", "depth": 5, "demo": True}).status_code, 200)


class TestLogin(unittest.TestCase):
    def setUp(self):
        self.c = app_com(auth_mode="firebase", firebase_project_id="p", allowed_emails=frozenset({"socio@exemplo.com"}))
        self.corpo = {"regions": ["zona sul"], "weeks": 4}

    def test_sem_token(self):
        self.assertEqual(self.c.post("/api/queries", json=self.corpo).status_code, 401)

    def test_token_invalido(self):
        r = self.c.post("/api/queries", json=self.corpo, headers={"Authorization": "Bearer tok-que-nao-existe-123"})
        self.assertEqual(r.status_code, 401)

    def test_email_fora_da_lista(self):
        c = TestClient(criar_app(
            settings=settings(auth_mode="firebase", firebase_project_id="p", allowed_emails=frozenset({"a@b.c"})),
            cfg=cfg(), verificar_token=lambda t: "intruso@exemplo.com", hoje=lambda: HOJE,
        ))
        r = c.post("/api/queries", json=self.corpo, headers={"Authorization": "Bearer qualquer-token-longo"})
        self.assertEqual(r.status_code, 403)

    def test_token_ok(self):
        c = TestClient(criar_app(
            settings=settings(auth_mode="firebase", firebase_project_id="p", allowed_emails=frozenset({"socio@exemplo.com"})),
            cfg=cfg(), verificar_token=lambda t: "socio@exemplo.com", hoje=lambda: HOJE,
        ))
        r = c.post("/api/queries", json=self.corpo, headers={"Authorization": "Bearer qualquer-token-longo"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(c.get("/api/config").json()["firebase"].get("senha"))


if __name__ == "__main__":
    unittest.main()
