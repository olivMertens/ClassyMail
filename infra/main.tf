terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    azapi   = { source = "azure/azapi", version = "~> 1.13" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

locals {
  # If not provided, rely on the active Azure CLI subscription.
  subscription_id = try(trimspace(var.subscription_id), "")
}

provider "azurerm" {
  features {}
  subscription_id     = local.subscription_id != "" ? local.subscription_id : null
  use_cli             = true
  storage_use_azuread = true
}

variable "subscription_id" {
  type        = string
  description = "Azure subscription ID (GUID). Optional: if omitted, Terraform uses the currently selected Azure CLI subscription (az account set)."
  default     = null
  nullable    = true
}

variable "enable_model_deployments" {
  type        = bool
  description = "Créer les déploiements de modèles (phi-4 / mistral-ocr) via Terraform. Désactivé par défaut car la disponibilité dépend fortement de la région, du tenant et des offres activées."
  default     = false
}

variable "cosmos_use_rbac" {
  type        = bool
  description = "Utiliser Entra ID / RBAC pour l'accès data-plane Cosmos (désactive l'auth locale). Recommandé (et souvent requis) dans les tenants avec policy qui désactive l'auth locale."
  default     = true
}

variable "location" { default = "swedencentral" } # Région recommandée pour disponibilité Mistral/Phi
variable "prefix" { default = "email-poc" }

resource "azurerm_resource_group" "rg" {
  name     = "${var.prefix}-rg"
  location = var.location
}

# --- 1. Stockage & Ingestion ---
resource "azurerm_storage_account" "st" {
  name                     = replace("${var.prefix}st", "-", "")
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  # Beaucoup d'environnements (policies) interdisent l'accès via clés (Shared Key).
  # On force un mode compatible: OAuth/Entra-only, pas de Shared Key.
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true

  allow_nested_items_to_be_public = false
  local_user_enabled              = false
}

resource "azurerm_storage_container" "pdf_inputs" {
  name                  = "pdf-inputs"
  storage_account_id    = azurerm_storage_account.st.id
  container_access_type = "private"
}

resource "azurerm_servicebus_namespace" "sb" {
  # Contrainte Azure: un namespace Service Bus ne peut pas se terminer par "-sb".
  name                = "${var.prefix}-sbus"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "Standard"

  # Beaucoup d'environnements (policies) désactivent l'auth locale (SAS keys).
  # Le provider peut lire une valeur différente de la valeur par défaut, ce qui crée du drift.
  local_auth_enabled = false
}

resource "azurerm_servicebus_queue" "q" {
  name               = "pdf-processing-queue"
  namespace_id       = azurerm_servicebus_namespace.sb.id
  max_delivery_count = 5 # Dead-letter après 5 échecs (ex: PDF corrompu)
}

# --- 2. Event Grid (La colle entre Blob et Queue) ---
resource "azurerm_eventgrid_system_topic" "blob_topic" {
  name                = "${var.prefix}-blob-events"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  source_resource_id  = azurerm_storage_account.st.id
  topic_type          = "Microsoft.Storage.StorageAccounts"
}

resource "azurerm_eventgrid_system_topic_event_subscription" "sub" {
  name                = "to-servicebus"
  system_topic        = azurerm_eventgrid_system_topic.blob_topic.name
  resource_group_name = azurerm_resource_group.rg.name

  # Le type de destination est Service Bus Queue
  service_bus_queue_endpoint_id = azurerm_servicebus_queue.q.id

  included_event_types = ["Microsoft.Storage.BlobCreated"]
  advanced_filter {
    string_ends_with {
      key    = "data.url"
      values = [".pdf", ".PDF"]
    }
  }
}

# --- 3. Intelligence (AI Foundry) ---
resource "azapi_resource" "ai_foundry" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  name                      = "${var.prefix}-aifoundry"
  parent_id                 = azurerm_resource_group.rg.id
  location                  = var.location
  schema_validation_enabled = false
  response_export_values    = ["properties.endpoint"]
  body = jsonencode({
    kind     = "AIServices"
    sku      = { name = "S0" }
    identity = { type = "SystemAssigned" }
    properties = {
      disableLocalAuth       = true
      allowProjectManagement = true
      customSubDomainName    = "${var.prefix}-aifoundry"
    }
  })
}

# Note: Le déploiement des modèles (Mistral/Phi) se fait souvent manuellement 
# ou via azapi_resource car les offres Marketplace changent vite.
# Ici, nous créons le Hub pour accueillir les modèles.

resource "azapi_resource" "ai_project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name                      = "${var.prefix}-project"
  parent_id                 = azapi_resource.ai_foundry.id
  location                  = var.location
  schema_validation_enabled = false
  body = jsonencode({
    sku      = { name = "S0" }
    identity = { type = "SystemAssigned" }
    properties = {
      displayName = "Email Classification Project"
      description = "Email intents classification"
    }
  })
}

# Deployments (MaaS models)
resource "azapi_resource" "deployment_phi4" {
  count     = var.enable_model_deployments ? 1 : 0
  type      = "Microsoft.CognitiveServices/accounts/deployments@2023-05-01"
  name      = "phi-4"
  parent_id = azapi_resource.ai_foundry.id
  body = jsonencode({
    sku = { name = "GlobalStandard", capacity = 1 }
    properties = {
      model = { format = "OpenAI", name = "phi-4", version = "2024-10-01" }
    }
  })
}

