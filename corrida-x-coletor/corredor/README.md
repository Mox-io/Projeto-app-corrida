# Ritmex — app do corredor (protótipo do piloto)

É a parte que o corredor usa: o calendário com a parte social. O **coletor** (pasta de cima) pesquisa as provas e gera o `calendario.json`; este app publica esse calendário para os corredores.

Um arquivo só (`index.html`, HTML + CSS + JS), no mesmo estilo do B31: **Firebase Authentication (login com Google) + Firestore**, sem servidor próprio.

## O que tem

| Aba | O que faz |
|---|---|
| **Provas** | A raiz do app. **Sua região** em destaque (cidade e, em São Paulo, zona), filtros rápidos de **distância** e **período** (fim de semana, 30 dias, este mês) e, em Filtros, **preço**, zonas, temáticas, noturnas e "onde amigos vão". No topo, a **próxima prova** (a sua confirmada ou a mais próxima) com contagem regressiva, local, organizador, lote/valor e o botão **Inscrever-se no Site Oficial**. Depois, as provas em destaque e a lista por data, com **lote e valor** quando informados. |
| **Feed** | Comunidade: quem vai em cada prova ("Vou correr") e quem **cruzou a linha de chegada** (provas concluídas, com distância, tempo e ritmo). **Treinos não aparecem aqui.** Também: buscar e seguir corredores, corredores da sua cidade, **Grupos** (ranking por km em **provas concluídas** no ano) e **Assessorias e parceiros** da região. |
| **Meu Painel** | **Privado** (só a pessoa vê). Km de treino no ano e no mês, provas concluídas, melhor ritmo em prova, **termômetro da próxima prova** (maior treino das últimas 4 semanas x distância da prova), **painel do Strava** (quando conectado), **evolução do ritmo** por semana, **Minhas provas** (marcar "Concluí" com o tempo) e lançar treinos (à mão ou GPX). |
| **Perfil** | Dados do corredor, **zonas favoritas de treino** (São Paulo), números (provas, km em provas, seguidores) e **medalhas**: primeira prova, 5 provas, 10 km, meia, maratona e os **circuitos da região** (Track&Field, Circuito das Estações, Night Run, SP City Marathon, São Silvestre, Circuito Caixa). Também: administração (admins), sair e excluir a conta. |
| **Administração** (no Perfil, só para admins) | Publicar o `calendario.json` do coletor (com a opção de só as aprovadas), marcar **destaque**, remover prova, cadastrar parceiros e **baixar as confirmações por prova** (o número para mostrar aos organizadores). |

Ficou de fora, como combinado: inscrição e pagamento dentro do app, integração direta com o Strava (o GPX resolve por enquanto), notificações e mensagens entre usuários.

## Testar agora (modo demonstração)

Com `FIREBASE_CONFIG = null` (o padrão), o app abre em **modo demonstração**: sem login real, com corredores, grupo, treinos e parceiros fictícios, e as provas da amostra do projeto piloto. Tudo fica salvo só no navegador (botão "Recomeçar a demonstração" no perfil).

Abra o `index.html` direto no navegador, ou sirva a pasta:

```powershell
cd C:\projetos\app-corrida\corrida-x-coletor\corredor
python -m http.server 8080
```

e abra http://localhost:8080. Para ver a Administração na demo, toque no seu avatar (canto de cima) > Administração.

## Ligar no Firebase (versão real)

1. No [console do Firebase](https://console.firebase.google.com), crie um projeto (ou use um que você já tenha; pode ser o mesmo do Prospector, mas um projeto separado deixa as regras independentes).
2. **Authentication > Método de login**: ative o **Google**.
3. **Firestore Database**: crie o banco (modo produção, região `southamerica-east1`).
4. **Configurações do projeto > Seus apps > Web**: registre um app e copie o objeto de configuração para `FIREBASE_CONFIG` no topo do `index.html`. Esses dados não são segredo.
5. Publique as regras e os índices (precisa do Node e do `firebase-tools`):
   ```powershell
   npm install -g firebase-tools
   firebase login
   firebase use --add        # escolha o projeto
   firebase deploy --only firestore
   ```
6. No Firestore, crie à mão o documento **`config/admins`** com o campo `emails` (array) contendo o seu e-mail Google e o do Diego. É ele que libera a tela de Administração; ninguém consegue mudá-lo pelo app.
7. Publique o site: `firebase deploy --only hosting` (o endereço fica `seu-projeto.web.app`). Também dá para usar a Vercel, criando um projeto com a pasta raiz `corredor`. Se usar outro endereço, acrescente-o em **Authentication > Configurações > Domínios autorizados**.
8. Entre com a sua conta, vá em Perfil > Administração e envie o `calendario.json` gerado pelo coletor.

## Segurança e privacidade

- As permissões ficam no `firestore.rules`, não na página: cada pessoa só altera o próprio perfil, as próprias confirmações, os próprios treinos e quem ela segue. Só admins publicam provas e parceiros. Nos grupos, cada um só pode entrar ou sair a si mesmo.
- Tudo o que vem do banco entra na página como texto (nunca como HTML), e só links `http(s)` viram links.
- **Visibilidade:** perfis, provas confirmadas e treinos ficam visíveis para qualquer corredor logado. A tela de login avisa isso. Antes de abrir para o público geral, vale um texto de privacidade (LGPD) e, se quiserem, uma opção de perfil privado.
- Limite do piloto: até 30 pessoas por grupo, e o feed e o ranking leem no máximo 30 pessoas por consulta (limite do filtro "in" do Firestore). Para crescer além disso, o caminho é somar os km numa Cloud Function.

## O que foi testado

O modo demonstração foi testado de ponta a ponta no navegador (celular e computador): login, perfil, filtros, "Vou correr", seguir, feed, treino manual e por GPX, grupo com ranking, parceiros e administração (importar o `calendario.json`, destacar). **A versão com Firebase ainda não rodou de verdade**: não consegui acessar o Firebase daqui. Na primeira vez, teste com a sua conta. Se aparecer um erro de índice, o próprio console do navegador mostra o link para criá-lo (ou rode o `firebase deploy --only firestore`, que cria todos).
