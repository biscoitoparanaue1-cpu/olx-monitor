@echo off
REM Dois cliques: roda o scraper agora, mesmo que ele já tenha rodado hoje.
cd /d "%~dp0.."
set PYTHONUTF8=1
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
echo Rodando o scraper. Pode levar uns 20 minutos; deixe esta janela aberta...
%PY% -m app.jobs.daily
echo.
echo Pronto. Abra o painel no Streamlit.
pause