resource "azapi_resource" "deployment_mistral_ocr" {
  count     = var.enable_model_deployments ? 1 : 0
  type      = "Microsoft.CognitiveServices/accounts/deployments@2023-05-01"
  name      = "mistral-ocr-2505"
  parent_id = azapi_resource.ai_foundry.id
  body = jsonencode({
    sku = { name = "GlobalStandard", capacity = 1 }
    properties = {
      model = { format = "Mistral", name = "mistral-ocr-2505", version = "25.05" }
    }
  })
}

# RBAC Assignments
resource "azurerm_role_assignment" "aca_storage_reader" {
  scope                = azurerm_storage_account.st.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app_id.principal_id
}

resource "azurerm_role_assignment" "aca_sb_receiver" {
  scope                = azurerm_servicebus_namespace.sb.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_user_assigned_identity.app_id.principal_id
}

resource "azurerm_role_assignment" "aca_sb_sender" {
  scope                = azurerm_servicebus_namespace.sb.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.app_id.principal_id
}

resource "random_uuid" "cosmos_sql_contrib_assignment" {}



# --- 4. Base de données (Resultats) ---
resource "azurerm_cosmosdb_account" "db" {
  name                = "${var.prefix}-cosmos"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # Beaucoup de tenants désactivent l'auth locale (clé) par policy.
  # On aligne le comportement Terraform avec ce mode; vous pouvez forcer cosmos_use_rbac=false uniquement si vous avez le droit d'activer l'auth locale.
  local_authentication_disabled = var.cosmos_use_rbac
  capabilities { name = "EnableServerless" } # Mode économique pour POC
  geo_location {
    location          = var.location
    failover_priority = 0
  }
  consistency_policy { consistency_level = "Session" }
}

# Cosmos SQL data-plane RBAC (built-in Data Contributor)
resource "azurerm_cosmosdb_sql_role_assignment" "aca_cosmos_sql_contrib" {
  count               = var.cosmos_use_rbac ? 1 : 0
  name                = random_uuid.cosmos_sql_contrib_assignment.result
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.db.name
  principal_id        = azurerm_user_assigned_identity.app_id.principal_id
  role_definition_id  = "${azurerm_cosmosdb_account.db.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  # Format attendu par l'API dans ce tenant: un préfixe ARM (subscriptions/.../databaseAccounts/...) + segments data-plane (dbs/.../colls/...).
  scope = "${azurerm_cosmosdb_account.db.id}/dbs/${azurerm_cosmosdb_sql_database.sql.name}/colls/${azurerm_cosmosdb_sql_container.container.name}"
}

resource "azurerm_cosmosdb_sql_database" "sql" {
  # Aligner avec les valeurs par défaut de l'app (main.py)
  name                = "emailsdb"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.db.name
}

resource "azurerm_cosmosdb_sql_container" "container" {
  # Aligner avec les valeurs par défaut de l'app (main.py)
  name                = "emails"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.db.name
  database_name       = azurerm_cosmosdb_sql_database.sql.name
  partition_key_paths = ["/id"]
}

# --- 5. Compute (Container App) ---
resource "azurerm_container_app_environment" "env" {
  name                = "${var.prefix}-env"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
}

# Identité Managée pour l'application
resource "azurerm_user_assigned_identity" "app_id" {
  location            = var.location
  name                = "${var.prefix}-id"
  resource_group_name = azurerm_resource_group.rg.name
}

# RBAC: Cognitive Services User for app identity
resource "azurerm_role_assignment" "rbac_ai" {
  scope                = azapi_resource.ai_foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.app_id.principal_id
}

# Output pour la config de l'app
output "SERVICEBUS_NAMESPACE" { value = azurerm_servicebus_namespace.sb.name }
output "AI_ENDPOINT" { value = try(jsondecode(azapi_resource.ai_foundry.output).properties.endpoint, null) }
output "APP_ID_CLIENT_ID" { value = azurerm_user_assigned_identity.app_id.client_id }

output "AZURE_SERVICE_BUS_FQDN" { value = "${azurerm_servicebus_namespace.sb.name}.servicebus.windows.net" }
output "AZURE_SERVICE_BUS_QUEUE" { value = azurerm_servicebus_queue.q.name }

output "AZURE_STORAGE_ACCOUNT_NAME" { value = azurerm_storage_account.st.name }
output "AZURE_STORAGE_ACCOUNT_URL" { value = azurerm_storage_account.st.primary_blob_endpoint }
output "AZURE_STORAGE_CONTAINER" { value = azurerm_storage_container.pdf_inputs.name }

output "AZURE_COSMOS_ENDPOINT" { value = azurerm_cosmosdb_account.db.endpoint }
output "AZURE_COSMOS_DB" { value = azurerm_cosmosdb_sql_database.sql.name }
output "AZURE_COSMOS_CONTAINER" { value = azurerm_cosmosdb_sql_container.container.name }

output "AZURE_COSMOS_KEY" {
  value     = var.cosmos_use_rbac ? null : azurerm_cosmosdb_account.db.primary_key
  sensitive = true
}