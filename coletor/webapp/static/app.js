// Corrida X (coletor) — lógica da página. Mesma base do Prospector.
//
// Regras deste arquivo:
//  1. Nada que vem do Google (nome da prova, local, links...) entra na página como HTML: tudo é
//     montado com textContent (via el()), e só links http(s) viram <a>.
//  2. A chave da AIsa nunca passa por aqui. A página só fala com o nosso servidor.
//  3. O servidor não guarda estado (roda em funções serverless). Quem conduz o fluxo é esta
//     página: uma chamada por consulta. As provas encontradas ficam na memória da página (e no
//     sessionStorage, para sobreviver a um recarregamento).
"use strict";

const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
const CHAVE_SESSAO = "corridax-sessao";

function el(tag, atributos = {}, ...filhos) {
  const no = document.createElement(tag);
  for (const [chave, valor] of Object.entries(atributos)) {
    if (valor === false || valor == null) continue;
    if (chave === "class") no.className = valor;
    else no.setAttribute(chave, valor === true ? "" : valor);
  }
  for (const filho of filhos.flat()) if (filho != null && filho !== false) no.append(filho);
  return no;
}

const estado = {
  config: null,
  getToken: async () => null,
  sair: null,
  regioes: new Set(),
  corridas: [], // provas como vieram das buscas (sem triagem)
  itens: [], // provas triadas pelo servidor
  resumo: null,
  demoDados: false, // as provas guardadas são da demonstração?
  consultasPrevistas: [],
  totalConsultas: 0,
  ocupado: false,
  cancelar: false,
  progresso: [],
  erroTarefa: "",
  tituloTarefa: "Andamento",
  appConfigurado: false,
};

// ---------- Chamadas ao servidor ----------

class ErroApi extends Error {
  constructor(mensagem, status) {
    super(mensagem);
    this.status = status;
  }
}

async function api(caminho, { json } = {}) {
  const cabecalhos = {};
  const token = await estado.getToken();
  if (token) cabecalhos.Authorization = `Bearer ${token}`;
  const opcoes = { method: json ? "POST" : "GET", headers: cabecalhos };
  if (json) {
    cabecalhos["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(json);
  }

  let resposta;
  try {
    resposta = await fetch(caminho, opcoes);
  } catch {
    throw new ErroApi("Sem conexão com o servidor. Verifique sua internet.", 0);
  }
  if (resposta.ok) return resposta;

  let mensagem = `Erro ${resposta.status}.`;
  try {
    const dados = await resposta.json();
    if (typeof dados.detail === "string") mensagem = dados.detail;
    else if (Array.isArray(dados.detail)) mensagem = dados.detail.map((d) => d.msg).join(" ");
  } catch {
    /* corpo sem JSON: mantém a mensagem padrão */
  }
  if (estado.config?.authMode === "firebase" && (resposta.status === 401 || resposta.status === 403)) {
    if (estado.sair) await estado.sair();
    mostrarLogin(mensagem);
  }
  throw new ErroApi(mensagem, resposta.status);
}

const apiJson = async (caminho, json) => (await api(caminho, { json })).json();

// 424 = a AIsa recusou por conta/chave/rota: repetir a chamada não adianta.
const erroFatal = (erro) => erro.status === 424 || erro.status === 401 || erro.status === 403;

async function baixar(caminho, json, nomePadrao) {
  const resposta = await api(caminho, { json });
  const blob = await resposta.blob();
  const disposicao = resposta.headers.get("Content-Disposition") || "";
  const nome = /filename="([^"]+)"/.exec(disposicao)?.[1] || nomePadrao;
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: nome });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 15000);
}

function mostrarErro(seletor, mensagem) {
  const caixa = $(seletor);
  caixa.textContent = mensagem || "";
  caixa.hidden = !mensagem;
}

// ---------- Sessão (sobrevive a recarregar a página) ----------

function salvarSessao() {
  try {
    sessionStorage.setItem(
      CHAVE_SESSAO,
      JSON.stringify({
        corridas: estado.corridas,
        demoDados: estado.demoDados,
        regioes: [...estado.regioes],
        semanas: $("#f-semanas").value,
      })
    );
  } catch {
    /* sem armazenamento (modo privado, cheio...): segue só em memória */
  }
}

function restaurarSessao() {
  try {
    const dados = JSON.parse(sessionStorage.getItem(CHAVE_SESSAO) || "null");
    if (!dados || !Array.isArray(dados.corridas)) return;
    estado.corridas = dados.corridas;
    estado.demoDados = Boolean(dados.demoDados);
    if (Array.isArray(dados.regioes) && dados.regioes.length) {
      estado.regioes = new Set(dados.regioes.filter((r) => estado.config.regions.includes(r)));
    }
    if (dados.semanas) $("#f-semanas").value = dados.semanas;
  } catch {
    estado.corridas = [];
  }
}

