# Installation du node-agent comme service Windows via NSSM.
# Prérequis : NSSM installé (https://nssm.cc), uv installé, dépôt cloné en C:\spouet.
#
# Usage : .\install.ps1 -Backend "https://spouet.local" -Token "xxx"

param(
    [Parameter(Mandatory=$true)] [string] $Backend,
    [Parameter(Mandatory=$true)] [string] $Token,
    [string] $OllamaUrl = "http://localhost:11434",
    [int]    $Interval  = 10,
    [string] $ServiceName = "SpouetAgent",
    [string] $InstallDir  = "C:\spouet\node-agent"
)

$ErrorActionPreference = "Stop"

$exe = (Get-Command uv).Source
$args = @(
    "run", "--directory", $InstallDir, "spouet-agent", "run",
    "--backend", $Backend,
    "--ollama",  $OllamaUrl,
    "--interval", $Interval
)

nssm install   $ServiceName $exe @args
nssm set       $ServiceName AppEnvironmentExtra "SPOUET_AGENT_TOKEN=$Token"
nssm set       $ServiceName Start SERVICE_AUTO_START
nssm set       $ServiceName AppStdout "$InstallDir\agent.log"
nssm set       $ServiceName AppStderr "$InstallDir\agent.log"
nssm start     $ServiceName

Write-Host "Service $ServiceName installé et démarré."
