@echo off
REM Dois cliques: roda o scraper agora, mesmo que ele já tenha rodado hoje.
cd /d "%~dp0.."
set PYTHONUTF8=1
if not exist .venv\Scripts\python.exe (
  echo Esta pasta ainda nao foi instalada: falta o ambiente .venv.
  echo Rode scripts\instalar_windows.bat nesta pasta, ou copie estes arquivos para a pasta
  echo onde voce ja instalou o OLX Monitor ^(a que tem .env e .venv^) e rode este arquivo de la.
  pause
  exit /b 1
)
if not exist .env (
  echo Falta o arquivo .env com a DATABASE_URL do Neon nesta pasta.
  echo Copie o .env da pasta onde voce instalou antes, ou rode scripts\instalar_windows.bat.
  pause
  exit /b 1
)
echo Rodando o scraper. Pode levar uns 20 minutos; deixe esta janela aberta...
.venv\Scripts\python.exe -m app.jobs.daily
echo.
echo Pronto. Abra o painel no Streamlit.
pause
