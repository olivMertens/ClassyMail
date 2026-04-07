param(
  [string]$AcrName,
  [string]$Registry,
  [string]$ImageName = "classymail",
  [string]$Tag,
  [ValidateSet('acr','docker')][string]$PushMethod = "acr"
)

if (-not $AcrName -and -not $Registry) {
  Write-Error "AcrName or Registry must be provided"
  exit 1
}
if (-not $Registry) { $Registry = "$AcrName.azurecr.io" }

# Auto-detect tag from git short SHA if not provided
if (-not $Tag) {
  $Tag = git rev-parse --short HEAD 2>$null
  if (-not $Tag) { $Tag = "local" }
}

$Image = "$Registry/$ImageName`:$Tag"
$ImageLatest = "$Registry/$ImageName`:latest"

Write-Host ""
Write-Host "[build] ClassyMail ACR Build" -ForegroundColor Cyan
Write-Host "  Image:  $Image"
Write-Host "  Method: $PushMethod"
Write-Host ""

if ($PushMethod -eq 'acr') {
  # ACR cloud build — send minimal context directly from repo
  # .dockerignore excludes node_modules, .venv, tests, docs, infra, data
  Write-Host "[build] Remote build via ACR Tasks..."
  az acr build `
    --registry $AcrName `
    --image "$ImageName`:$Tag" `
    --image "$ImageName`:latest" `
    --platform linux/amd64 `
    --build-arg "COMMIT_SHA=$Tag" `
    .

  if ($LASTEXITCODE -ne 0) {
    Write-Error "[build] ACR build failed"
    exit 1
  }
} elseif ($PushMethod -eq 'docker') {
  Write-Host "[build] Local docker build & push..."
  az acr login -n $AcrName | Out-Null
  docker build -t $Image -t $ImageLatest --build-arg "COMMIT_SHA=$Tag" .
  docker push $Image
  docker push $ImageLatest
}

Write-Host ""
Write-Host "[ok] Built & pushed $Image" -ForegroundColor Green
Write-Host "[ok] Also tagged as $ImageLatest" -ForegroundColor Green
