<#
.SYNOPSIS
    Spouet — installer node-agent Windows (one-liner, bootstrap complet).

.DESCRIPTION
    À lancer dans une PowerShell *Administrateur*. Installe automatiquement :
      - git (winget si absent)
      - uv (https://astral.sh/uv)
      - NSSM (téléchargé et placé dans C:\spouet\bin)
      - clone du dépôt dans C:\spouet
      - service Windows "SpouetAgent" (auto-start)

.PARAMETER Backend
    URL du backend Spouet, ex: https://spouet.local

.PARAMETER Token
    Token agent (créé par 'spouet-admin create-token --email ...').

.PARAMETER LlamaPort
    Port d'écoute de llama-server. Défaut: 8080

.PARAMETER AgentPort
    Port de l'API de contrôle du node-agent. Défaut: 8765

.PARAMETER Interval
    Intervalle de heartbeat (s). Défaut: 10

.PARAMETER InstallDir
    Répertoire d'installation. Défaut: C:\spouet

.PARAMETER RepoUrl
    URL Git du dépôt Spouet.

.PARAMETER Branch
    Branche à cloner. Défaut: master

.PARAMETER ServiceName
    Nom du service Windows. Défaut: SpouetAgent

.EXAMPLE
    irm https://raw.githubusercontent.com/<owner>/spouet/master/node-agent/install.ps1 | iex

.EXAMPLE
    .\install.ps1 -Backend https://spouet.local -Token xxx
#>

[CmdletBinding()]
param(
    [string] $Backend,
    [string] $Token,
    [int]    $LlamaPort   = 8080,
    [int]    $AgentPort   = 8765,
    [int]    $Interval    = 10,
    [string] $InstallDir  = "C:\spouet",
    [string] $RepoUrl     = "https://github.com/ezoxe/spouet.git",
    [string] $Branch      = "master",
    [string] $ServiceName = "SpouetAgent",
    [switch] $Images,
    [int]    $ImagePort   = 8083,
    [string] $ImageModel  = ""
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host "[spouet-agent] $msg" -ForegroundColor Cyan }
function Write-Warn { param([string]$msg) Write-Host "[spouet-agent] $msg" -ForegroundColor Yellow }
function Die        { param([string]$msg) Write-Host "[spouet-agent] $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# Élévation requise
# ---------------------------------------------------------------------------
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Die "Ouvre PowerShell en Administrateur et relance le script."
}

# ---------------------------------------------------------------------------
# Prompts si paramètres absents
# ---------------------------------------------------------------------------
if (-not $Backend) { $Backend = Read-Host "URL du backend Spouet (ex: https://spouet.local)" }
if (-not $Token)   { $Token   = Read-Host "Token agent (créé par spouet-admin create-token)" }

if (-not $Backend) { Die "Backend requis." }
if (-not $Token)   { Die "Token requis." }

# ---------------------------------------------------------------------------
# Helpers — recharge PATH après installation d'un outil
# ---------------------------------------------------------------------------
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Resolve-Tool {
    param([string]$name)
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# ---------------------------------------------------------------------------
# 1. git
# ---------------------------------------------------------------------------
if (-not (Resolve-Tool git)) {
    Write-Step "Installation de git via winget..."
    if (-not (Resolve-Tool winget)) {
        Die "git absent et winget indisponible. Installe Git for Windows manuellement (https://git-scm.com)."
    }
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
}
Write-Step "git OK : $(git --version)"

# ---------------------------------------------------------------------------
# 2. uv
# ---------------------------------------------------------------------------
if (-not (Resolve-Tool uv)) {
    Write-Step "Installation de uv (astral.sh)..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-Path
}
$UvPath = Resolve-Tool uv
if (-not $UvPath) { Die "uv introuvable après installation." }
Write-Step "uv OK : $UvPath"

# ---------------------------------------------------------------------------
# 3. Clone / pull
# ---------------------------------------------------------------------------
$AgentDir = Join-Path $InstallDir "node-agent"
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Step "Dépôt existant — git pull..."
    git -C $InstallDir fetch --quiet origin $Branch
    git -C $InstallDir checkout --quiet $Branch
    git -C $InstallDir pull --quiet --ff-only
} else {
    Write-Step "Clone $RepoUrl -> $InstallDir..."
    if (Test-Path $InstallDir) {
        Die "$InstallDir existe mais n'est pas un dépôt git. Supprime-le ou choisis -InstallDir différent."
    }
    git clone --quiet --branch $Branch $RepoUrl $InstallDir
}

Write-Step "uv sync (node-agent)..."
if ($Images) {
    Write-Step "  -> extra [images] (torch/diffusers) : installation (peut etre longue)..."
    & $UvPath sync --extra images --directory $AgentDir
} else {
    & $UvPath sync --directory $AgentDir
}

# ---------------------------------------------------------------------------
# 4. NSSM (download si absent)
# ---------------------------------------------------------------------------
$BinDir   = Join-Path $InstallDir "bin"
$NssmExe  = Join-Path $BinDir "nssm.exe"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

if (-not (Test-Path $NssmExe)) {
    Write-Step "Téléchargement de NSSM 2.24..."
    $NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
    $TmpZip  = Join-Path $env:TEMP "nssm.zip"
    $TmpDir  = Join-Path $env:TEMP "nssm-extract"
    Invoke-WebRequest -Uri $NssmUrl -OutFile $TmpZip -UseBasicParsing
    if (Test-Path $TmpDir) { Remove-Item $TmpDir -Recurse -Force }
    Expand-Archive -Path $TmpZip -DestinationPath $TmpDir
    $arch = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
    $found = Get-ChildItem -Path $TmpDir -Recurse -Filter "nssm.exe" |
             Where-Object { $_.FullName -match "\\$arch\\" } | Select-Object -First 1
    if (-not $found) { Die "nssm.exe introuvable dans le zip téléchargé." }
    Copy-Item $found.FullName $NssmExe
    Remove-Item $TmpZip -Force
    Remove-Item $TmpDir -Recurse -Force
}
Write-Step "NSSM OK : $NssmExe"

# ---------------------------------------------------------------------------
# 5. Service Windows
# ---------------------------------------------------------------------------
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Step "Service $ServiceName existant — réinstallation propre..."
    & $NssmExe stop   $ServiceName  | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
}