// ---------- Login (Firebase) ----------

function mostrarLogin(mensagem = "") {
  $("#tela-app").hidden = true;
  $("#tela-login").hidden = false;
  $("#btn-sair").hidden = true;
  $("#usuario-email").textContent = "";
  mostrarErro("#login-erro", mensagem);
}

function mostrarApp(rotuloUsuario) {
  $("#tela-login").hidden = true;
  $("#tela-app").hidden = false;
  $("#usuario-email").textContent = rotuloUsuario;
  $("#btn-sair").hidden = estado.config.authMode !== "firebase";
  configurarApp();
}

const ERROS_LOGIN = {
  "auth/invalid-credential": "E-mail ou senha incorretos.",
  "auth/user-not-found": "E-mail ou senha incorretos.",
  "auth/wrong-password": "E-mail ou senha incorretos.",
  "auth/invalid-email": "E-mail inválido.",
  "auth/too-many-requests": "Muitas tentativas. Aguarde um pouco e tente de novo.",
  "auth/network-request-failed": "Sem conexão com a internet.",
};

async function iniciarFirebase(configFirebase) {
  const base = "https://www.gstatic.com/firebasejs/10.13.0/";
  let modulos;
  try {
    modulos = await Promise.all([import(`${base}firebase-app.js`), import(`${base}firebase-auth.js`)]);
  } catch {
    mostrarLogin("Não foi possível carregar o login (sem internet?). Recarregue a página.");
    return;
  }
  const [{ initializeApp }, { getAuth, signInWithEmailAndPassword, onAuthStateChanged, signOut }] = modulos;
  const auth = getAuth(initializeApp(configFirebase));

  estado.getToken = async () => (auth.currentUser ? auth.currentUser.getIdToken() : null);
  estado.sair = () => signOut(auth);

  $("#form-login").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    mostrarErro("#login-erro", "");
    const botao = $("#btn-entrar");
    botao.disabled = true;
    botao.textContent = "Entrando...";
    try {
      await signInWithEmailAndPassword(auth, $("#login-email").value.trim(), $("#login-senha").value);
    } catch (erro) {
      mostrarErro("#login-erro", ERROS_LOGIN[erro.code] || "Não foi possível entrar. Tente novamente.");
    } finally {
      botao.disabled = false;
      botao.textContent = "Entrar";
    }
  });
  $("#btn-sair").addEventListener("click", async () => {
    try {
      sessionStorage.removeItem(CHAVE_SESSAO);
    } catch {
      /* ignora */
    }
    await signOut(auth);
  });

  onAuthStateChanged(auth, (usuario) => {
    if (usuario) mostrarApp(usuario.email);
    else mostrarLogin();
  });
}

// ---------- Formulário ----------

const NOMES_REGIOES = { "zona sul": "Zona sul", "zona norte": "Zona norte", "zona leste": "Zona leste", "zona oeste": "Zona oeste", centro: "Centro" };

function lerInteiro(seletor, nome, minimo, maximo) {
  const texto = $(seletor).value.trim();
  if (!/^\d+$/.test(texto)) throw new Error(`${nome}: informe um número inteiro.`);
  const n = Number(texto);
  if (n < minimo || n > maximo) throw new Error(`${nome}: use um valor entre ${minimo} e ${maximo}.`);
  return n;
}

function lerFiltros() {
  const { limits } = estado.config;
  if (!estado.regioes.size) throw new Error("Escolha ao menos uma região.");
  return {
    regions: [...estado.regioes],
    weeks: lerInteiro("#f-semanas", "Semanas à frente", 1, 52),
    depth: lerInteiro("#f-profundidade", "Resultados por consulta", 1, limits.maxDepth),
    limite: lerInteiro("#f-limite", "Máx. de consultas", 1, limits.maxQueries),
    extra: $("#f-extras").value.split("\n").map((t) => t.trim()).filter(Boolean).slice(0, 10),
    useLlm: $("#f-llm").checked,
    demo: $("#f-demo").checked,
  };
}

function renderRegioes() {
  const caixa = $("#regioes");
  caixa.replaceChildren(
    ...estado.config.regions.map((r) => {
      const botao = el("button", { type: "button", "aria-pressed": String(estado.regioes.has(r)) }, NOMES_REGIOES[r] || r);
      botao.disabled = estado.ocupado;
      botao.addEventListener("click", () => {
        if (estado.regioes.has(r)) estado.regioes.delete(r);
        else estado.regioes.add(r);
        renderRegioes();
        aoMudarFiltros();
      });
      return botao;
    })
  );
}

