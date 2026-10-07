# OLX Monitor — Arquitetura e Esquema do Banco (v2)

## 1. Stack adotada

| Camada | Escolha | Por quê |
|---|---|---|
| Linguagem | Python 3.12 | Ecossistema de scraping e dados |
| API | FastAPI + Uvicorn | Tipagem com Pydantic, docs automáticas em `/docs` |
| ORM | SQLAlchemy 2.0 + Alembic | Mesmo modelo serve SQLite e PostgreSQL; migrações versionadas |
| Banco | SQLite local; **Neon PostgreSQL** na nuvem | Troca só a `DATABASE_URL` |
| Scraper | `httpx` + `selectolax`/BeautifulSoup; fallback Playwright | HTTP puro é rápido; Playwright entra quando houver bloqueio |
| Hospedagem e agendamento | **Streamlit Community Cloud** (painel) + **GitHub Actions** (scraper às 07:00) | Grátis e sem cartão; ver [DEPLOY.md](DEPLOY.md) |
| NLP | Regex + normalização (sem acento, minúsculas) + `rapidfuzz` | Resolve "desliga a cada 40min" / "desligando sozinha" sem modelo pesado |
| Score / ML | Pesos por regras no início → Regressão Logística (scikit-learn) quando houver ~30 feedbacks | Aprende com pouco dado e é explicável |
| Frontend | **Streamlit** (`streamlit_app.py`) | Python puro, hospedagem grátis; lê o banco direto |

## 2. Visão geral

```
            ┌────────────── GitHub Actions (diário, 07:00) ───────────────┐
            │                                                             │
            ▼                                                             │
 ┌────────────────────┐   anúncios crus   ┌─────────────────────────┐     │
 │ 1. SCRAPER         │ ───────────────▶ │ 2. CATEGORIZAÇÃO        │     │
 │ httpx → Playwright │                   │ regex/keywords/fuzzy    │     │
 │ UA rotation, delay │                   │ estado + regras casadas │     │
 └────────────────────┘                   └───────────┬─────────────┘     │
            │ scrape_runs                             ▼                   │
            │                             ┌─────────────────────────┐     │
            │                             │ 3. AVALIAÇÃO DE PREÇO   │     │
            │                             │ mediana/z-score do grupo│     │
            │                             │ (categoria + estado)    │     │
            │                             └───────────┬─────────────┘     │
            │                                         ▼                   │
            │                             ┌─────────────────────────┐     │
            │                             │ 5. SCORE (modelo ativo) │◀────┘ retreino
            │                             │ features × pesos        │       após feedback
            ▼                             └───────────┬─────────────┘
   ┌───────────────────────── Banco (SQLAlchemy) ─────┴──────────────┐
   └───────────────────────────────▲─────────────────────────────────┘
                                   │
                         ┌─────────┴──────────────┐   ┌──────────────────┐
                         │ 4. PAINEL (Streamlit)  │   │ API FastAPI      │
                         │ cards + 👍 / 👎 (Neon) │   │ (opcional/local) │
                         └────────────────────────┘   └──────────────────┘
```

**Fluxo diário:** para cada `search_term` ativo → busca páginas → para cada anúncio faz *upsert* por `olx_id` (novo ou atualiza `last_seen_at`; grava em `price_history` se o preço mudou) → aplica regras e define `condition` → calcula `price_evaluation` → calcula `listing_score` → anúncios que não apareceram mais são marcados `is_active = 0`.

## 3. Estrutura de pastas

```
olx-monitor/
├── app/
│   ├── main.py              # FastAPI (API opcional)
│   ├── config.py            # DATABASE_URL, horário do job, termos default
│   ├── db.py                # engine/session
│   ├── models.py            # SQLAlchemy (espelha schema.sql)
│   ├── schemas.py           # Pydantic (entrada/saída da API)
│   ├── api/                 # listings.py, feedback.py, rules.py, searches.py
│   ├── scraper/
│   │   ├── fetcher.py       # httpx com headers/UA/delay; fallback Playwright
│   │   └── parser.py        # extrai do JSON embutido (__NEXT_DATA__) ou HTML
│   ├── nlp/categorizer.py   # normalização + aplicação das filter_rules
│   ├── pricing/evaluator.py # estatística do grupo e rótulo
│   ├── scoring/             # features.py, model.py, trainer.py
│   └── jobs/daily.py        # orquestra o pipeline
├── streamlit_app.py         # painel
├── .github/workflows/       # scraper diário
└── tests/
```

## 4. Decisões de cada módulo

### 4.1 Scraper
- Tenta primeiro `httpx` com headers de navegador real; a página de busca da OLX costuma trazer os dados num JSON embutido (`__NEXT_DATA__`), mais estável que seletores CSS.
- Delay aleatório de 3–8 s entre páginas, limite de páginas por termo, retry com *backoff*.
- Se receber 403/captcha, marca o `scrape_run` como `blocked` e repete com Playwright (headless, perfil persistente). Rotação de User-Agent e stealth entram nesta camada se precisar.
- Descrição completa às vezes só existe na página do anúncio: visita o detalhe **apenas de anúncios novos**, para reduzir requisições.

### 4.2 Categorização (estado do item)
Valores de `condition`: `novo`, `usado_bom`, `usado_com_avaria`, `defeito`, `para_pecas`.
- Texto normalizado (minúsculas, sem acento, `40 min` = `40min`).
- `filter_rules` são cadastradas pelo dashboard. Exemplo:
  - *Desliga sozinha*: `deslig\w*\s+(sozinh\w*|a cada \d+\s*min)` → `sets_condition = defeito`, `action = include`
  - *Tela trincada*: `tela\s+(trincad\w*|quebrad\w*|rachad\w*)` → `defeito`
  - *Excluir lojas de conserto*: `assistencia tecnica|conserto` → `action = exclude`
