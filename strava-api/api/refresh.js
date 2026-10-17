// POST { refresh_token } -> nova chave de acesso (a do Strava vence a cada 6 horas).
import { renovar, rota } from "../lib/strava.js";

export default rota((cfg, corpo, fetchFn) => renovar(cfg, corpo.refresh_token, fetchFn));