let temporizadorPlano = null;
function aoMudarFiltros() {
  clearTimeout(temporizadorPlano);
  temporizadorPlano = setTimeout(async () => {
    await atualizarPlano();
    if (estado.corridas.length && !estado.ocupado) await retriar();
  }, 350);
}

async function atualizarPlano() {
  mostrarErro("#busca-erro", "");
  let f;
  try {
    f = lerFiltros();
  } catch (erro) {
    $("#plano").textContent = erro.message;
    $("#lista-consultas").replaceChildren();
    return;
  }
  if (f.demo) {
    $("#plano").textContent = "Demonstração: busca e IA simuladas com a amostra do projeto piloto. Sem custo.";
    $("#lista-consultas").replaceChildren(el("li", {}, "(nenhuma consulta real no modo demonstração)"));
    return;
  }
  try {
    const dados = await apiJson("/api/queries", { regions: f.regions, weeks: f.weeks, extra: f.extra });
    estado.consultasPrevistas = dados.queries;
    estado.totalConsultas = dados.total;
  } catch (erro) {
    $("#plano").textContent = erro.message;
    return;
  }
  const usadas = Math.min(f.limite, estado.consultasPrevistas.length);
  $("#lista-consultas").replaceChildren(
    ...estado.consultasPrevistas.map((c, i) => el("li", { class: i < usadas ? null : "fora" }, c))
  );
  const custo = `${usadas} busca(s) no Google (até ${f.depth} resultados cada)` + (f.useLlm ? ` + ${usadas} leitura(s) com IA` : "");
  const sobra = estado.totalConsultas > usadas ? ` ${estado.totalConsultas - usadas} consulta(s) ficam de fora pelo limite.` : "";
  $("#plano").textContent = `Custo: ${custo} — consome créditos da AIsa.${sobra}`;
}

// ---------- Tarefas ----------

function log(mensagem) {
  estado.progresso.push(mensagem);
  if (estado.progresso.length > 60) estado.progresso.shift();
  renderTarefa();
}

function definirOcupado(ocupado, titulo) {
  estado.ocupado = ocupado;
  if (titulo) estado.tituloTarefa = titulo;
  if (ocupado) {
    estado.cancelar = false;
    estado.progresso = [];
    estado.erroTarefa = "";
  }
  renderTudo();
}

async function iniciarBusca(evento) {
  evento.preventDefault();
  if (estado.ocupado) return;
  mostrarErro("#busca-erro", "");
  let f;
  try {
    f = lerFiltros();
  } catch (erro) {
    mostrarErro("#busca-erro", erro.message);
    return;
  }
  if (!f.demo && !estado.config.hasApiKey) {
    mostrarErro("#busca-erro", "A chave da AIsa não está configurada no servidor. Use o modo demonstração.");
    return;
  }

  const botao = $("#btn-buscar");
  botao.textContent = "Buscando...";
  definirOcupado(true, "Buscando provas");
  try {
    let consultas;
    if (f.demo) {
      consultas = [(await apiJson("/api/queries", { regions: f.regions, weeks: f.weeks, extra: [] })).demoQuery];
    } else {
      const dados = await apiJson("/api/queries", { regions: f.regions, weeks: f.weeks, extra: f.extra });
      consultas = dados.queries.slice(0, f.limite);
    }

    const novas = [];
    for (const [i, consulta] of consultas.entries()) {
      if (estado.cancelar) {
        log("Cancelado. As provas já encontradas foram mantidas.");
        break;
      }
      log(`(${i + 1}/${consultas.length}) ${consulta}`);
      try {
        const dados = await apiJson("/api/search", { query: consulta, depth: f.depth, use_llm: f.useLlm, demo: f.demo });
        novas.push(...dados.corridas);
        log(`   ${dados.corridas.length} prova(s)${dados.origem === "heuristica" ? " (regras, sem IA)" : ""}`);
      } catch (erro) {
        if (erroFatal(erro)) throw erro;
        log(`   falhou: ${erro.message}`);
      }
    }
    estado.corridas = novas;
    estado.demoDados = f.demo;
    salvarSessao();
    await retriar();
    if (estado.resumo) log(`Pronto: ${estado.resumo.aprovada} aprovada(s), ${estado.resumo.conferir} a conferir.`);
  } catch (erro) {
    estado.erroTarefa = erro.message;
  } finally {
    botao.textContent = "Buscar provas";
    definirOcupado(false, estado.erroTarefa ? "Busca interrompida" : "Busca concluída");
  }
}

