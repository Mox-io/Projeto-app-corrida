# Ritmex — coletor de corridas de rua + app do corredor

Este repositório tem as duas partes do piloto:

- **Coletor** (este README): pesquisa as provas e monta o calendário, no estilo do Prospector. Uso interno.
- **App do corredor** ([`corredor/`](corredor/README.md)): o que o corredor usa. Calendário por região com temáticas e noturnas, "Vou correr" com os amigos, seguir corredores, treinos (manual ou GPX), grupos com ranking de km, parceiros por região e uma área de administração para publicar o `calendario.json` do coletor e marcar provas em destaque.


Ferramenta da **fase 1 do projeto piloto Ritmex** (planilha-piloto): pesquisa corridas de rua de uma cidade (em São Paulo, por zona) e monta o calendário das próximas semanas, com fonte e link oficial de cada prova. Usa a mesma arquitetura do **Prospector** (mesma chave da AIsa, mesmo login Firebase, mesmo jeito de publicar na Vercel) e existe nas mesmas duas formas: **linha de comando** e **app web**.

O agente faz, sozinho, este fluxo:

1. **Gera as consultas** de cada região escolhida: uma por mês da janela ("corrida de rua zona sul São Paulo novembro 2026") e uma por local conhecido ("corrida Parque Ibirapuera 2026 inscrições").
2. **Pesquisa** no Google (busca orgânica do DataForSEO, via AIsa).
3. **Lê os resultados com IA** e extrai as provas: nome, data, horário, local, distâncias, organizador, preço/lote, porte e link de inscrição.
4. **Confere tudo no código**: a data precisa ser válida, a fonte precisa ser um dos resultados da busca e o link de inscrição só vale se for uma das URLs encontradas. O LLM não consegue inventar link.
5. **Classifica a região no código** (não no LLM), com a tabela de locais do projeto piloto (Obelisco do Ibirapuera, Parque da Independência, Campo de Marte...) e uma lista de bairros.
6. **Junta repetidas** (a mesma prova em duas páginas vira uma só, com os campos das duas) e faz a **triagem**.
7. Marca as provas **temáticas** (Barbie, Disney, super-heróis, Harry Potter...) e **noturnas**, pelo nome e pelo horário (`corridax/tags.py`, lista aberta).
8. Gera a **planilha-piloto** (`calendario.csv`) e o **calendário em JSON** (`calendario.json`), que a área de administração do app do corredor publica. Cada prova sai com a cidade do calendário (`CITY_NAME`), que o app usa para mostrar as provas de cada cidade.

O programa **não publica nada**: ele só monta os arquivos. Confira cada prova no site oficial antes de divulgar.

## Triagem: aprovada, a conferir ou descartada

| Situação | Quando |
|---|---|
| **aprovada** | data dentro da janela, região conhecida e entre as escolhidas, link oficial de inscrição |
| **a conferir** | local sem região conhecida, sem link oficial, ou extraída por regras (sem IA) |
| **descartada** | sem data, já aconteceu, depois da janela, não é corrida a pé (ciclismo, triatlo...), outra cidade, outra região |

As descartadas continuam na planilha com o motivo, para dar para auditar (igual aos leads descartados do Prospector). O calendário sai ordenado com **a próxima prova primeiro**, como pede o piloto.

## O que a AIsa oferece (e o que foi testado)

- Busca: `POST /apis/v1/dataforseo/serp/google/organic/live/advanced` (listada no catálogo da AIsa). Existe também a rota de **Google Events**, mas o DataForSEO informa que ela só funciona em inglês, então não foi usada.
- LLM: `POST /v1/chat/completions`, igual ao Prospector.

> Já rodou com chave real (outubro/2026): a busca e a IA funcionam no formato esperado. Na conta de **avaliação** da AIsa só alguns modelos ficam liberados (ex.: `qwen-flash`); o `gpt-4.1-mini` exige saldo pago. Modelos que "pensam" antes de responder (ex.: `deepseek-v4.1-flash`) podem devolver resposta vazia. A busca do Google às vezes falha com o erro 40101 do provedor; é passageiro, rode de novo.

## Testar sem chave e sem custo (modo demonstração)

O modo demonstração usa as 25 provas da "Amostra de calendário de São Paulo" do projeto piloto (cronograma da Prefeitura de 08/10/2026) e alguns casos inventados para mostrar a triagem (um pedal, uma prova em Campinas, uma que já passou, um local desconhecido). As páginas e links são **fictícios** (`agenda.example`, `inscricoes.example`) e a data de "hoje" é fixa em 15/10/2026.

```powershell
cd C:\projetos\app-corrida\corrida-x-coletor
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m corridax --demo
python -m corridax --demo -r sul -r norte -r leste -r oeste -r centro
```

## Linha de comando (busca real)

1. `copy .env.example .env` e preencha `AISA_API_KEY` (pode ser a mesma do Prospector).
2. Veja as consultas que seriam feitas, sem gastar nada:
   ```powershell
   python -m corridax --listar-consultas -r "zona sul"
   ```
3. Primeira busca real, só uma consulta:
   ```powershell
   python -m corridax -r "zona sul" --limite-consultas 1
   ```
4. Coleta do piloto (zona sul, 8 semanas):
   ```powershell
   python -m corridax -r "zona sul" --semanas 8
   ```

O programa mostra o plano (consultas e custo) e pergunta `Continuar? [s/N]`; `--yes` pula a pergunta.

