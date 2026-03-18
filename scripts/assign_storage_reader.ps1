param(
    [Parameter(Mandatory=$true)] [string]$ManagedIdentityClientId,
    [Parameter(Mandatory=$true)] [string]$StorageAccountName
)

$storageId = az storage account show --name $StorageAccountName --query id -o tsv

az role assignment create `
  --assignee $ManagedIdentityClientId `
  --role "Storage Blob Data Reader" `
  --scope $storageId
