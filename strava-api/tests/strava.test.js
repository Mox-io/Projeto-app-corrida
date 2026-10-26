// Testes sem internet: o Strava é simulado. Rodar com: node --test tests/
import assert from "node:assert/strict";
import { test } from "node:test";

import { rota, trocarCodigo, renovar } from "../lib/strava.js";

const ENV = { STRAVA_CLIENT_ID: "288160", STRAVA_CLIENT_SECRET: "segredo-de-teste" };
const CFG = { clientId: "288160", clientSecret: "segredo-de-teste", origens: ["https://projeto-app-corrida-five.vercel.app"] };

function stravaFalso(status, corpo) {
  const chamadas = [];
  const fetchFn = async (url, opcoes) => {
    chamadas.push({ url, corpo: Object.fromEntries(new URLSearchParams(opcoes.body)) });
    return { ok: status < 400, status, json: async () => corpo };
  };
  return { fetchFn, chamadas };
}

function chamar(handler, { method = "POST", origin = "https://projeto-app-corrida-five.vercel.app", body } = {}) {
  const res = {
    headers: {}, statusCode: 0, corpo: undefined,
    setHeader(k, v) { this.headers[k] = v; },
    status(c) { this.statusCode = c; return this; },
    json(d) { this.corpo = d; return this; },
    end() { return this; },
  };
  return handler({ method, headers: origin ? { origin } : {}, body }, res).then(() => res);
}

test("troca o código e devolve só o necessário", async () => {
  const { fetchFn, chamadas } = stravaFalso(200, {
    access_token: "acesso123456", refresh_token: "renova123456", expires_at: 1790000000, token_type: "Bearer",
    athlete: { id: 42, firstname: "Ana", lastname: "Lima", profile_medium: "https://x/a.jpg", weight: 60 },
  });
  const r = await trocarCodigo(CFG, "abcdef0123456789", fetchFn);
  assert.deepEqual(r.athlete, { id: 42, firstname: "Ana", lastname: "Lima", profile_medium: "https://x/a.jpg" });
  assert.equal(r.token_type, undefined);
  assert.deepEqual(chamadas[0].corpo, {
    client_id: "288160", client_secret: "segredo-de-teste", code: "abcdef0123456789", grant_type: "authorization_code",
  });
});

test("código com formato estranho nem é enviado ao Strava", async () => {
  const { fetchFn, chamadas } = stravaFalso(200, {});
  await assert.rejects(trocarCodigo(CFG, "abc&client_secret=x", fetchFn), /inválido/);
  assert.equal(chamadas.length, 0);
});

test("token vencido ou revogado vira mensagem para conectar de novo", async () => {
  const { fetchFn } = stravaFalso(400, { message: "Bad Request" });
  await assert.rejects(renovar(CFG, "renova123456", fetchFn), /Conecte de novo/);
});

test("sem o segredo configurado, avisa", async () => {
  await assert.rejects(trocarCodigo({ ...CFG, clientSecret: "" }, "abcdef0123456789", async () => {}), /STRAVA_CLIENT_SECRET/);
});

test("rota: CORS só para o Ritmex, só POST", async () => {
  const { fetchFn } = stravaFalso(200, { access_token: "a1234567890", refresh_token: "r1234567890", expires_at: 1 });
  const handler = rota((cfg, corpo, f) => renovar(cfg, corpo.refresh_token, f), { env: ENV, fetchFn });

  const ok = await chamar(handler, { body: { refresh_token: "renova123456" } });
  assert.equal(ok.statusCode, 200);
  assert.equal(ok.headers["Access-Control-Allow-Origin"], "https://projeto-app-corrida-five.vercel.app");

  const outraOrigem = await chamar(handler, { origin: "https://site-estranho.example", body: { refresh_token: "renova123456" } });
  assert.equal(outraOrigem.statusCode, 403);
  assert.equal(outraOrigem.headers["Access-Control-Allow-Origin"], undefined);

  assert.equal((await chamar(handler, { method: "GET" })).statusCode, 405);
  assert.equal((await chamar(handler, { method: "OPTIONS" })).statusCode, 204);
  assert.equal((await chamar(handler, { body: "não é json" })).statusCode, 400);
});

test("erro inesperado não vaza detalhes", async () => {
  const handler = rota(() => { throw new Error("detalhe interno com segredo"); }, { env: ENV });
  const res = await chamar(handler, { body: {} });
  assert.equal(res.statusCode, 500);
  assert.equal(res.corpo.erro, "Erro inesperado.");
});
