// Testes do firestore.rules no emulador do Firestore. Como rodar: veja o README do app (seção "Testar as regras").
import { test, before, after } from "node:test";
import { readFileSync } from "node:fs";
import { initializeTestEnvironment, assertSucceeds, assertFails } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, updateDoc, getDocs, collection, query, where, arrayUnion } from "firebase/firestore";

const REGRAS = new URL("../firestore.rules", import.meta.url);
let env;
const agora = () => new Date().toISOString();
const db = (uid, extra = {}) => env.authenticatedContext(uid, extra).firestore();

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-ritmex",
    firestore: { rules: readFileSync(REGRAS, "utf8") }, // host e porta vêm do emulators:exec (FIRESTORE_EMULATOR_HOST)
  });
  await env.withSecurityRulesDisabled(async (ctx) => {
    const f = ctx.firestore();
    await setDoc(doc(f, "provas/p1"), { nome: "Prova 1", data: "2026-10-04", kmMax: 10 });
    await setDoc(doc(f, "provas/pfut"), { nome: "Futura", data: "2099-01-01", kmMax: 10 });
    await setDoc(doc(f, "provas/pold"), { nome: "Antiga", data: "2026-09-20" });
    for (const p of ["p1", "pfut", "pold"]) await setDoc(doc(f, `confirmacoes/${p}_alice`), { provaId: p, uid: "alice", nome: "Alice", data: "2026-10-04", em: agora() });
    await setDoc(doc(f, "config/admins"), { emails: ["admin@x.com"] });
    await setDoc(doc(f, "grupos/ABC123"), { nome: "Turma", codigo: "ABC123", dono: "bob", membros: ["bob"], criadoEm: agora() });
  });
});
after(async () => { await env?.cleanup(); });

const conclusao = (extra = {}) => ({ provaId: "p1", provaNome: "Prova 1", data: "2026-10-04", distanciaKm: 10, tempoSeg: 2850, uid: "alice", nome: "Alice", em: agora(), ...extra });
const concluir = (uid, provaId, extra) => setDoc(doc(db(uid), `conclusoes/${provaId}_${uid}`), conclusao({ provaId, uid, ...extra }));

test("conclusão válida passa", () => assertSucceeds(concluir("alice", "p1")));
test("conclusão sem tempo passa", () => assertSucceeds(concluir("alice", "p1", { tempoSeg: null })));
test("distância até kmMax + 1 passa", () => assertSucceeds(concluir("alice", "p1", { distanciaKm: 10.9, tempoSeg: 3000 })));
test("distância acima de kmMax + 1 falha", () => assertFails(concluir("alice", "p1", { distanciaKm: 11.5, tempoSeg: 3000 })));
test("250 km numa prova de 10 km falha", () => assertFails(concluir("alice", "p1", { distanciaKm: 250, tempoSeg: null })));
test("nome da prova inventado falha", () => assertFails(concluir("alice", "p1", { provaNome: "Spam no feed" })));
test("data diferente da prova falha", () => assertFails(concluir("alice", "p1", { data: "2026-10-05" })));
test("sem confirmação falha", () => assertFails(concluir("bob", "p1", { nome: "Bob" })));
test("prova inexistente falha", () => assertFails(concluir("alice", "nao-existe", { provaNome: "X" })));
test("prova futura falha", () => assertFails(concluir("alice", "pfut", { provaNome: "Futura", data: "2099-01-01" })));
test("ritmo abaixo de 2:00/km falha", () => assertFails(concluir("alice", "p1", { tempoSeg: 600 })));
test("prova sem kmMax aceita até 250 km", () => assertSucceeds(concluir("alice", "pold", { provaNome: "Antiga", data: "2026-09-20", distanciaKm: 100, tempoSeg: 36000 })));
test("em em formato errado falha", () => assertFails(concluir("alice", "p1", { em: 123 })));

const treino = (extra) => ({ uid: "alice", nome: "Alice", data: "2026-10-01", km: 10, minutos: 25, descricao: "", origem: "manual", em: agora(), ...extra });
test("treino 10 km em 25 min passa", () => assertSucceeds(setDoc(doc(db("alice"), "treinos/t1"), treino())));
test("treino sem tempo passa", () => assertSucceeds(setDoc(doc(db("alice"), "treinos/t2"), treino({ minutos: null }))));
test("treino 42 km em 10 min falha", () => assertFails(setDoc(doc(db("alice"), "treinos/t3"), treino({ km: 42, minutos: 10 }))));
test("treino com em numérico falha", () => assertFails(setDoc(doc(db("alice"), "treinos/t4"), treino({ em: 5 }))));

test("confirmação com em válido passa", () => assertSucceeds(setDoc(doc(db("bob"), "confirmacoes/p1_bob"), { provaId: "p1", uid: "bob", nome: "Bob", data: "2026-10-04", em: agora() })));
test("confirmação com em numérico falha", () => assertFails(setDoc(doc(db("carol"), "confirmacoes/p1_carol"), { provaId: "p1", uid: "carol", nome: "Carol", data: "2026-10-04", em: 1 })));
test("seguir com em válido passa", () => assertSucceeds(setDoc(doc(db("alice"), "follows/alice_bob"), { seguidor: "alice", alvo: "bob", em: agora() })));
test("seguir com em futuro em texto livre falha", () => assertFails(setDoc(doc(db("alice"), "follows/alice_carol"), { seguidor: "alice", alvo: "carol", em: "amanhã" })));

test("corredor não lê config/admins", () => assertFails(getDoc(doc(db("alice", { email: "alice@x.com", email_verified: true }), "config/admins"))));
test("admin lê config/admins", () => assertSucceeds(getDoc(doc(db("adm", { email: "admin@x.com", email_verified: true }), "config/admins"))));

const grupo = (uid, codigo) => ({ nome: "Meu grupo", codigo, dono: uid, membros: [uid], criadoEm: agora() });
test("criar grupo com id = código passa", () => assertSucceeds(setDoc(doc(db("carol"), "grupos/XYZ789"), grupo("carol", "XYZ789"))));
test("criar grupo com id diferente do código falha", () => assertFails(setDoc(doc(db("carol"), "grupos/aleatorio1"), grupo("carol", "QWE456"))));
test("quem sabe o código lê o grupo", () => assertSucceeds(getDoc(doc(db("dave"), "grupos/ABC123"))));
test("listar todos os grupos falha", () => assertFails(getDocs(collection(db("dave"), "grupos"))));
test("buscar grupo pelo código (list) falha", () => assertFails(getDocs(query(collection(db("dave"), "grupos"), where("codigo", "==", "ABC123")))));
test("listar os próprios grupos passa", () => assertSucceeds(getDocs(query(collection(db("bob"), "grupos"), where("membros", "array-contains", "bob")))));
test("entrar no grupo com o código passa", () => assertSucceeds(updateDoc(doc(db("dave"), "grupos/ABC123"), { membros: arrayUnion("dave") })));
test("pôr outra pessoa no grupo falha", () => assertFails(updateDoc(doc(db("erin"), "grupos/ABC123"), { membros: arrayUnion("frank") })));
// Controle do teste "sem confirmação falha": depois de confirmar (teste acima), Bob consegue concluir.
test("depois de confirmar, Bob conclui", () => assertSucceeds(concluir("bob", "p1", { nome: "Bob" })));