async function retriar() {
  if (!estado.corridas.length) {
    estado.itens = [];
    estado.resumo = null;
    renderTudo();
    return;
  }
  let semanas;
  try {
    semanas = lerInteiro("#f-semanas", "Semanas à frente", 1, 52);
  } catch {
    return; // campo sendo editado: mantém o calendário atual
  }
  if (!estado.regioes.size) return;
  try {
    const dados = await apiJson("/api/triage", corpoTriagem(semanas));
    estado.itens = dados.items;
    estado.resumo = dados.summary;
    salvarSessao();
  } catch (erro) {
    mostrarErro("#baixar-erro", erro.message);
  }
  renderTudo();
}

function corpoTriagem(semanas) {
  return {
    corridas: estado.corridas,
    regions: [...estado.regioes],
    weeks: semanas ?? lerInteiro("#f-semanas", "Semanas à frente", 1, 52),
    demo: estado.demoDados,
  };
}

// ---------- Renderização ----------

function renderTudo() {
  renderTarefa();
  renderRegioes();
  renderCalendario();
  $("#btn-buscar").disabled = estado.ocupado;
  $("#btn-csv").disabled = estado.ocupado || !estado.itens.length;
  $("#btn-json").disabled = estado.ocupado || !estado.itens.length;
}

function renderTarefa() {
  const visivel = estado.ocupado || estado.progresso.length > 0 || Boolean(estado.erroTarefa);
  $("#painel-progresso").hidden = !visivel;
  $("#titulo-progresso").firstChild.textContent = `${estado.tituloTarefa} `;
  $("#spinner-tarefa").hidden = !estado.ocupado;
  $("#lista-progresso").replaceChildren(...estado.progresso.map((m) => el("li", {}, m)));
  mostrarErro("#erro-tarefa", estado.erroTarefa);
  $("#btn-cancelar").hidden = !estado.ocupado;
}

const dataBR = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

function tituloDoDia(iso) {
  if (!iso) return "Sem data";
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
}

function link(url, texto) {
  if (typeof url !== "string" || !/^https?:\/\//i.test(url)) return null;
  return el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, texto);
}

function criarProva(item) {
  const selo =
    item.situacao === "aprovada"
      ? null
      : el("span", { class: `selo ${item.situacao === "conferir" ? "selo--warn" : ""}` }, item.situacao === "conferir" ? "a conferir" : "descartada");

  const meta = [item.horario, item.local || "local não informado", item.regiao].filter(Boolean).join(" · ");
  const detalhes = [
    item.distancias?.length ? item.distancias.join(", ") : null,
    item.organizador ? `Organização: ${item.organizador}` : null,
  ].filter(Boolean);
  const extras = [item.preco ? `Preço: ${item.preco}` : null, item.porte ? `Porte: ${item.porte}` : null].filter(Boolean);

  return el(
    "li",
    { class: `prova prova--${item.situacao}` },
    el("div", { class: "prova-cab" }, el("div", {}, el("div", { class: "prova-nome" }, item.nome), el("div", { class: "prova-meta" }, meta)), selo),
    detalhes.length ? el("div", { class: "prova-linha" }, detalhes.join(" · ")) : null,
    extras.length ? el("div", { class: "prova-linha" }, extras.join(" · ")) : null,
    item.situacao !== "aprovada" ? el("div", { class: "prova-linha" }, item.motivo_texto) : null,
    el(
      "div",
      { class: "prova-links" },
      link(item.link_inscricao, `Inscrição${item.plataforma ? ` (${item.plataforma})` : ""}`),
      link(item.fonte_url, `Fonte: ${item.fonte_nome || "página"}`)
    )
  );
}

