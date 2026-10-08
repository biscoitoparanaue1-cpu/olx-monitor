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

## Rodar o scraper no seu computador (Windows)
Seu computador usa IP residencial, que a OLX quase não bloqueia. O painel continua no Streamlit
e lê o mesmo Neon.
1. Instale o Python 3.12 em https://www.python.org/downloads/ marcando **Add python.exe to PATH**.
2. Baixe o código: no GitHub, *Code → Download ZIP*, e extraia numa pasta fixa
   (ex.: `C:\olx-monitor`). Não rode de dentro do ZIP.
3. Dê dois cliques em `scripts\instalar_windows.bat`. Ele:
   - cria o ambiente e instala as bibliotecas e o navegador (Chromium);
   - abre o `.env` no Bloco de Notas para você colar a connection string do Neon;
   - agenda a tarefa **OLX Monitor** para todo dia às 07:00 (se o PC estiver desligado,
     roda assim que ligar);
   - pergunta se quer rodar um teste na hora.
4. O resultado de cada execução fica em `scraper.log`, e no painel, aba **Execuções**.
5. Para rodar fora do horário (mesmo se já rodou hoje): dois cliques em `scripts\rodar_agora.bat`.

**Atualizar o código:** baixe o ZIP de novo e copie o conteúdo por cima da pasta
(o Windows pergunta se quer substituir: *Substituir*). O `.env` e o `.venv` não estão no ZIP
e continuam como estão. Depois, `scripts\rodar_agora.bat` para aplicar as correções na hora.

Mac/Linux: `scripts/rodar_scraper.sh` no `cron` (veja o comentário no arquivo) e `.env` igual.

O GitHub Actions pode continuar ligado como reserva: as duas rotas gravam no mesmo banco e cada
uma pula o que a outra já concluiu no dia.

## Proxy residencial (opcional, pago)
Para rodar 100% na nuvem sem bloqueio, contrate um proxy residencial e crie o secret
`OLX_PROXY` no GitHub (`http://usuario:senha@host:porta`). O scraper usa automaticamente.
