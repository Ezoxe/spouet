<#
.SYNOPSIS
    Spouet — installer desktop Windows (téléchargement MSI).

.DESCRIPTION
    Télécharge le dernier MSI publié sur GitHub Releases et le lance en mode
    silencieux (msiexec /quiet). Aucune compilation locale.

.PARAMETER Repo
    Dépôt GitHub au format <owner>/<name>. Défaut: maximehollie41/spouet.

.PARAMETER Tag
    Tag de release à installer. Défaut: latest.

.PARAMETER Quiet
    Installation totalement silencieuse. Défaut: $true.
    Mettre $false pour voir l'UI MSI.

.EXAMPLE
    irm https://raw.githubusercontent.com/<owner>/spouet/main/desktop/install.ps1 | iex

.EXAMPLE
    .\install.ps1 -Tag v0.2.0
#>

[CmdletBinding()]
param(
    [string] $Repo  = "maximehollie41/spouet",
    [string] $Tag   = "latest",
    [bool]   $Quiet = $true
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host "[spouet-desktop] $msg" -ForegroundColor Cyan }
function Die        { param([string]$msg) Write-Host "[spouet-desktop] $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# Élévation requise (msiexec /quiet réussit mieux en admin)
# ---------------------------------------------------------------------------
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($Quiet -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Die "Lance PowerShell en Administrateur (ou passe -Quiet `$false pour une install interactive)."
}

# ---------------------------------------------------------------------------
# Résolution de l'asset MSI
# ---------------------------------------------------------------------------
$apiBase = "https://api.github.com/repos/$Repo/releases"
$apiUrl  = if ($Tag -eq "latest") { "$apiBase/latest" } else { "$apiBase/tags/$Tag" }

Write-Step "Recherche de la release ($Tag) sur $Repo..."
$headers = @{ "User-Agent" = "spouet-installer" }
try {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers $headers -UseBasicParsing
} catch {
    Die "Impossible de trouver la release '$Tag' sur $Repo : $($_.Exception.Message)"
}

$msiAsset = $release.assets | Where-Object { $_.name -like "*.msi" } | Select-Object -First 1
if (-not $msiAsset) {
    $available = ($release.assets | ForEach-Object { $_.name }) -join ", "
    Die "Aucun .msi dans la release $($release.tag_name). Assets disponibles : $available"
}

# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------
$tmpMsi = Join-Path $env:TEMP $msiAsset.name
Write-Step "Téléchargement de $($msiAsset.name) ($([math]::Round($msiAsset.size/1MB,1)) Mo)..."
Invoke-WebRequest -Uri $msiAsset.browser_download_url -OutFile $tmpMsi -UseBasicParsing -Headers $headers

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
Write-Step "Installation de $($msiAsset.name)..."
$msiArgs = @("/i", "`"$tmpMsi`"", "/norestart")
if ($Quiet) { $msiArgs += "/quiet" } else { $msiArgs += "/passive" }
$msiArgs += "/l*v", "`"$env:TEMP\spouet-install.log`""

$proc = Start-Process -FilePath "msiexec.exe" -ArgumentList $msiArgs -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Die "msiexec a retourné $($proc.ExitCode). Log : $env:TEMP\spouet-install.log"
}

Remove-Item $tmpMsi -ErrorAction SilentlyContinue
Write-Step "✓ Spouet Desktop installé. Cherche 'Spouet' dans le menu Démarrer."