function renderCalendario() {
  const painel = $("#painel-resultados");
  painel.hidden = !estado.itens.length;
  if (!estado.itens.length) return;

  const r = estado.resumo || { aprovada: 0, conferir: 0, descartada: 0 };
  $("#resumo").replaceChildren(
    el("span", { class: "selo selo--ok" }, `${r.aprovada} aprovada(s)`),
    el("span", { class: "selo selo--warn" }, `${r.conferir} a conferir`),
    el("span", { class: "selo" }, `${r.descartada} descartada(s)`),
    estado.demoDados ? el("span", { class: "selo selo--erro" }, "demonstração: links fictícios") : null
  );

  const hoje = estado.demoDados ? estado.config.demoToday : estado.config.today;
  const semanas = Number($("#f-semanas").value) || estado.config.defaults.weeks;
  const fim = new Date(`${hoje}T12:00:00`);
  fim.setDate(fim.getDate() + semanas * 7);
  $("#info-janela").textContent =
    `Próximas provas de ${dataBR(hoje)} a ${fim.toLocaleDateString("pt-BR")}` +
    (estado.demoDados ? " (data fixa da demonstração)." : ".") +
    ` Regiões: ${[...estado.regioes].map((x) => NOMES_REGIOES[x] || x).join(", ")}.`;

  const mostrar = { aprovada: true, conferir: $("#mostrar-conferir").checked, descartada: $("#mostrar-descartadas").checked };
  const visiveis = estado.itens.filter((i) => mostrar[i.situacao]);
  // A ordem do servidor é por situação; aqui o calendário é por data (próxima prova primeiro).
  visiveis.sort((a, b) => (a.data || "9999").localeCompare(b.data || "9999") || (a.horario || "99").localeCompare(b.horario || "99"));

  const grupos = new Map();
  for (const item of visiveis) {
    const chave = item.data || "";
    if (!grupos.has(chave)) grupos.set(chave, []);
    grupos.get(chave).push(item);
  }
  const blocos = [];
  for (const [dia, itens] of grupos) {
    blocos.push(el("h3", { class: "dia" }, tituloDoDia(dia)), el("ul", { class: "provas" }, itens.map(criarProva)));
  }
  $("#calendario").replaceChildren(...(blocos.length ? blocos : [el("p", { class: "vazio" }, "Nenhuma prova com os filtros atuais.")]));
}

// ---------- Início ----------

function configurarApp() {
  if (estado.appConfigurado) return;
  estado.appConfigurado = true;
  const { defaults, limits, hasApiKey } = estado.config;

  estado.regioes = new Set(defaults.regions.filter((r) => estado.config.regions.includes(r)));
  $("#f-semanas").value = String(defaults.weeks);
  $("#f-profundidade").value = String(defaults.depth);
  $("#f-limite").value = String(Math.min(6, limits.maxQueries));

  if (!hasApiKey) {
    const aviso = $("#aviso-config");
    aviso.textContent = "A chave da AIsa não está configurada no servidor: por enquanto só o modo demonstração funciona.";
    aviso.hidden = false;
    $("#f-demo").checked = true;
  }

  restaurarSessao();
  renderTudo();
  atualizarPlano().then(() => (estado.corridas.length ? retriar() : null));

  $("#form-busca").addEventListener("submit", iniciarBusca);
  for (const id of ["#f-semanas", "#f-profundidade", "#f-limite", "#f-extras"]) $(id).addEventListener("input", aoMudarFiltros);
  for (const id of ["#f-llm", "#f-demo"]) $(id).addEventListener("change", () => atualizarPlano());
  $("#mostrar-conferir").addEventListener("change", renderCalendario);
  $("#mostrar-descartadas").addEventListener("change", renderCalendario);
  $("#btn-cancelar").addEventListener("click", () => {
    estado.cancelar = true;
    log("Cancelando depois da consulta atual...");
  });
  $("#btn-csv").addEventListener("click", () => baixarArquivo("/api/csv", "calendario-corrida-x.csv", "#btn-csv"));
  $("#btn-json").addEventListener("click", () => baixarArquivo("/api/json", "calendario-corrida-x.json", "#btn-json"));
  $("#btn-limpar").addEventListener("click", () => {
    estado.corridas = [];
    estado.itens = [];
    estado.resumo = null;
    estado.progresso = [];
    estado.erroTarefa = "";
    salvarSessao();
    renderTudo();
  });
}

async function baixarArquivo(caminho, nome, seletor) {
  mostrarErro("#baixar-erro", "");
  const botao = $(seletor);
  const texto = botao.textContent;
  botao.disabled = true;
  botao.textContent = "Gerando...";
  try {
    await baixar(caminho, corpoTriagem(), nome);
  } catch (erro) {
    mostrarErro("#baixar-erro", erro.message);
  } finally {
    botao.textContent = texto;
    botao.disabled = false;
  }
}

async function iniciar() {
  try {
    const resposta = await fetch("/api/config");
    if (!resposta.ok) throw new Error();
    estado.config = await resposta.json();
  } catch {
    $("#carregando").textContent = "Não foi possível falar com o servidor. Recarregue a página.";
    return;
  }
  $("#cidade").textContent = `· coletor de corridas de ${estado.config.city}`;
  $("#carregando").hidden = true;

  if (estado.config.authMode === "firebase") await iniciarFirebase(estado.config.firebase);
  else mostrarApp("uso local (sem login)");
}

iniciar();
