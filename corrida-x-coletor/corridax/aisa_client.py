"""Cliente HTTP da AIsa: um único header (Authorization: Bearer) para tudo.

Rotas usadas (conforme a documentação pública da AIsa):
  - Google orgânico (via DataForSEO): POST /apis/v1/dataforseo/serp/google/organic/live/advanced
  - LLM (formato OpenAI):         POST /v1/chat/completions
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# (segundos para conectar, segundos para receber a resposta). A busca "live" do Google
# pode demorar, por isso a leitura tem um prazo generoso.
TIMEOUT = (10, 90)
PARCIAL = 40106  # DataForSEO: "Task completed with partial results"
ERRO_INTERNO = 40101  # DataForSEO: "Internal SE Server Error" (passageiro, sem cobrança)
ESPERAS_ERRO_INTERNO = (5, 15)  # segundos antes de cada nova tentativa


class AisaError(Exception):
    """Falha ao falar com a AIsa. A mensagem já vem em português e sem dados sensíveis.

    `status` é o HTTP; `codigo` é o código do provedor de dados (DataForSEO), quando houver.
    """

    def __init__(self, mensagem: str, status: int | None = None, codigo: int | None = None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo


_MENSAGENS_HTTP = {
    401: "Chave da AIsa inválida ou ausente. Confira AISA_API_KEY no arquivo .env.",
    402: "A AIsa recusou a chamada por saldo/crédito. Verifique seu saldo no console da AIsa.",
    403: "Sem permissão para este recurso com a chave atual. Verifique o plano/permissões no console da AIsa.",
    404: "Rota não encontrada na AIsa. Ela pode ter mudado; confira a documentação em https://aisa.one/docs.",
    429: "Limite de requisições da AIsa atingido. Aguarde um pouco e tente de novo.",
}


class AisaClient:
    def __init__(self, api_key: str, base_url: str = "https://api.aisa.one", session: requests.Session | None = None,
                 esperar=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.esperar = esperar  # os testes trocam por uma função que não espera
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        if session is None:
            # Retentativas só para "muitas requisições" (429) e indisponibilidade momentânea
            # (502/503/504). NÃO repetimos em erro 500 nem em timeout: a busca no Google é cobrada
            # por chamada e repetir às cegas poderia cobrar duas vezes.
            retry = Retry(
                total=2,
                backoff_factor=2.0,
                status_forcelist=(429, 502, 503, 504),
                allowed_methods=frozenset({"POST"}),
                respect_retry_after_header=True,
                raise_on_status=False,
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def post(self, path: str, corpo: Any) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resposta = self.session.post(url, json=corpo, timeout=TIMEOUT)
        except requests.exceptions.Timeout:
            raise AisaError("A AIsa demorou demais para responder (timeout). Tente novamente.") from None
        except requests.exceptions.ConnectionError:
            raise AisaError("Não foi possível conectar à AIsa. Verifique sua internet.") from None
        except requests.exceptions.RequestException as erro:
            raise AisaError(f"Falha de rede ao chamar a AIsa: {type(erro).__name__}.") from None

        if resposta.status_code >= 400:
            base = _MENSAGENS_HTTP.get(resposta.status_code, f"A AIsa respondeu com erro HTTP {resposta.status_code}.")
            # Só um trecho curto do corpo, para diagnóstico; o header (com a chave) nunca é exibido.
            trecho = resposta.text.strip().replace("\n", " ")[:200]
            if "model_route_not_supported" in resposta.text or "model_not_found" in resposta.text:
                base = ("O modelo de IA do .env (AISA_MODEL) não está disponível na sua conta da AIsa. "
                        "Escolha outro da lista em https://api.aisa.one/v1/models (ex.: gpt-4.1-mini).")
            detalhe = f" Detalhe: {trecho}" if trecho else ""
            raise AisaError(base + detalhe, status=resposta.status_code)

        try:
            dados = resposta.json()
        except ValueError:
            raise AisaError("A AIsa devolveu uma resposta que não é JSON válido.", status=resposta.status_code) from None
        if not isinstance(dados, dict):
            raise AisaError("A AIsa devolveu um JSON em formato inesperado.", status=resposta.status_code)
        return dados

    # ---------- Chamadas de alto nível ----------

    def buscar_google(self, palavra_chave: str, local: str, idioma: str, profundidade: int) -> list[dict]:
        """Busca orgânica no Google e devolve a lista bruta de itens (dicts do DataForSEO)."""
        corpo = [
            {
                "keyword": palavra_chave,
                "location_name": local,
                "language_code": idioma,
                "depth": profundidade,
            }
        ]
        # O erro interno do provedor (40101) é passageiro e não é cobrado: tenta de novo, com espera.
        for espera in (*ESPERAS_ERRO_INTERNO, None):
            dados = self.post("/apis/v1/dataforseo/serp/google/organic/live/advanced", corpo)
            try:
                return extrair_itens(dados)
            except AisaError as erro:
                if erro.codigo != ERRO_INTERNO or espera is None:
                    raise
                log.warning("  O Google (provedor) teve um erro interno; tentando de novo em %d s...", espera)
                self.esperar(espera)
        raise AssertionError("inalcançável")

    def conversar(self, modelo: str, mensagens: list[dict], temperatura: float = 0.4, max_tokens: int = 1800) -> str:
        """Chama o LLM (chat/completions, formato OpenAI) e devolve o texto da resposta."""
        dados = self.post(
            "/v1/chat/completions",
            {"model": modelo, "messages": mensagens, "temperature": temperatura, "max_tokens": max_tokens},
        )
        try:
            conteudo = dados["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AisaError("Resposta do LLM sem o campo choices[0].message.content.") from None
        if isinstance(conteudo, list):  # alguns provedores devolvem blocos de texto
            conteudo = "".join(bloco.get("text", "") for bloco in conteudo if isinstance(bloco, dict))
        if not isinstance(conteudo, str) or not conteudo.strip():
            mensagem = dados["choices"][0].get("message") or {}
            if mensagem.get("reasoning_content") or mensagem.get("reasoning"):
                # Modelos que "pensam" (ex.: deepseek) podem gastar todo o max_tokens no raciocínio.
                raise AisaError("O modelo gastou a resposta inteira raciocinando e não devolveu o JSON. "
                                "Use em AISA_MODEL um modelo sem raciocínio (ex.: qwen-flash ou gpt-4.1-mini).")
            raise AisaError("O LLM devolveu uma resposta vazia.")
        return conteudo


def extrair_itens(dados: dict) -> list[dict]:
    """Abre o "envelope" do DataForSEO: tasks[0].result[0].items.

    Códigos 20000 = sucesso; 40106 = resultado parcial (algumas páginas do Google não vieram; as que
    vieram já foram cobradas), que é aproveitado com um aviso. Qualquer outro vira um erro legível.
    """
    codigo = dados.get("status_code")
    if codigo not in (None, 20000):
        raise AisaError(f"Erro do provedor de dados: {dados.get('status_message', 'sem detalhe')} (código {codigo}).")

    tarefas = dados.get("tasks") or []
    if not tarefas:
        raise AisaError("Resposta da busca sem a lista 'tasks'.")
    tarefa = tarefas[0]
    codigo_tarefa = tarefa.get("status_code")
    resultados = tarefa.get("result") or []
    if codigo_tarefa == PARCIAL and resultados:
        log.warning("  Busca com resultado parcial (o provedor não trouxe todas as páginas); usando o que veio.")
    elif codigo_tarefa not in (None, 20000):
        raise AisaError(f"Busca recusada: {tarefa.get('status_message', 'sem detalhe')} (código {codigo_tarefa}).",
                        codigo=codigo_tarefa)

    if not resultados or not isinstance(resultados[0], dict):
        return []  # busca válida, mas sem resultados
    return [item for item in (resultados[0].get("items") or []) if isinstance(item, dict)]
