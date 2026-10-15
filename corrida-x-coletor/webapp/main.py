"""API e página do app web.

SEM ESTADO NO SERVIDOR (mesma arquitetura do Prospector). A Vercel executa cada requisição
numa função separada, sem memória compartilhada e sem processos em segundo plano. Por isso o
navegador conduz o fluxo (uma chamada por consulta) e o servidor faz uma única coisa por chamada.

Rotas (exigem login, exceto GET /api/config e os arquivos da página):
  GET  /api/config     dados públicos para montar a tela e fazer login
  POST /api/queries    gera os termos de busca das regiões escolhidas (sem custo)
  POST /api/search     faz UMA consulta no Google e extrai as provas (custa 1 busca + 1 LLM)
  POST /api/triage     junta repetidas, classifica região e faz a triagem (sem custo)
  POST /api/csv        planilha-piloto (sem custo)
  POST /api/json       calendário em JSON para o site do piloto (sem custo)

Erros da AIsa nunca voltam como 401/403 (a página trataria como "sessão expirada"):
  424 = problema de conta/chave/rota na AIsa (repetir não adianta: a página para a coleta)
  502 = falha momentânea da AIsa (rede, instabilidade)
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from corridax.aisa_client import AisaClient, AisaError
from corridax.coleta import buscar_consulta, meses_da_janela, resumo_por_situacao, triar_todas
from corridax.config import Config
from corridax.demo_data import CONSULTA_DEMO, HOJE_DEMO, ClienteDemo
from corridax.regioes import REGIOES, consultas_da_regiao
from corridax.relatorio import calendario_json, csv_bytes

from .auth import criar_verificador_firebase, obter_usuario
from .schemas import PedidoBusca, PedidoConsultas, PedidoTriagem, corrida_para_json, item_para_json
from .settings import WebSettings

log = logging.getLogger(__name__)

PASTA_ESTATICA = Path(__file__).resolve().parent / "static"
ERROS_DE_CONTA = (401, 402, 403, 404)
FUSO = ZoneInfo("America/Sao_Paulo")


def erro_da_aisa(erro: AisaError) -> HTTPException:
    codigo = 424 if erro.status in ERROS_DE_CONTA else 502
    return HTTPException(status_code=codigo, detail=str(erro))


def criar_app(
    settings: WebSettings | None = None,
    cfg: Config | None = None,
    verificar_token: Callable[[str], str] | None = None,
    fabrica_cliente: Callable[[Config], AisaClient] | None = None,
    hoje: Callable[[], date] | None = None,
) -> FastAPI:
    """Monta o app. Os parâmetros existem para os testes injetarem dados falsos."""
    settings = settings or WebSettings.from_env()
    cfg = cfg or Config.from_env(require_api_key=False)
    fabrica_cliente = fabrica_cliente or (lambda c: AisaClient(c.api_key, c.base_url))
    hoje = hoje or (lambda: datetime.now(FUSO).date())  # a Vercel roda em UTC; o calendário é de SP

    app = FastAPI(title="Corrida X — coletor", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.cfg = cfg
    app.state.verificar_token = verificar_token or (
        criar_verificador_firebase(settings.firebase_project_id) if settings.auth_mode == "firebase" else None
    )

    _cliente: dict = {}
    _trava = threading.Lock()

    def cliente_aisa() -> AisaClient:
        if not cfg.api_key:
            raise HTTPException(400, "AISA_API_KEY não configurada no servidor. Use o modo demonstração ou configure a chave.")
        with _trava:
            if "c" not in _cliente:
                _cliente["c"] = fabrica_cliente(cfg)
            return _cliente["c"]

    def dia(demo: bool) -> date:
        return HOJE_DEMO if demo else hoje()

    @app.middleware("http")
    async def cabecalhos_de_seguranca(request: Request, call_next):
        resposta = await call_next(request)
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        resposta.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    # ----- rotas -----

    @app.get("/api/config")
    def configuracao():
        return {
            "authMode": settings.auth_mode,
            "firebase": settings.firebase_public(),
            "hasApiKey": bool(cfg.api_key),
            "city": cfg.city_name,
            "regions": list(REGIOES),
            "today": hoje().isoformat(),
            "demoToday": HOJE_DEMO.isoformat(),
            "defaults": {
                "regions": list(cfg.regions),
                "weeks": cfg.window_weeks,
                "depth": min(cfg.search_depth, settings.max_depth),
            },
            "limits": {"maxQueries": settings.max_queries, "maxDepth": settings.max_depth},
        }

    @app.post("/api/queries")
    def consultas(pedido: PedidoConsultas, usuario: str = Depends(obter_usuario)):
        meses = meses_da_janela(hoje(), pedido.weeks)
        termos = [c for r in pedido.regions for c in consultas_da_regiao(r, meses, cfg.city_name)]
        termos = list(dict.fromkeys(termos + pedido.extra))
        return {"queries": termos[: settings.max_queries], "total": len(termos), "demoQuery": CONSULTA_DEMO}

    @app.post("/api/search")
    def buscar(pedido: PedidoBusca, usuario: str = Depends(obter_usuario)):
        if pedido.depth > settings.max_depth:
            raise HTTPException(422, f"A profundidade máxima é {settings.max_depth}.")
        cliente = ClienteDemo() if pedido.demo else cliente_aisa()
        try:
            corridas, origem = buscar_consulta(
                cliente, cfg, pedido.query, pedido.depth, dia(pedido.demo), usar_llm=pedido.use_llm or pedido.demo
            )
        except AisaError as erro:
            raise erro_da_aisa(erro) from None
        if pedido.demo:
            origem = "demo"
        return {"corridas": [corrida_para_json(c, pedido.query, origem) for c in corridas], "origem": origem}

    def _triar(pedido: PedidoTriagem):
        encontradas = [(c.para_corrida(), c.consulta, c.origem) for c in pedido.corridas]
        return triar_todas(encontradas, cfg, tuple(pedido.regions), dia(pedido.demo), pedido.weeks)

    @app.post("/api/triage")
    def triagem(pedido: PedidoTriagem, usuario: str = Depends(obter_usuario)):
        itens = _triar(pedido)
        return {"items": [item_para_json(i) for i in itens], "summary": resumo_por_situacao(itens)}

    @app.post("/api/csv")
    def baixar_csv(pedido: PedidoTriagem, usuario: str = Depends(obter_usuario)):
        return Response(
            csv_bytes(_triar(pedido)),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="calendario-corrida-x.csv"'},
        )

    @app.post("/api/json")
    def baixar_json(pedido: PedidoTriagem, usuario: str = Depends(obter_usuario)):
        conteudo = calendario_json(_triar(pedido), dia(pedido.demo).isoformat(), cfg.city_name)
        return Response(
            json.dumps(conteudo, ensure_ascii=False, indent=2).encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="calendario-corrida-x.json"'},
        )

    # ----- página -----

    @app.get("/", include_in_schema=False)
    def pagina():
        return FileResponse(PASTA_ESTATICA / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=PASTA_ESTATICA), name="static")
    return app