Write-Step "Création du service $ServiceName..."
$ModelsDir = Join-Path $InstallDir "models"
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
# IMPORTANT : `uv run` resynchronise l'env sur les deps par defaut et RETIRE les
# extras. On relance donc le service avec `--extra images`, sinon torch/diffusers
# disparaissent au demarrage (image_enabled=false dans le heartbeat).
$svcArgs = @("run")
if ($Images) { $svcArgs += @("--extra", "images") }
$svcArgs += @(
    "--directory", $AgentDir, "spouet-agent", "run",
    "--backend",     $Backend,
    "--interval",    "$Interval",
    "--llama-port",  "$LlamaPort",
    "--agent-port",  "$AgentPort",
    "--install-dir", $InstallDir,
    "--models-dir",  $ModelsDir
)
if ($Images) {
    $svcArgs += @("--image-port", "$ImagePort")
    if ($ImageModel) { $svcArgs += @("--image-model", $ImageModel) }
    Write-Step "Generation d'images activee (port $ImagePort)."
} else {
    $svcArgs += "--no-images"
}
& $NssmExe install $ServiceName $UvPath @svcArgs | Out-Null
# Token + HF_HOME passent par l'environnement du service. NSSM accepte plusieurs
# variables : on les pose toutes en un seul appel séparées par espaces (format
# attendu par AppEnvironmentExtra côté NSSM CLI).
& $NssmExe set $ServiceName AppEnvironmentExtra `
    "SPOUET_AGENT_TOKEN=$Token" `
    "HF_HOME=$InstallDir\.cache\huggingface" `
    "LLAMA_MODELS_DIR=$ModelsDir" | Out-Null
& $NssmExe set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $NssmExe set $ServiceName AppStdout (Join-Path $AgentDir "agent.log") | Out-Null
& $NssmExe set $ServiceName AppStderr (Join-Path $AgentDir "agent.log") | Out-Null
& $NssmExe set $ServiceName AppRotateFiles 1 | Out-Null
& $NssmExe set $ServiceName AppRotateBytes 5242880 | Out-Null
& $NssmExe start $ServiceName | Out-Null

Start-Sleep -Seconds 2
$status = (Get-Service $ServiceName).Status
Write-Step "Service $ServiceName : $status"
Write-Step "✓ Installation terminée."
Write-Host ""
Write-Host "  Logs    : Get-Content '$AgentDir\agent.log' -Tail 50 -Wait"
Write-Host "  Stop    : nssm stop $ServiceName"
Write-Host "  Remove  : nssm remove $ServiceName confirm"
