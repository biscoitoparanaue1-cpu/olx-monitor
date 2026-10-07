# OLX Monitor

Monitora a OLX todo dia, avalia o preço de TVs (foco: com defeito) e aprende com seu 👍/👎.
Arquitetura e banco: [arquitetura.md](arquitetura.md) · Publicar de graça: [DEPLOY.md](DEPLOY.md)

## Rodar na sua máquina
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install playwright playwright-stealth && python -m playwright install chromium   # p/ o scraper

python -m app.scraper.cli "TV LG OLED" --pages 2   # buscar agora
streamlit run streamlit_app.py                      # painel em http://localhost:8501
uvicorn app.main:app --reload                       # API opcional em http://localhost:8000/docs
python -m pytest -q                                 # testes
```
Sem `DATABASE_URL`, tudo usa o SQLite `olx_monitor.db`. Para usar o Neon:
`export DATABASE_URL='postgresql://...neon.tech/neondb?sslmode=require'`.

## Estrutura
| Caminho | O que faz |
|---|---|
| `streamlit_app.py` | Painel: melhores do dia, 👍/👎, todos os anúncios, regras, termos, aprendizado, execuções |
| `app/jobs/daily.py` | Job diário (GitHub Actions): roda todos os termos ativos |
| `app/scraper/` | Download (httpx → Playwright), parser do JSON da OLX, extração de modelo/tamanho, gravação |
| `app/nlp/categorizer.py` | Estado do item (defeito, para peças...) com negação e regras do usuário (regex, palavras-chave, aproximado) |
| `app/pricing/evaluator.py` | Mediana do grupo (modelo+tamanho → marca+tamanho → tamanho) e rótulo de preço |
| `app/scoring/` | Características, score e aprendizado com 👍/👎 |
| `app/pipeline.py` | Após cada captura: estado → preço → score |
| `app/services.py` | Regras compartilhadas: ranking do dia, feedback (retreina a cada clique) |
| `app/api/` + `app/main.py` | API REST (FastAPI): anúncios, feedback, regras, termos, ingestão, estatísticas |
| `app/models.py` | Tabelas (fonte da verdade do [schema.sql](schema.sql)) |
| `.github/workflows/scraper.yml` | Agendamento diário às 07:00 |

## Rotas da API
| Método | Rota | Uso |
|---|---|---|
| GET | `/api/listings/top?days=1&limit=20` | Melhores do dia (score, sem os 👎, respeitando regras include/exclude) |
| GET | `/api/listings?q=&screen_size=&price_label=&order=` | Busca e filtros |
| GET | `/api/listings/{id}` | Detalhe com histórico de preço |
| POST | `/api/listings/ingest` | Recebe anúncios de um scraper externo |
| POST / DELETE | `/api/feedback` · `/api/feedback/{id}` | 👍 (1) / 👎 (-1) e desfazer |
| CRUD | `/api/rules`, `/api/search-terms` | Configuração |
| GET | `/api/categories`, `/api/stats`, `/api/health` | Consulta |
| POST | `/api/jobs/run` | Dispara o scraping |
| GET / POST | `/api/model` · `/api/model/retrain` · `/api/listings/reprocess` | O que o modelo aprendeu, retreino e reprocessamento |

Se a variável `API_KEY` estiver definida, as rotas de escrita exigem o header `X-API-Key`.