| Quero... | Como |
|---|---|
| Outra cidade | `--cidade Campinas` (busca a cidade toda, sem zonas) |
| Cidade com nome repetido | `--cidade Palmas --uf TO` (o programa avisa quando precisa da UF) |
| Outras zonas (São Paulo) | repita `-r`: `-r sul -r oeste` (aceita `zona sul`, `sul`, `centro`...) |
| Um termo meu | `-q "corrida noturna São Paulo novembro"` (soma aos da região) |
| Só os meus termos | `-q "..." --so-consultas` |
| Mais semanas | `--semanas 12` |
| Gastar menos | `--limite-consultas 3` ou `--profundidade 10` |
| Sem IA | `--sem-llm` (regras simples; tudo vai para "a conferir") |
| Buscar de novo no Google | `--sem-cache` (ignora a busca guardada) |

Resultados em `output\<data-hora>\calendario.csv` (separado por `;`, abre direto no Excel) e `calendario.json`.

**Outras cidades:** São Paulo é a padrão e a única dividida em zonas. Em outra cidade, as consultas são por mês ("corrida de rua Campinas novembro 2026") e uma de calendário do ano; a triagem não exige zona (aprovada = data na janela, mesma cidade e link oficial). A busca no Google usa a localização exata da cidade, tirada de `corridax/dados/locais_busca_br.json` (1.304 cidades, gerado da lista gratuita de localizações do DataForSEO). Cidade fora da lista: usa o estado (com `--uf`) ou o Brasil, e o nome da cidade na consulta mantém a busca focada. No app web do coletor, os campos **Cidade** e **UF** ficam acima das zonas.

**Buscas guardadas:** cada busca paga no Google fica em `output\buscas-guardadas\` por 24 horas, gravada antes de chamar a IA. Se a IA falhar (sem saldo, modelo indisponível, resposta fora do formato), rode o mesmo comando de novo: o plano mostra a busca como já guardada e só a IA é chamada.

## App web

A mesma coleta numa página para celular ou computador: você escolhe as regiões, vê as consultas e o custo antes, acompanha o andamento (com **Cancelar**), vê o calendário por dia e baixa CSV ou JSON. Mudou a região ou as semanas depois da busca? O calendário é refeito na hora, **sem nova busca e sem custo** (a triagem é separada da busca).

Testar no computador, sem login:

```powershell
$env:AUTH_MODE = "none"
python -m webapp
```

Abra http://127.0.0.1:8000. Sem chave da AIsa, a página entra no modo demonstração.

**Publicar na Vercel**: igual ao Prospector (veja o README dele). Resumo: importe o repositório, cadastre as variáveis `AUTH_MODE=firebase`, `FIREBASE_PROJECT_ID`, `FIREBASE_WEB_API_KEY`, `FIREBASE_APP_ID`, `ALLOWED_EMAILS`, `AISA_API_KEY` (marque como *Sensitive*) e, se quiser, `REGIONS`, `WINDOW_WEEKS`, `MAX_QUERIES`, `MAX_DEPTH`. Depois do deploy, adicione o endereço da Vercel em **Authentication > Domínios autorizados** do Firebase. Pode usar o mesmo projeto Firebase do Prospector.

**Proteções** (as mesmas do Prospector): a chave da AIsa fica só no servidor; só entra quem está em `ALLOWED_EMAILS`; cada chamada é validada no servidor (inclusive as provas que a página devolve, para ninguém injetar link `javascript:`); erros de conta na AIsa (chave inválida, sem saldo) param a coleta na hora.

## Uso responsável

- **Termos de uso**: o projeto piloto prevê coleta automática só depois de checar os termos de cada site. Este coletor não raspa sites: ele só lê o título e o trecho que o Google mostra. Mesmo assim, não copie calendários inteiros de terceiros para o site público sem autorização ou parceria.
- **Custos**: cada consulta é uma busca paga no Google e uma chamada paga ao LLM. O programa sempre mostra o plano antes de gastar.
- **Dados desatualizados**: datas mudam e provas são canceladas. A planilha registra a fonte e a data da coleta de cada prova.

## Testes automáticos

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests -t . -v
```

## Estrutura do código

```
app.py                  entrada da Vercel (expõe o FastAPI `app`)
webapp/                 app web sem estado: main.py (API), schemas.py (validação), auth.py (login),
                        settings.py (limites), static/ (página)
corridax/
  __main__.py           linha de comando (python -m corridax)
  config.py             lê e valida o .env
  aisa_client.py        HTTP na AIsa (busca no Google + LLM), erros em português
  regioes.py            regiões, locais conhecidos, bairros e consultas por região
  extracao.py           resultados -> provas: prompt, conferência do JSON, plano B por regras
  coleta.py             triagem, junção de repetidas, fluxo completo
  relatorio.py          calendario.csv e calendario.json
  tags.py               etiquetas: temática e noturna
  demo_data.py          amostra do projeto piloto para o modo demonstração
  cli.py                orquestra tudo
tests/                  testes do núcleo e do app web
corredor/               app do corredor (index.html + regras do Firestore), ver corredor/README.md
```

## Próximos passos sugeridos

- Rodar a fase 1 por 2 semanas e medir o que o piloto pede: provas catalogadas, % com link oficial e tempo de conferência por prova.
- Acrescentar à tabela de `regioes.py` os locais que aparecerem como "a confirmar".
- Publicar o `calendario.json` no app do corredor (Perfil > Administração) e acompanhar as confirmações por prova.
