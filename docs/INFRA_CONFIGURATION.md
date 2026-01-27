# Infrastructure & Deployment Guide

## Mandatory Environment Variables per Service

### 1. API Service (`-api`)
Responsible for serving the REST API and Dashboard.

| Variable | Description | Example / Default |
|----------|-------------|-------------------|
| `AZURE_SERVICE_BUS_FQDN` | Service Bus Hostname | `email-poc-sbus.servicebus.windows.net` |
| `AZURE_SERVICE_BUS_QUEUE` | Queue Name | `pdf-processing-queue` |
| `AZURE_STORAGE_ACCOUNT_URL` | Blob Storage Endpoint | `https://emailpocst.blob.core.windows.net` |
| `AZURE_STORAGE_CONTAINER` | Blob Container | `pdf-inputs` |
| `AZURE_COSMOS_ENDPOINT` | Cosmos DB URI | `https://email-poc-cosmos.documents.azure.com:443/` |
| `AZURE_COSMOS_DB` | Database Name | `emailsdb` |
| `AZURE_COSMOS_CONTAINER` | Container Name | `emails` |
| `AZURE_AI_ENDPOINT` | Azure AI Foundry Endpoint | `https://email-poc-aifoundry.cognitiveservices.azure.com/` |
| `AZURE_CLIENT_ID` | Managed Identity Client ID | `3ae24af5-97c6-437f...` |
| **`ENABLE_WORKER`** | Enable background processing? | `true` (if running single container), `false` (if split) |

### 2. Worker Service (`-worker`)
Responsible for processing PDFs from the queue.

| Variable | Description | Example / Default |
|----------|-------------|-------------------|
| **`ENABLE_WORKER`** | **MANDATORY** | `true` |
| `AZURE_SERVICE_BUS_FQDN` | Service Bus Hostname | `email-poc-sbus.servicebus.windows.net` |
| `AZURE_SERVICE_BUS_QUEUE` | Queue Name | `pdf-processing-queue` |
| `AZURE_STORAGE_ACCOUNT_URL` | Blob Storage Endpoint | `https://emailpocst.blob.core.windows.net` |
| `AZURE_STORAGE_CONTAINER` | Blob Container | `pdf-inputs` |
| `AZURE_COSMOS_ENDPOINT` | Cosmos DB URI | `https://email-poc-cosmos.documents.azure.com:443/` |
| `AZURE_COSMOS_DB` | Database Name | `emailsdb` |
| `AZURE_COSMOS_CONTAINER` | Container Name | `emails` |
| `AZURE_AI_ENDPOINT` | Azure AI Foundry Endpoint | `https://email-poc-aifoundry.cognitiveservices.azure.com/` |
| `PHI_DEPLOYMENT` | Model Deployment Name | `phi-4` |
| `MISTRAL_DEPLOYMENT` | OCR Model Deployment | `mistral-ocr-2505` |
| `AZURE_CLIENT_ID` | Managed Identity Client ID | `3ae24af5-97c6-437f...` |

## Infrastructure Notes

### Service Bus Authentication
For Azure Event Grid to successfully deliver blob events to Service Bus, **Local Authentication** must be enabled on the Service Bus Namespace.
- Terraform: `local_auth_enabled = true`
- This ensures Event Grid (which may use connection strings or key-based auth) can communicate with the queue.

### Event Grid Subscription To Service Bus
The subscription `to-servicebus` listens to `Microsoft.Storage.BlobCreated` events on the Storage Account and forwards them to the Service Bus Queue `pdf-processing-queue`.
- Filter: `data.url` ends with `.pdf` or `.PDF`.
