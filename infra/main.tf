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

  # Tags obligatoires G2S pour toutes les ressources déployées
  common_tags = {
    "cp-code-sa"       = "devin"
    "cp-deploiement"   = "terraform"
    "cp-environnement" = "d"
    "cp-proprietaire"  = "g2s-dtpo-iaf"
    "cp-responsable"   = "g2s-dtpo-iaf"
    "cp-supervision"   = "oui"
  }
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

variable "deploy_language_service" {
  type        = bool
  description = "Deploy Azure AI Language service for native PII detection (optional). Uses Standard SKU (S tier). Free tier (F0) can be used manually if preferred."
  default     = false
}

variable "organization_name" {
  type        = string
  description = "Organization/destination name displayed in the UI (e.g., G2S, Groupama, ClassyMail)"
  default     = "ClassyMail"
}

variable "location" { default = "swedencentral" } # Région recommandée pour disponibilité Mistral/Phi
variable "prefix" { default = "email-poc" }

resource "azurerm_resource_group" "rg" {
  name     = "${var.prefix}-rg"
  location = var.location

  tags = local.common_tags
}

# --- 1. Stockage & Ingestion ---
resource "azurerm_storage_account" "st" {
  name                     = replace("${var.prefix}st", "-", "")
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  tags = local.common_tags

  # Avoid unintended drift vs existing secured deployments.
  # NOTE: If you need Container Apps to access Storage over the public internet,
  # set this to true and ensure your org policies allow it.
  public_network_access_enabled = true

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

  tags = local.common_tags

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

  tags = local.common_tags
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

  tags = local.common_tags
  body = jsonencode({
    kind     = "AIServices"
    sku      = { name = "S0" }
    identity = { type = "SystemAssigned" }
    properties = {
      publicNetworkAccess    = "Enabled"
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

  tags = local.common_tags
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

# --- Optional: Azure AI Language Service for PII Detection ---
# Provides native PII detection API as alternative to LLM-based detection
# Enable via: deploy_language_service = true
resource "azurerm_cognitive_account" "language" {
  count               = var.deploy_language_service ? 1 : 0
  name                = "${var.prefix}-language"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "TextAnalytics"
  sku_name            = "S" # Standard tier for production (F0 free tier available but with limits)

  tags = local.common_tags

  public_network_access_enabled = true
  local_auth_enabled            = false # Force Managed Identity (RBAC-only)

  identity {
    type = "SystemAssigned"
  }
}

# Grant Managed Identity access to Language service (Cognitive Services Language Reader)
resource "azurerm_role_assignment" "aca_language_reader" {
  count                = var.deploy_language_service ? 1 : 0
  scope                = azurerm_cognitive_account.language[0].id
  role_definition_name = "Cognitive Services Language Reader"
  principal_id         = azurerm_user_assigned_identity.app_id.principal_id
}

# RBAC Assignments
resource "azurerm_role_assignment" "aca_storage_contrib" {
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

resource "azurerm_role_assignment" "acr_pull" {
  count                = var.acr_name != "" ? 1 : 0
  scope                = data.azurerm_container_registry.acr[0].id
  role_definition_name = "AcrPull"
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

  tags = local.common_tags

  # Enable public access but restrict via firewall/RBAC
  public_network_access_enabled = true

  # "0.0.0.0" is the magic IP to "Allow access from Azure Datacenters"
  # This serves as the firewall exception for Container Apps without VNet injection.
  # We also append any client IPs provided via variables.
  ip_range_filter = concat(["0.0.0.0"], var.allowed_ip_ranges)

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
  # IMPORTANT: db-scope is required in some tenants for metadata access (readMetadata).
  scope = "${azurerm_cosmosdb_account.db.id}/dbs/${azurerm_cosmosdb_sql_database.sql.name}"
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

  # Politique d'indexation: garder l'index sur les champs utiles aux requêtes (status, reviewed, classification.needs_review, _ts)
  # et désindexer les gros champs rarement filtrés pour réduire les RU (markdown, raw_response, logs, usage).
  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/markdown/?"
    }

    excluded_path {
      path = "/processing_log/?"
    }

    excluded_path {
      path = "/usage/?"
    }

    excluded_path {
      path = "/classification/raw_response/?"
    }
  }
}

# --- RAG Containers (Chatbot & Cache) ---

resource "azurerm_cosmosdb_sql_container" "chat_history" {
  name                = "chat_history"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.db.name
  database_name       = azurerm_cosmosdb_sql_database.sql.name
  partition_key_paths = ["/id"]
  default_ttl         = -1 # Enable TTL but no expiration by default

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

# Use AzApi for Vector Search (Preview feature support)
resource "azapi_resource" "vector_cache" {
  # Schema validation disabled: vectorIndexes / vectorEmbeddingPolicy not fully GA yet
  schema_validation_enabled = false

  type      = "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15"
  name      = "vector_cache"
  parent_id = azurerm_cosmosdb_sql_database.sql.id

  body = jsonencode({
    properties = {
      resource = {
        id = "vector_cache"
        partitionKey = {
          paths = ["/id"]
          kind  = "Hash"
        }
        vectorEmbeddingPolicy = {
          vectorEmbeddings = [
            {
              path             = "/vector"
              dataType         = "float32"
              distanceFunction = "cosine"
              dimensions       = 1536
            }
          ]
        }
        indexingPolicy = {
          indexingMode = "consistent"
          automatic    = true
          includedPaths = [
            { path = "/*" }
          ]
          excludedPaths = [
            { path = "/vector/*" },
            { path = "/_etag/?" }
          ]
          vectorIndexes = [
            { path = "/vector", type = "quantizedFlat" }
          ]
        }
        defaultTtl = -1
      }
    }
  })
}

# --- 5. Compute (Container App) ---
# (Container App Environment defined below with Log Analytics)

# Identité Managée pour l'application
resource "azurerm_user_assigned_identity" "app_id" {
  location            = var.location
  name                = "${var.prefix}-id"
  resource_group_name = azurerm_resource_group.rg.name

  tags = local.common_tags
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
output "LANGUAGE_ENDPOINT" { value = var.deploy_language_service ? azurerm_cognitive_account.language[0].endpoint : null }
output "LANGUAGE_SERVICE_NAME" { value = var.deploy_language_service ? azurerm_cognitive_account.language[0].name : null }
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
variable "container_image" {
  type        = string
  description = "Container image (registry/repo:tag) to deploy to Container Apps (API & worker)."
  default     = ""
  validation {
    condition     = var.container_image != ""
    error_message = "container_image must be set (e.g., via terraform.tfvars)."
  }
}

variable "acr_name" {
  type        = string
  description = "Optional: ACR name to grant AcrPull to the managed identity."
  default     = ""
}

variable "acr_resource_group" {
  type        = string
  description = "Optional: ACR resource group (required if acr_name is set)."
  default     = ""
}

variable "allowed_ip_ranges" {
  type        = list(string)
  description = "List of public IPs or CIDRs to allow access to Cosmos DB (e.g. your local IP)."
  default     = []
}

data "azurerm_container_registry" "acr" {
  count               = var.acr_name != "" ? 1 : 0
  name                = var.acr_name
  resource_group_name = var.acr_resource_group
}

# --- Container Apps env and apps ---
resource "azurerm_log_analytics_workspace" "log" {
  name                = "${var.prefix}-logs"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = local.common_tags
}

# Workspace-based Application Insights (recommended)
resource "azurerm_application_insights" "appi" {
  name                = "${var.prefix}-appi"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.log.id

  tags = local.common_tags
}

resource "azurerm_container_app_environment" "env" {
  name                       = "${var.prefix}-env"
  location                   = var.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.log.id

  tags = local.common_tags
}

resource "azurerm_container_app" "api" {
  name                         = "${var.prefix}-api"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"

  tags = local.common_tags

  dynamic "registry" {
    for_each = var.acr_name != "" ? [1] : []
    content {
      server   = data.azurerm_container_registry.acr[0].login_server
      identity = azurerm_user_assigned_identity.app_id.id
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app_id.id]
  }

  template {
    container {
      name   = "api"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "PORT"
        value = "8000"
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app_id.client_id
      }
      env {
        name  = "AZURE_SERVICE_BUS_FQDN"
        value = "${azurerm_servicebus_namespace.sb.name}.servicebus.windows.net"
      }
      env {
        name  = "AZURE_SERVICE_BUS_QUEUE"
        value = azurerm_servicebus_queue.q.name
      }
      env {
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = azurerm_storage_account.st.primary_blob_endpoint
      }
      env {
        name  = "AZURE_STORAGE_CONTAINER"
        value = azurerm_storage_container.pdf_inputs.name
      }
      env {
        name  = "AZURE_COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.db.endpoint
      }
      env {
        name  = "AZURE_COSMOS_DB"
        value = azurerm_cosmosdb_sql_database.sql.name
      }
      env {
        name  = "AZURE_COSMOS_CONTAINER"
        value = azurerm_cosmosdb_sql_container.container.name
      }

      # AI endpoints (Phi uses AZURE_AI_ENDPOINT fallback if PHI_ENDPOINT isn't set)
      env {
        name  = "AZURE_AI_ENDPOINT"
        value = try(jsondecode(azapi_resource.ai_foundry.output).properties.endpoint, "")
      }
      env {
        name  = "PHI_ENDPOINT"
        value = try(jsondecode(azapi_resource.ai_foundry.output).properties.endpoint, "")
      }
      env {
        name  = "PHI_DEPLOYMENT"
        value = "Phi-4"
      }
      env {
        name  = "MISTRAL_ENDPOINT"
        value = try(jsondecode(azapi_resource.ai_foundry.output).properties.endpoint, "")
      }
      env {
        name  = "MISTRAL_DEPLOYMENT"
        value = "mistral-document-ai-2505"
      }
      env {
        name  = "MISTRAL_MODE"
        value = "maas"
      }
      env {
        name  = "AZURE_AI_API_VERSION"
        value = "2024-08-01-preview"
      }
      env {
        name  = "AZURE_LANGUAGE_ENDPOINT"
        value = var.deploy_language_service ? azurerm_cognitive_account.language[0].endpoint : ""
      }

      # --- Telemetry: Application Map + Agents View ---
      # service.name  → cloud role name on Application Map
      # service.namespace → groups API + Worker under one logical app
      # AZURE_MONITOR_ENABLE_GENAI_TRACES → enables GenAI tracing
      #   (Agents View in Application Insights → "Agents (Preview)")
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "classymail-api"
      }
      env {
        name  = "OTEL_RESOURCE_ATTRIBUTES"
        value = "service.namespace=classymail"
      }
      env {
        name  = "AZURE_MONITOR_ENABLE_GENAI_TRACES"
        value = "true"
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.appi.connection_string
      }
      env {
        name  = "LOG_ANALYTICS_WORKSPACE_ID"
        value = azurerm_log_analytics_workspace.log.workspace_id
      }

      # UI Features (optional overrides)
      env {
        name  = "UI_SHOW_INFO_MODAL"
        value = "true"
      }
      env {
        name  = "UI_SHOW_DEVELOPER_TAB"
        value = "true"
      }
      env {
        name  = "ORGANIZATION_NAME"
        value = var.organization_name
      }
      env {
        name  = "MAX_UPLOAD_SIZE"
        value = "10"
      }

      liveness_probe {
        transport     = "HTTP"
        port          = 8000
        path          = "/healthz"
        initial_delay = 3
      }

      readiness_probe {
        transport     = "HTTP"
        port          = 8000
        path          = "/readyz"
        initial_delay = 3
      }

    }

    min_replicas = 1
    max_replicas = 5

    http_scale_rule {
      name                = "http"
      concurrent_requests = 100
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].container[0].image
    ]
  }
}

resource "azurerm_container_app" "worker" {
  name                         = "${var.prefix}-worker"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"

  tags = local.common_tags

  dynamic "registry" {
    for_each = var.acr_name != "" ? [1] : []
    content {
      server   = data.azurerm_container_registry.acr[0].login_server
      identity = azurerm_user_assigned_identity.app_id.id
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app_id.id]
  }

  template {
    container {
      name    = "worker"
      image   = var.container_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python"]
      args    = ["-m", "classymail.worker_main"]

      env {
        name  = "ENABLE_WORKER"
        value = "true"
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app_id.client_id
      }
      env {
        name  = "AZURE_SERVICE_BUS_FQDN"
        value = "${azurerm_servicebus_namespace.sb.name}.servicebus.windows.net"
      }
      env {
        name  = "AZURE_SERVICE_BUS_QUEUE"
        value = azurerm_servicebus_queue.q.name
      }
      env {
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = azurerm_storage_account.st.primary_blob_endpoint
      }
      env {
        name  = "AZURE_STORAGE_CONTAINER"
        value = azurerm_storage_container.pdf_inputs.name
      }
      env {
        name  = "AZURE_COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.db.endpoint
      }
      env {
        name  = "AZURE_COSMOS_DB"
        value = azurerm_cosmosdb_sql_database.sql.name
      }
      env {
        name  = "AZURE_COSMOS_CONTAINER"
        value = azurerm_cosmosdb_sql_container.container.name
      }

      env {
        name  = "AZURE_AI_ENDPOINT"
        value = try(jsondecode(azapi_resource.ai_foundry.output).properties.endpoint, "")
      }
      env {
        name  = "PHI_ENDPOINT"
        value = try(jsondecode(azapi_resource.ai_foundry.output).properties.endpoint, "")
      }
      env {
        name  = "PHI_DEPLOYMENT"
        value = "Phi-4"
      }
      env {
        name  = "MISTRAL_ENDPOINT"
        value = try(jsondecode(azapi_resource.ai_foundry.output).properties.endpoint, "")
      }
      env {
        name  = "MISTRAL_DEPLOYMENT"
        value = "mistral-document-ai-2505"
      }
      env {
        name  = "MISTRAL_MODE"
        value = "maas"
      }
      env {
        name  = "AZURE_AI_API_VERSION"
        value = "2024-08-01-preview"
      }
      env {
        name  = "AZURE_LANGUAGE_ENDPOINT"
        value = var.deploy_language_service ? azurerm_cognitive_account.language[0].endpoint : ""
      }

      # --- Telemetry: Application Map + Agents View ---
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "classymail-worker"
      }
      env {
        name  = "OTEL_RESOURCE_ATTRIBUTES"
        value = "service.namespace=classymail"
      }
      env {
        name  = "AZURE_MONITOR_ENABLE_GENAI_TRACES"
        value = "true"
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.appi.connection_string
      }
      env {
        name  = "LOG_ANALYTICS_WORKSPACE_ID"
        value = azurerm_log_analytics_workspace.log.workspace_id
      }
    }

    min_replicas = 0
    max_replicas = 10

    custom_scale_rule {
      name             = "sb-queue"
      custom_rule_type = "azure-servicebus"
      metadata = {
        queueName    = azurerm_servicebus_queue.q.name
        namespace    = azurerm_servicebus_namespace.sb.name
        messageCount = "5"
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].container[0].image
    ]
  }
}
