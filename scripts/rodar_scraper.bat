@echo off
REM Roda o scraper (o Agendador de Tarefas chama este arquivo todo dia).
REM A DATABASE_URL do Neon fica no arquivo .env na pasta do projeto.
cd /d "%~dp0.."
set PYTHONUTF8=1
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m app.jobs.daily --skip-if-done-today >> scraper.log 2>&1
