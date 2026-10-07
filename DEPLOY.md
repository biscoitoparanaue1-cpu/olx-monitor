# Publicar de graça (sem cartão de crédito)

## Como fica
| Peça | Onde roda | Custo |
|---|---|---|
| Painel (melhores do dia, 👍/👎, regras, termos) | **Streamlit Community Cloud** | grátis |
| Scraper diário às 07:00 (Brasília) | **GitHub Actions** (agendado) | grátis |
| Banco PostgreSQL | **Neon** | grátis (0,5 GB) |

Os três só pedem login (GitHub/Google), nenhum pede cartão.

## Passo a passo (uma vez só)
1. **Neon:** crie conta em https://neon.tech, um projeto na região **AWS São Paulo (sa-east-1)**
   e copie a *connection string* (`postgresql://...neon.tech/neondb?sslmode=require`).
2. **GitHub:** o código já está em https://github.com/biscoitoparanaue1-cpu/olx-monitor (branch `main`).
3. **Segredo do scraper:** no repositório, *Settings → Secrets and variables → Actions →
   New repository secret*: nome `DATABASE_URL`, valor = a connection string do Neon.
4. **Teste o scraper:** aba *Actions → Scraper diário → Run workflow*. Em ~5 min ele termina;
   o log mostra `[ok]`, `[blocked]` ou `[error]`. Depois disso roda sozinho todo dia às 07:00.
5. **Painel:** em https://share.streamlit.io entre com o GitHub, *Create app → Deploy a public app
   from GitHub*, escolha o repositório, branch `main`, arquivo `streamlit_app.py`.
   Em *Advanced settings*: Python 3.12 e, em **Secrets**, cole:
   ```toml
   DATABASE_URL = "postgresql://...neon.tech/neondb?sslmode=require"
   APP_PASSWORD = "uma-senha-sua"   # opcional: pede senha para abrir o painel
   ```
   O link fica no formato `https://<nome>.streamlit.app`.

## Bom saber
- **O app "dorme"** depois de alguns dias sem acesso; ao abrir, aparece um botão para acordá-lo
  (leva ~30 s). O scraper não é afetado: ele roda no GitHub, não no Streamlit.
- **GitHub pausa agendamentos** de repositórios sem nenhum commit há 60 dias; ele avisa por e-mail
  e basta clicar em reativar.
- **Bloqueio da OLX:** o GitHub Actions roda em servidores de data center, que a OLX costuma
  barrar mais. Se o log vier `[blocked]` mesmo com Playwright, rode o scraper na sua máquina
  gravando no mesmo Neon (o painel continua na nuvem):
  ```bash
  pip install -r requirements.txt playwright playwright-stealth && python -m playwright install chromium
  DATABASE_URL='postgresql://...' python -m app.jobs.daily
  ```
  e agende isso no Agendador de Tarefas do Windows (ou `cron` no Mac/Linux).
