# Instala o OLX Monitor nesta pasta e agenda o scraper para todo dia às 07:00.
# Use pelo instalar_windows.bat (dois cliques). Pode rodar de novo sem problema.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Passo($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

Passo "Verificando o Python"
$versao = $null
try { $versao = (& python --version) 2>&1 } catch { }
if (-not ($versao -match "Python 3\.(1[0-9])")) {
    Write-Host "Python 3.10+ não encontrado. Instale o Python 3.12 (marque 'Add python.exe to PATH')" -ForegroundColor Yellow
    Write-Host "e rode este instalador de novo. Abrindo a página de download..." -ForegroundColor Yellow
    Start-Process "https://www.python.org/downloads/"
    exit 1
}
Write-Host "Encontrado: $versao"

Passo "Criando o ambiente (.venv) e instalando as bibliotecas"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & python -m venv .venv }
$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt playwright playwright-stealth --quiet
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as bibliotecas" }

Passo "Baixando o navegador do Playwright (Chromium)"
& $py -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar o Chromium" }

Passo "Configurando o banco (Neon)"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
if ((Get-Content ".env" -Raw) -match "usuario:senha@ep-xxxx") {
    Write-Host "Cole a connection string do Neon na linha DATABASE_URL, salve e feche o Bloco de Notas." -ForegroundColor Yellow
    Start-Process notepad.exe -ArgumentList ".env" -Wait
}

Passo "Agendando a tarefa 'OLX Monitor' (todo dia às 07:00)"
$bat = Join-Path $root "scripts\rodar_scraper.bat"
$acao = New-ScheduledTaskAction -Execute "`"$bat`"" -WorkingDirectory $root  # aspas: caminho pode ter espaço
$gatilho = New-ScheduledTaskTrigger -Daily -At "07:00"
# StartWhenAvailable: se o PC estava desligado às 07:00, roda assim que ligar
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "OLX Monitor" -Action $acao -Trigger $gatilho -Settings $config `
    -Description "Scraper diário da OLX (olx-monitor)" -Force | Out-Null
Write-Host "Tarefa agendada." -ForegroundColor Green

$resposta = Read-Host "`nRodar o scraper agora para testar? Leva alguns minutos (s/n)"
if ($resposta -match "^[sS]") {
    & $py -m app.jobs.daily
    Write-Host "`nPronto. Abra o painel no Streamlit para ver os anúncios." -ForegroundColor Green
}