- `action`: `include` (só mostra se casar), `exclude` (esconde), `tag` (só marca e influencia o score).
- Cada casamento fica em `listing_rule_matches` com o trecho, para destacar no card.

### 4.3 Avaliação de preço
- Grupo de comparação = **marca + linha/modelo + tamanho** (ex.: "LG OLED C1 55", extraído do título/descrição por `app/scraper/attributes.py`) + mesma `condition`, anúncios dos últimos 90 dias. Se o grupo tiver menos de 5 anúncios, sobe um nível: só marca + tamanho ("LG OLED 55"), depois só tamanho. O nível usado fica em `price_evaluations.group_level`, usando o **primeiro preço** observado de cada anúncio (evita contar o mesmo anúncio várias vezes).
- Usa **mediana** e desvio robusto (MAD), menos sensíveis a preços absurdos (R$ 1, R$ 99.999).
- Rótulo: `otimo_negocio` se preço ≤ 80% da mediana; `caro` se ≥ 115%; senão `preco_justo`. Com menos de 5 anúncios no grupo: `sem_base`. Os limiares ficam em configuração.

### 4.4 Score e aprendizado (implementado em `app/scoring/`)
Características por anúncio (`features.py`): preço vs. mediana do grupo, rótulo de preço, estado do item, regras que casaram (`regra:<id>`), palavras e pares de palavras da descrição (`palavra:...`, já sem trechos negados), tamanho, linha, UF, vendedor profissional, faixa de preço e dias no ar.

`score = sigmoid(Σ peso × característica)`, de 0 a 1.
- **Sem feedback (versão 0):** pesos iniciais alinhados ao objetivo: barato em relação ao grupo (+3 × % abaixo da mediana), "Ótimo negócio" +1, "Caro" −1, **com defeito +1**, para peças +0,5, novo −0,5, e o peso que você der a cada regra.
- **Com feedback (a partir de 5 cliques com 👍 e 👎):** regressão logística treinada nos seus cliques, **regularizada em torno dos pesos iniciais** (L2 em `w − w_inicial`). Com poucos cliques o score muda pouco; com muitos, segue o seu gosto, inclusive palavras, UF, tamanho e vendedor.
- Retreina e reordena **a cada clique** (poucos dados: milissegundos). Guarda as últimas 10 versões em `model_versions`/`feature_weights`.
- `listing_scores.features_json` guarda as 6 maiores contribuições, que o painel mostra como "Por que: ▲ com defeito · ▲ preço vs. grupo · ▼ “perfeita”".

### 4.5 API (rotas previstas)
| Método | Rota | Uso |
|---|---|---|
| GET | `/api/listings/top?date=&limit=` | Melhores do dia (ordenado por score) |
| GET | `/api/listings?category=&condition=&label=&q=` | Busca/filtro geral |
| GET | `/api/listings/{id}` | Detalhe + histórico de preço |
| POST | `/api/feedback` | `{listing_id, value: 1 \| -1}` |
| CRUD | `/api/search-terms`, `/api/rules`, `/api/categories` | Configuração |
| POST | `/api/jobs/run` | Dispara o scraping manualmente |
| GET | `/api/stats` | Execuções, bloqueios, versão do modelo |

## 5. Esquema do banco

SQL completo e testado em [`schema.sql`](schema.sql). Resumo:

| Tabela | Papel | Campos-chave |
|---|---|---|
| `search_terms` | Termos monitorados ("TV LG OLED") | query, região, faixa de preço, ativo |
| `product_categories` | Agrupamento para comparar preço | nome, regex no título |
| `scrape_runs` | Log de cada execução | status (ok/blocked/error), modo, contagens |
| `sellers` | Vendedor | olx_seller_id, profissional |
| `listings` | Anúncio (1 linha por `olx_id`) | título, descrição, url, preço atual, `posted_at`, `condition`, ativo, `raw_json` |
| `price_history` | Histórico de preço por anúncio | price, observed_at |
| `filter_rules` | Filtros da descrição configuráveis | pattern, tipo, action, sets_condition, weight |
| `listing_rule_matches` | Regras que casaram em cada anúncio | trecho casado |
| `price_evaluations` | Comparação com o grupo | mediana, amostra, z-score, rótulo |
| `listing_scores` | Score atual para ordenar | score, versão do modelo, features |
| `feedback` | 👍 / 👎 | value ±1 (o último clique vale) |
| `model_versions` / `feature_weights` | Pesos aprendidos versionados | algoritmo, métricas, peso por feature |

Relações principais: `search_terms 1─N listings`, `listings N─1 sellers`, `listings 1─N price_history`, `listings N─N filter_rules` (via `listing_rule_matches`), `listings 1─1 feedback`, `listings 1─1 listing_scores`, `model_versions 1─N feature_weights`.

## 6. Decisões tomadas (07/10/2026)
1. **Objetivo:** *achar* TVs com defeito (para conserto/revenda). As regras de defeito somam no score inicial.
2. **Região:** Brasil todo (`/brasil` na URL da OLX).
3. **Comparação de preço:** separada por tamanho e modelo, com fallback para níveis mais amplos quando faltar amostra.
4. **Hospedagem:** Streamlit Community Cloud + GitHub Actions, banco no Neon (troca do Firebase para não precisar de cartão).
5. Em aberto: notificação (Telegram/e-mail) quando surgir um "Ótimo negócio".
