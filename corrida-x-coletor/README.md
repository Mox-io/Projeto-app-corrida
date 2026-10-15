# Corrida X — coletor de corridas de rua

Ferramenta da **fase 1 do projeto piloto Corrida X** (planilha-piloto): pesquisa corridas de rua por região de São Paulo e monta o calendário das próximas semanas, com fonte e link oficial de cada prova. Usa a mesma arquitetura do **Prospector** (mesma chave da AIsa, mesmo login Firebase, mesmo jeito de publicar na Vercel) e existe nas mesmas duas formas: **linha de comando** e **app web**.

O agente faz, sozinho, este fluxo:

1. **Gera as consultas** de cada região escolhida: uma por mês da janela ("corrida de rua zona sul São Paulo novembro 2026") e uma por local conhecido ("corrida Parque Ibirapuera 2026 inscrições").
2. **Pesquisa** no Google (busca orgânica do DataForSEO, via AIsa).
3. **Lê os resultados com IA** e extrai as provas: nome, data, horário, local, distâncias, organizador, preço/lote, porte e link de inscrição.
4. **Confere tudo no código**: a data precisa ser válida, a fonte precisa ser um dos resultados da busca e o link de inscrição só vale se for uma das URLs encontradas. O LLM não consegue inventar link.
5. **Classifica a região no código** (não no LLM), com a tabela de locais do projeto piloto (Obelisco do Ibirapuera, Parque da Independência, Campo de Marte...) e uma lista de bairros.
6. **Junta repetidas** (a mesma prova em duas páginas vira uma só, com os campos das duas) e faz a **triagem**.
7. Gera a **planilha-piloto** (`calendario.csv`) e o **calendário em JSON** (`calendario.json`), no formato que o site da fase 2 pode ler.

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

> O programa foi testado com respostas simuladas (42 testes automáticos) e com o modo demonstração. **Ainda não rodou com uma chave real.** Na primeira vez, use `--listar-consultas` (sem custo) e depois uma única consulta (`--limite-consultas 1`) para conferir se o formato das respostas bate com o esperado.

## Testar sem chave e sem custo (modo demonstração)

O modo demonstração usa as 25 provas da "Amostra de calendário de São Paulo" do projeto piloto (cronograma da Prefeitura de 08/10/2026) e alguns casos inventados para mostrar a triagem (um pedal, uma prova em Campinas, uma que já passou, um local desconhecido). As páginas e links são **fictícios** (`agenda.example`, `inscricoes.example`) e a data de "hoje" é fixa em 15/10/2026.

```powershell
cd C:projetospp-corridarrida-x-coletor
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
| Outras regiões | repita `-r`: `-r sul -r oeste` (aceita `zona sul`, `sul`, `centro`...) |
| Um termo meu | `-q "corrida noturna São Paulo novembro"` (soma aos da região) |
| Só os meus termos | `-q "..." --so-consultas` |
| Mais semanas | `--semanas 12` |
| Gastar menos | `--limite-consultas 3` ou `--profundidade 10` |
| Sem IA | `--sem-llm` (regras simples; tudo vai para "a conferir") |

Resultados em `output\<data-hora>\calendario.csv` (separado por `;`, abre direto no Excel) e `calendario.json`.

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
  demo_data.py          amostra do projeto piloto para o modo demonstração
  cli.py                orquestra tudo
tests/                  testes do núcleo e do app web
```

## Próximos passos sugeridos

- Rodar a fase 1 por 2 semanas e medir o que o piloto pede: provas catalogadas, % com link oficial e tempo de conferência por prova.
- Acrescentar à tabela de `regioes.py` os locais que aparecerem como "a confirmar".
- Na fase 2, o site do corredor lê o `calendario.json` (só as provas conferidas).
