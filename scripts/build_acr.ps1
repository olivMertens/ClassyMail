param(
  [string]$AcrName,
  [string]$Registry,
  [string]$ImageName = "classimail-agent",
  [string]$Tag = "local",
  [ValidateSet('acr','docker')][string]$PushMethod = "acr"
)

if (-not $AcrName -and -not $Registry) {
  Write-Error "AcrName or Registry must be provided"
  exit 1
}
if (-not $Registry) { $Registry = "$AcrName.azurecr.io" }
$Image = "$Registry/$ImageName:$Tag"

if ($PushMethod -eq 'acr') {
  Write-Host "[build] Remote build via az acr build -> $Image"
  az acr build --registry $AcrName --image "$ImageName:$Tag" .
} elseif ($PushMethod -eq 'docker') {
  Write-Host "[build] Local docker build & push -> $Image"
  az acr login -n $AcrName | Out-Null
  docker build -t $Image .
  docker push $Image
} else {
  Write-Error "Unknown PushMethod=$PushMethod"
  exit 1
}

Write-Host "[ok] Built & pushed $Image"
