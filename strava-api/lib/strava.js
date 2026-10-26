// Ritmex — servidor da conexão com o Strava.
//
// Só faz o que exige o Client Secret (que nunca pode ir para a página):
//   - trocar o código do login do Strava pelas chaves de acesso;
//   - renovar a chave de acesso quando ela vence (a cada 6 horas);
//   - desconectar (revogar o acesso do Ritmex na conta Strava da pessoa).
// Não guarda nada: as atividades são lidas pela própria página, direto do Strava, e mostradas
// só para o atleta que conectou (regra do acordo de API do Strava).

const URL_TOKEN = "https://www.strava.com/oauth/token";
const URL_DESAUTORIZAR = "https://www.strava.com/oauth/deauthorize";

export function configuracao(env = process.env) {
  return {
    clientId: (env.STRAVA_CLIENT_ID || "288160").trim(),
    clientSecret: (env.STRAVA_CLIENT_SECRET || "").trim(),
    origens: (env.ORIGENS_PERMITIDAS || "https://projeto-app-corrida-five.vercel.app,http://localhost:8080")
      .split(",").map((o) => o.trim()).filter(Boolean),
  };
}

export class ErroStrava extends Error {
  constructor(mensagem, status = 400) {
    super(mensagem);
    this.status = status;
  }
}

// Códigos e tokens do Strava são letras e números; qualquer outra coisa nem chega a ser enviada.
const FORMATO = /^[A-Za-z0-9]{10,200}$/;
function exigirFormato(valor, nome) {
  if (typeof valor !== "string" || !FORMATO.test(valor)) throw new ErroStrava(`${nome} inválido.`);
  return valor;
}

async function postarFormulario(url, campos, fetchFn) {
  let resposta;
  try {
    resposta = await fetchFn(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams(campos).toString(),
    });
  } catch {
    throw new ErroStrava("Não foi possível falar com o Strava. Tente de novo.", 502);
  }
  let dados = null;
  try { dados = await resposta.json(); } catch { /* corpo vazio ou não JSON */ }
  if (!resposta.ok) {
    if (resposta.status === 400 || resposta.status === 401) {
      throw new ErroStrava("O Strava recusou o pedido (código vencido ou acesso revogado). Conecte de novo.", 400);
    }
    if (resposta.status === 429) throw new ErroStrava("Muitos pedidos ao Strava agora. Tente em alguns minutos.", 429);
    throw new ErroStrava(`O Strava respondeu com erro ${resposta.status}.`, 502);
  }
  return dados || {};
}

// Só o que a página precisa; o resto da resposta do Strava fica de fora.
function chaves(dados) {
  const a = dados.athlete || null;
  return {
    access_token: dados.access_token,
    refresh_token: dados.refresh_token,
    expires_at: dados.expires_at,
    athlete: a ? { id: a.id, firstname: a.firstname || "", lastname: a.lastname || "", profile_medium: a.profile_medium || "" } : null,
  };
}

export async function trocarCodigo(cfg, codigo, fetchFn = fetch) {
  if (!cfg.clientSecret) throw new ErroStrava("STRAVA_CLIENT_SECRET não está configurado no servidor.", 500);
  const dados = await postarFormulario(URL_TOKEN, {
    client_id: cfg.clientId, client_secret: cfg.clientSecret, code: exigirFormato(codigo, "Código"), grant_type: "authorization_code",
  }, fetchFn);
  return chaves(dados);
}

export async function renovar(cfg, refreshToken, fetchFn = fetch) {
  if (!cfg.clientSecret) throw new ErroStrava("STRAVA_CLIENT_SECRET não está configurado no servidor.", 500);
  const dados = await postarFormulario(URL_TOKEN, {
    client_id: cfg.clientId, client_secret: cfg.clientSecret, refresh_token: exigirFormato(refreshToken, "Token"), grant_type: "refresh_token",
  }, fetchFn);
  return chaves(dados);
}

export async function desconectar(accessToken, fetchFn = fetch) {
  await postarFormulario(URL_DESAUTORIZAR, { access_token: exigirFormato(accessToken, "Token") }, fetchFn);
  return { ok: true };
}

// ---------- HTTP (função da Vercel) ----------

export function aplicarCors(req, res, cfg) {
  const origem = req.headers.origin;
  if (origem && cfg.origens.includes(origem)) {
    res.setHeader("Access-Control-Allow-Origin", origem);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "no-store");
}

// Monta a função da Vercel: CORS, só POST, corpo JSON e erros em português.
export function rota(acao, { env = process.env, fetchFn = fetch } = {}) {
  return async function handler(req, res) {
    const cfg = configuracao(env);
    aplicarCors(req, res, cfg);
    if (req.method === "OPTIONS") return res.status(204).end();
    if (req.method !== "POST") return res.status(405).json({ erro: "Use POST." });
    if (req.headers.origin && !cfg.origens.includes(req.headers.origin)) {
      return res.status(403).json({ erro: "Origem não permitida." });
    }
    let corpo = req.body;
    if (typeof corpo === "string") {
      try { corpo = JSON.parse(corpo); } catch { corpo = null; }
    }
    if (!corpo || typeof corpo !== "object") return res.status(400).json({ erro: "Corpo JSON inválido." });
    try {
      return res.status(200).json(await acao(cfg, corpo, fetchFn));
    } catch (erro) {
      const status = erro instanceof ErroStrava ? erro.status : 500;
      return res.status(status).json({ erro: erro instanceof ErroStrava ? erro.message : "Erro inesperado." });
    }
  };
}
