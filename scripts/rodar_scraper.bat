@echo off
REM Roda o scraper na sua maquina (IP residencial, a OLX bloqueia menos).
REM Agende no "Agendador de Tarefas" do Windows para todo dia (veja DEPLOY.md).
REM A DATABASE_URL do Neon fica no arquivo .env na pasta do projeto.
cd /d "%~dp0.."
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m app.jobs.daily --skip-if-done-today >> scraper.log 2>&1
