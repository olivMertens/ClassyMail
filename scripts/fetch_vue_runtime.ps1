param(
  [string]$Version = "3.5.13",
  [string]$OutFile = "static/js/vue.global.prod.js"
)

$ErrorActionPreference = "Stop"

$uri = "https://unpkg.com/vue@$Version/dist/vue.global.prod.js"
Write-Host "Downloading Vue runtime from $uri"

$dir = Split-Path -Parent $OutFile
if ($dir -and -not (Test-Path $dir)) {
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Invoke-WebRequest -Uri $uri -OutFile $OutFile

# Minimal sanity check: stub marker should not be present
$content = Get-Content -Raw -Path $OutFile
if ($content -match "Vue stub loaded|Vue stub:") {
  throw "Downloaded file still looks like the stub. Aborting."
}

Write-Host "OK: wrote $OutFile"
