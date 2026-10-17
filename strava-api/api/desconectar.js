// POST { access_token } -> revoga o acesso do Ritmex na conta Strava da pessoa.
import { desconectar, rota } from "../lib/strava.js";

export default rota((cfg, corpo, fetchFn) => desconectar(corpo.access_token, fetchFn));
