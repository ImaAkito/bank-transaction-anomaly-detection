<#
.SYNOPSIS
    Запуск системы выявления аномальных транзакций в Docker (Windows, PowerShell).

.DESCRIPTION
    Проверяет, что Docker Desktop установлен и запущен (при необходимости запускает его),
    собирает и запускает все сервисы, ждёт готовности и открывает интерфейс в браузере.
    Если что-то пошло не так, называет вероятную причину и показывает журналы сервисов.

.EXAMPLE
    .\start.ps1            # обычный запуск (после git pull тоже подходит)
    .\start.ps1 -Reset     # удалить все данные и модель и начать с чистого состояния
    .\start.ps1 -NoBuild   # запустить без пересборки образов (быстрее, не нужен интернет)
    .\start.ps1 -Stop      # остановить систему (данные сохраняются)
#>
param(
    [switch]$Reset,
    [switch]$NoBuild,
    [switch]$Stop
)

$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Fail([string]$Text) { Write-Host "ОШИБКА: $Text" -ForegroundColor Red }
function Write-Hint([string]$Text) { Write-Host "  $Text" -ForegroundColor Yellow }

function Get-EnvValue([string]$Name, [string]$Default) {
    if (Test-Path ".env") {
        foreach ($line in Get-Content ".env") {
            if ($line -match "^\s*$Name\s*=\s*(.+?)\s*$") { return $Matches[1] }
        }
    }
    return $Default
}

function Test-DockerEngine {
    docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Docker([string[]]$Arguments) {
    # Вывод печатается построчно и одновременно сохраняется для разбора ошибки.
    $script:DockerOutput = @()
    & docker @Arguments 2>&1 | ForEach-Object {
        $line = "$_"
        $script:DockerOutput += $line
        Write-Host $line
    }
    return $LASTEXITCODE
}

function Show-Diagnostics {
    Write-Step "Состояние сервисов"
    docker compose ps -a
    Write-Step "Последние строки журналов api и trainer"
    docker compose logs --tail 40 api trainer
}

$isWindowsHost = ($env:OS -eq 'Windows_NT')
$frontendPort = Get-EnvValue 'FRONTEND_PORT' '8080'
$apiPort = Get-EnvValue 'API_PORT' '8000'
$adminUser = Get-EnvValue 'ADMIN_USERNAME' 'admin'
$adminPassword = Get-EnvValue 'ADMIN_PASSWORD' 'admin'

# 1. Docker установлен?
Write-Step "Проверка Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Fail "команда docker не найдена — Docker Desktop не установлен."
    Write-Hint "Установите Docker Desktop: https://www.docker.com/products/docker-desktop/ (при установке выберите WSL 2)."
    exit 1
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "не найден Docker Compose v2 (команда 'docker compose'). Обновите Docker Desktop."
    exit 1
}

# 2. Движок Docker запущен? Если нет — запускаем Docker Desktop и ждём.
if (-not (Test-DockerEngine)) {
    $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if ($isWindowsHost -and (Test-Path $desktop)) {
        Write-Host "Docker Desktop не запущен — запускаю его, это может занять до 3 минут..."
        Start-Process -FilePath $desktop | Out-Null
    } else {
        Write-Host "Движок Docker не отвечает — запустите Docker Desktop вручную. Жду до 3 минут..."
    }
    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Test-DockerEngine)) {
        if ((Get-Date) -gt $deadline) {
            Write-Fail "движок Docker так и не запустился."
            Write-Hint "1. Откройте Docker Desktop и дождитесь надписи 'Engine running'."
            Write-Hint "2. Проверьте WSL: выполните 'wsl --status' и 'wsl --update' (WSL ставится командой 'wsl --install' от администратора)."
            Write-Hint "3. Если Docker пишет про виртуализацию — включите Intel VT-x / AMD SVM в BIOS."
            Write-Hint "4. В меню значка Docker в трее должен быть пункт 'Switch to Windows containers' (значит, режим Linux уже включён)."
            exit 1
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 3
    }
    Write-Host ""
}
Write-Host "Docker работает." -ForegroundColor Green

# 3. Остановка / сброс.
if ($Stop) {
    Write-Step "Остановка системы (данные сохраняются)"
    docker compose down --remove-orphans
    exit $LASTEXITCODE
}
if ($Reset) {
    Write-Step "Сброс: удаляю контейнеры, базу данных, модель и состояние симулятора"
    docker compose down -v --remove-orphans
}

# 4. Сборка и запуск.
$composeArgs = @('compose', 'up', '-d', '--remove-orphans')
if (-not $NoBuild) { $composeArgs += '--build' }
Write-Step ("Запуск: docker " + ($composeArgs -join ' ') + " (первый запуск — 5–15 минут)")
$code = Invoke-Docker $composeArgs
if ($code -ne 0) {
    $text = $script:DockerOutput -join "`n"
    Write-Host ""
    Write-Fail "docker compose завершился с кодом $code."
    if ($text -match 'port is already allocated|address already in use|Only one usage of each socket address|ports are not available') {
        Write-Hint "Порт $frontendPort или $apiPort уже занят другой программой."
        Write-Hint "Создайте файл .env (скопируйте .env.example) и задайте свободные порты, например FRONTEND_PORT=8081 и API_PORT=8001."
    } elseif ($text -match 'Too Many Requests|toomanyrequests|429') {
        Write-Hint "Docker Hub временно ограничил скачивание образов. Подождите 15–30 минут или выполните 'docker login' и повторите."
    } elseif ($text -match 'no space left on device') {
        Write-Hint "Закончилось место для Docker. Освободите его: 'docker system prune' (удалит неиспользуемые образы и кэш)."
    } elseif ($text -match 'TLS handshake timeout|dial tcp|i/o timeout|Could not resolve|Temporary failure in name resolution|failed to resolve source metadata|pypi.org|registry.npmjs.org') {
        Write-Hint "Проблема с интернетом при скачивании образов или пакетов. Проверьте подключение (VPN, прокси, антивирус) и повторите."
        Write-Hint "Если образы уже собирались раньше, можно запустить без сборки: .\start.ps1 -NoBuild"
    } elseif ($text -match 'already exists') {
        Write-Hint "Конфликт при сохранении образа. Выполните 'docker builder prune -f' и запустите скрипт ещё раз."
    } elseif ($text -match 'unhealthy|dependency failed|exited \(1\)|didn.t complete successfully') {
        Write-Hint "Один из сервисов не запустился. Журналы ниже; часто помогает чистый старт: .\start.ps1 -Reset"
    }
    Show-Diagnostics
    exit 1
}

# 5. Ожидание готовности интерфейса и API.
Write-Step "Ожидание готовности системы"
$url = "http://localhost:$frontendPort"
$deadline = (Get-Date).AddMinutes(5)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 3
}
Write-Host ""
if (-not $ready) {
    Write-Fail "система не ответила за 5 минут по адресу $url."
    Write-Hint "Если в журнале api есть ошибки модели или базы данных — выполните чистый старт: .\start.ps1 -Reset"
    Show-Diagnostics
    exit 1
}

Write-Host ""
Write-Host "Система запущена." -ForegroundColor Green
Write-Host "  Интерфейс:        $url  (вход: $adminUser / $adminPassword)"
Write-Host "  API и Swagger:    http://localhost:$apiPort/docs"
Write-Host "  Остановить:       .\start.ps1 -Stop"
Write-Host "  Начать с нуля:    .\start.ps1 -Reset"
Write-Host "Операции от симулятора появятся в интерфейсе в течение минуты."
if ($isWindowsHost) { Start-Process $url | Out-Null }
exit 0
