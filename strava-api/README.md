# Ritmex — servidor da conexão com o Strava

Funções da Vercel que fazem **só** o que exige o *Client Secret* do Strava (que nunca pode ficar na página):

| Rota | Faz |
|---|---|
| `POST /api/token` `{ code }` | troca o código do login do Strava pelas chaves de acesso |
| `POST /api/refresh` `{ refresh_token }` | renova a chave de acesso (ela vence a cada 6 horas) |
| `POST /api/desconectar` `{ access_token }` | revoga o acesso do Ritmex na conta Strava da pessoa |

O servidor **não guarda nada**. A página do Ritmex lê as atividades direto do Strava, na hora, e mostra **só para o atleta que conectou** (regra do acordo de API do Strava); as chaves ficam em `strava/{uid}` no Firestore, que só a própria pessoa lê. Só a origem do Ritmex pode chamar as rotas (CORS).

## Publicar na Vercel

1. Na Vercel: **Add New › Project** › importe o repositório `app-corrida`.
2. **Root Directory**: `strava-api`. Framework: *Other*. Não precisa de comando de build.
3. **Environment Variables**:
   - `STRAVA_CLIENT_SECRET` = o *Client Secret* do app no Strava (marque como **Sensitive**)
   - `STRAVA_CLIENT_ID` = `288160` (opcional; já é o padrão)
   - `ORIGENS_PERMITIDAS` = `https://corrida-x.web.app,http://localhost:8080` (opcional; já é o padrão)
4. **Deploy**. O endereço fica algo como `https://ritmex-strava.vercel.app`.
5. Coloque esse endereço em `STRAVA_API` no topo do `corredor/index.html` e publique o site (`firebase deploy --only hosting`).

No Strava (*strava.com/settings/api*), o **Domínio de callback** deve ser `corrida-x.web.app` (`localhost` é sempre aceito para testes).

## Testes

```powershell
cd C:\projetos\app-corrida\strava-api
npm test
```

## Limites do Strava (out/2026)

- A API exige que a conta que criou o app seja **assinante** do Strava.
- App novo: **1 atleta**; até **10** sem revisão; acima disso, pedir revisão ao Strava.
- Exigências de marca: botão "Conectar com Strava" e menção "Powered by Strava" onde os dados aparecem; antes de pedir a revisão, trocar o botão e o selo pelos arquivos oficiais das diretrizes de marca do Strava.
