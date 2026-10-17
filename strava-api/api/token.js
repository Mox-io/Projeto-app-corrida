// POST { code } -> troca o código do login do Strava pelas chaves de acesso.
import { rota, trocarCodigo } from "../lib/strava.js";

export default rota((cfg, corpo, fetchFn) => trocarCodigo(cfg, corpo.code, fetchFn));
