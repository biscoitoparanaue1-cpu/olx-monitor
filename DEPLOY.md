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
- **Bloqueio da OLX:** a OLX (Cloudflare) bloqueia por IP parte dos servidores do GitHub.
  Nos testes de 07/10/2026 a busca passou em 2 de 3 execuções, mas a página de cada anúncio
  (de onde vem a descrição) foi bloqueada. Por isso o GitHub tenta 3 vezes por dia
  (07h, 10h e 13h) e cada tentativa completa só o que faltou.

## Rodar o scraper na sua máquina (recomendado para ter as descrições)
Seu computador usa IP residencial, que a OLX quase não bloqueia. O painel continua no Streamlit
e lê o mesmo Neon.
1. Instale o Python 3.12 (python.org, marque *Add to PATH*) e, na pasta do projeto:
   ```bat
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt playwright playwright-stealth
   .venv\Scripts\python -m playwright install chromium
   ```
2. Copie `.env.example` para `.env` e cole a connection string do Neon em `DATABASE_URL`.
3. Teste: dê dois cliques em `scripts\rodar_scraper.bat` e veja o `scraper.log`.
4. Agende: *Agendador de Tarefas → Criar Tarefa Básica → Diariamente, 07:00 →
   Iniciar um programa → `scripts\rodar_scraper.bat`*. Marque "Executar o mais cedo possível
   se um início agendado for perdido" para rodar quando o PC ligar.
   No Mac/Linux use `scripts/rodar_scraper.sh` no `cron`.

Pode deixar o GitHub Actions ligado junto: as duas rotas gravam no mesmo banco e cada uma pula
o que a outra já fez no dia.

## Proxy residencial (opcional, pago)
Para rodar 100% na nuvem sem bloqueio, contrate um proxy residencial e crie o secret
`OLX_PROXY` no GitHub (`http://usuario:senha@host:porta`). O scraper usa automaticamente.
