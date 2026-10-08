@echo off
REM Gera diagnostico.txt com a estrutura das paginas da OLX (para o Claude ajustar o parser).
cd /d "%~dp0.."
set PYTHONUTF8=1
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m app.scraper.diagnose
echo.
echo Pronto: envie o arquivo diagnostico.txt no chat.
pause
