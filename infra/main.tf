terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    azapi   = { source = "azure/azapi", version = "~> 1.13" }
  }
}

provider "azurerm" {
  features {}
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
}

resource "azurerm_servicebus_namespace" "sb" {
  name                = "${var.prefix}-sb"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "Standard"
}

resource "azurerm_servicebus_queue" "q" {
  name         = "pdf-processing-queue"
  namespace_id = azurerm_servicebus_namespace.sb.id
  max_delivery_count = 5 # Dead-letter après 5 échecs (ex: PDF corrompu)
}

# --- 2. Event Grid (La colle entre Blob et Queue) ---
resource "azurerm_eventgrid_system_topic" "blob_topic" {
  name                   = "${var.prefix}-blob-events"
  location               = var.location
  resource_group_name    = azurerm_resource_group.rg.name
  source_arm_resource_id = azurerm_storage_account.st.id
  topic_type             = "Microsoft.Storage.StorageAccounts"
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
  delivery_identity {
    type = "SystemAssigned"
  }
}

# --- 3. Intelligence (AI Foundry) ---
resource "azapi_resource" "ai_foundry" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  name                      = "${var.prefix}-aifoundry"
  parent_id                 = azurerm_resource_group.rg.id
  location                  = var.location
  schema_validation_enabled = false
  body = jsonencode({
    kind = "AIServices"
    sku = { name = "S0" }
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
    sku = { name = "S0" }
    identity = { type = "SystemAssigned" }
    properties = {
      displayName = "Email Classification Project"
      description = "Email intents classification"
    }
  })
}

# Deployments (MaaS models)
resource "azapi_resource" "deployment_phi4" {
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
  role_definition_name = "Storage Blob Data Reader"
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

resource "azurerm_role_assignment" "aca_cosmos_contrib" {
  scope                = azurerm_cosmosdb_account.db.id
  role_definition_name = "Cosmos DB Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app_id.principal_id
}

resource "azurerm_role_assignment" "eventgrid_to_sb" {
  scope                = azurerm_servicebus_namespace.sb.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_eventgrid_system_topic_event_subscription.sub.identity[0].principal_id
}

# --- 4. Base de données (Resultats) ---
resource "azurerm_cosmosdb_account" "db" {
  name                = "${var.prefix}-cosmos"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  capabilities { name = "EnableServerless" } # Mode économique pour POC
  geo_location { location = var.location; failover_priority = 0 }
  consistency_policy { consistency_level = "Session" }
}

resource "azurerm_cosmosdb_sql_database" "sql" {
  name                = "EmailDB"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.db.name
}

resource "azurerm_cosmosdb_sql_container" "container" {
  name                  = "Classifications"
  resource_group_name   = azurerm_resource_group.rg.name
  account_name          = azurerm_cosmosdb_account.db.name
  database_name         = azurerm_cosmosdb_sql_database.sql.name
  partition_key_paths   = ["/category"]
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
output "AI_ENDPOINT" { value = jsondecode(azapi_resource.ai_foundry.output).properties.endpoint }
output "APP_ID_CLIENT_ID" { value = azurerm_user_assigned_identity.app_id.client_id }