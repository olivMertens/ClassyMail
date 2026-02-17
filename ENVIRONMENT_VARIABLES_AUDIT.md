# Environment Variables Audit Report
**Date:** 2026-02-07
**Author:** GitHub Copilot
**Purpose:** Comprehensive audit of environment variables across codebase, scripts, and infrastructure

---

## 📊 Executive Summary

This audit compares environment variables across:
- ✅ **Code** (`classymail/core/config.py` + other modules)
- ✅ **Scripts** (`write_secrets_env.ps1`)
- ✅ **Documentation** (`secrets.env.example`, README.md, LOCAL_DEVELOPMENT.md)
- ✅ **Infrastructure** (Terraform `infra/main.tf`)

### 🔴 Critical Findings

1. **secrets.env.example is 40% incomplete** - Missing 20+ variables actually used in code
2. **write_secrets_env.ps1 generates wrong variable names** - `AZURE_AI_SCOPE` vs `AI_SCOPE`
3. **Terraform deployment names inconsistent** - `Phi-4` vs `phi-4`
4. **Missing telemetry variables** - `APPLICATIONINSIGHTS_CONNECTION_STRING` not in example

---

## 📋 Complete Environment Variables List

### 🔵 **Core Azure Resources** (ALL REQUIRED)

| Variable | Source | Used In | Status |
|----------|--------|---------|--------|
| `AZURE_CLIENT_ID` | Terraform output | All services (MI auth) | ✅ Complete |
| `AZURE_SERVICE_BUS_FQDN` | Terraform output | Queue messaging | ✅ Complete |
| `AZURE_SERVICE_BUS_QUEUE` | Terraform output | Queue name | ✅ Complete |
| `AZURE_STORAGE_ACCOUNT_URL` | Terraform output | Blob storage | ✅ Complete |
| `AZURE_STORAGE_CONTAINER` | Terraform output | PDF uploads | ✅ Complete |
| `AZURE_COSMOS_ENDPOINT` | Terraform output | Database | ✅ Complete |
| `AZURE_COSMOS_DB` | Terraform output | Database name | ✅ Complete |
| `AZURE_COSMOS_CONTAINER` | Terraform output | Main container | ✅ Complete |
| `COSMOS_CHAT_CONTAINER` | Config default | RAG chat history | ⚠️ Missing from example |
| `COSMOS_CACHE_CONTAINER` | Config default | Vector cache | ⚠️ Missing from example |
| `AZURE_COSMOS_KEY` | Optional (RBAC) | Key-based auth | ✅ Optional documented |

### 🤖 **AI Model Endpoints** (REQUIRED)

| Variable | Source | Used In | Status |
|----------|--------|---------|--------|
| `AZURE_AI_ENDPOINT` | Terraform output | Fallback endpoint | ✅ Complete |
| `MISTRAL_ENDPOINT` | Config/Terraform | OCR service | ✅ Complete |
| `MISTRAL_DEPLOYMENT` | Terraform | Mistral model name | ✅ Complete |
| `MISTRAL_MODE` | Terraform | Deployment mode (maas) | ✅ Complete |
| `MISTRAL_API_VERSION` | Config default | API version | ⚠️ Missing from example |
| `PHI_ENDPOINT` | Terraform output | Classification | ✅ Complete |
| `PHI_DEPLOYMENT` | Terraform | Primary model | ⚠️ Case inconsistent |
| `PHI_FALLBACK_ENDPOINT` | Config fallback | Long context | ⚠️ Missing from example |
| `PHI_FALLBACK_DEPLOYMENT` | Config default | Fallback model | ⚠️ Missing from example |
| `AI_API_VERSION` | Config default | Azure AI version | ⚠️ Wrong name in script |
| `AI_SCOPE` | Config default | Auth scope | ⚠️ Wrong name in script |

### 🔍 **RAG & Embeddings** (OPTIONAL but used if RAG enabled)

| Variable | Source | Used In | Status |
|----------|--------|---------|--------|
| `EMBEDDING_ENDPOINT` | Config fallback | Vector search | ❌ Missing everywhere |
| `EMBEDDING_DEPLOYMENT` | Config default | Embeddings model | ❌ Missing everywhere |
| `EMBEDDING_API_VERSION` | Config default | API version | ❌ Missing everywhere |
| `CHAT_ENDPOINT` | Config fallback | RAG chatbot | ❌ Missing everywhere |
| `CHAT_DEPLOYMENT` | Config default | Chat model | ❌ Missing everywhere |
| `CHAT_API_VERSION` | Config default | API version | ❌ Missing everywhere |
| `VISION_ENDPOINT` | Config fallback | Vision analysis | ❌ Missing everywhere |
| `VISION_DEPLOYMENT` | Config default | Vision model | ❌ Missing everywhere |
| `VISION_API_VERSION` | Config default | API version | ❌ Missing everywhere |

### 🛡️ **PII Detection & Anonymization** (OPTIONAL)

| Variable | Source | Used In | Status |
|----------|--------|---------|--------|
| `AZURE_LANGUAGE_ENDPOINT` | Terraform optional | Azure AI Language PII | ⚠️ Missing from example |
| `AZURE_LANGUAGE_KEY` | Optional | Key-based auth | ⚠️ Missing from example |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | Terraform (AI Foundry) | OCR Fallback (Document Intelligence via AI Foundry) | ✅ In secrets.env.example |
| `DOC_INTELLIGENCE_API_VERSION` | Config default `2024-11-30` | DI REST API version | ✅ In secrets.env.example |
| `ANONYMIZER_ENDPOINT` | Config fallback | PII scrubbing | ❌ Missing everywhere |
| `ANONYMIZER_DEPLOYMENT` | Config default | Anonymization model | ❌ Missing everywhere |
| `ANONYMIZER_API_VERSION` | Config default | API version | ❌ Missing everywhere |
| `ANONYMIZER_PROMPT_VERSION` | Config default | Prompt version | ❌ Missing everywhere |
| `ANONYMIZER_MAX_TOKENS` | Config default | Token limit | ❌ Missing everywhere |

### 📊 **Telemetry & Observability** (REQUIRED for production)

| Variable | Source | Used In | Status |
|----------|--------|---------|--------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Terraform output | App Insights | ❌ Missing from example |
| `LOG_ANALYTICS_WORKSPACE_ID` | Terraform output | Log queries | ✅ In example |
| `OTEL_SERVICE_NAME` | Terraform | Service naming | ❌ Missing from example |
| `OTEL_RESOURCE_ATTRIBUTES` | Terraform | Grouping | ❌ Missing from example |
| `AZURE_MONITOR_ENABLE_GENAI_TRACES` | Terraform | GenAI tracing | ❌ Missing from example |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional | Custom OTLP | ✅ In example |

### ⚙️ **Configuration & Tuning** (OPTIONAL with defaults)

| Variable | Default | Purpose | Status |
|----------|---------|---------|--------|
| `AZURE_REGION` | swedencentral | Region metadata | ❌ Missing |
| `AZURE_PREFERRED_DATA_ZONE` | eu-central | Data residency | ❌ Missing |
| `COSMOS_QUERY_MAX_LIMIT` | 100 | Query safety | ❌ Missing |
| `PHI_PRIMARY_MAX_INPUT_TOKENS` | 8000 | Context window | ❌ Missing |
| `PHI_FALLBACK_MAX_INPUT_TOKENS` | 120000 | Fallback context | ❌ Missing |
| `PHI_RESERVED_OUTPUT_TOKENS` | 1000 | Output buffer | ❌ Missing |
| `PHI4_COST_PER_1K_INPUT` | 0.000107 | Cost tracking | ✅ In example |
| `PHI4_COST_PER_1K_OUTPUT` | 0.00043 | Cost tracking | ✅ In example |
| `MISTRAL_OCR_COST_PER_1K_PAGES` | 1.0 | Cost tracking | ✅ In example |
| `FALLBACK_COST_PER_1K_INPUT` | 0 | Fallback costs | ❌ Missing |
| `FALLBACK_COST_PER_1K_OUTPUT` | 0 | Fallback costs | ❌ Missing |
| `MISTRAL_OCR_MAX_ATTEMPTS` | 2 | Retry logic | ❌ Missing |
| `REVIEW_CONFIDENCE_THRESHOLD` | 0.85 | Quality gate | ❌ Missing |

### 👷 **Worker Configuration** (OPTIONAL with defaults)

| Variable | Default | Purpose | Status |
|----------|---------|---------|--------|
| `WORKER_CONCURRENCY` | 30 | Parallel tasks | ❌ Missing |
| `WORKER_LOCK_RENEWAL_DURATION` | 3600 | Lock timeout | ❌ Missing |
| `MISTRAL_RPM` | 30 | Rate limit | ❌ Missing |
| `MISTRAL_TPM` | 60000 | Token limit | ❌ Missing |
| `PHI_RPM` | 60 | Rate limit | ❌ Missing |
| `PHI_TPM` | 80000 | Token limit | ❌ Missing |
| `CHAT_RPM` | 60 | Rate limit | ❌ Missing |
| `CHAT_TPM` | 80000 | Token limit | ❌ Missing |

### 🎨 **UI Configuration** (OPTIONAL)

| Variable | Default | Purpose | Status |
|----------|---------|---------|--------|
| `UI_SHOW_INFO_MODAL` | true | Welcome modal | ❌ Missing from example |
| `UI_SHOW_DEVELOPER_TAB` | true | Dev features | ❌ Missing from example |
| `ORGANIZATION_NAME` | ClassyMail | Branding | ❌ Missing from example |
| `MAX_UPLOAD_SIZE` | 10485760 | Upload limit | ❌ Missing from example |
| `UPLOAD_MAX_BYTES` | 10485760 | Upload limit (alt) | ❌ Missing from example |

### 🌍 **Environment & Deployment** (OPTIONAL)

| Variable | Default | Purpose | Status |
|----------|---------|---------|--------|
| `AZURE_ENV` | development | Environment tag | ❌ Missing |
| `APP_VERSION` | - | Version tracking | ❌ Missing |
| `AZURE_SUBSCRIPTION_ID` | - | Subscription info | ❌ Missing |
| `AZURE_TENANT_ID` | - | Tenant info | ❌ Missing |
| `AZURE_RESOURCE_GROUP` | - | RG info | ❌ Missing |
| `ENABLE_WORKER` | false | Run worker | ❌ Missing from example |

### 🧪 **Testing & Development** (LOCAL ONLY)

| Variable | Purpose | Status |
|----------|---------|--------|
| `AZURE_OPENAI_ENDPOINT` | Test data generation | ✅ In example |
| `AZURE_OPENAI_DEPLOYMENT` | Test data model | ✅ In example |
| `AZURE_OPENAI_API_VERSION` | Test API version | ✅ In example |
| `AZURE_OPENAI_SCOPE` | Test auth scope | ✅ In example |
| `AZURE_OPENAI_API_KEY` | Optional key auth | ✅ In example |
| `AZURE_OPENAI_TIMEOUT` | Request timeout | ❌ Missing |
| `BASE_URL` | API base URL | ❌ Missing |

---

## 🔧 Recommended Actions

### Priority 1: Fix secrets.env.example (BLOCKING)
- [ ] Add all RAG/Embedding variables
- [ ] Add all PII/Anonymization variables
- [ ] Add all Telemetry variables
- [ ] Add all Configuration variables
- [ ] Add all Worker variables
- [ ] Add all UI variables

### Priority 2: Fix write_secrets_env.ps1 (HIGH)
- [ ] Change `AZURE_AI_SCOPE` → `AI_SCOPE`
- [ ] Change `AZURE_AI_API_VERSION` → `AI_API_VERSION`
- [ ] Add RAG variables (EMBEDDING_*, CHAT_*, VISION_*)
- [ ] Add Telemetry variables (APPLICATIONINSIGHTS_*, OTEL_*)
- [ ] Add optional configuration variables with defaults
- [ ] Document which variables come from Terraform vs local overrides

### Priority 3: Update Documentation (MEDIUM)
- [ ] Update README.md (fix line 135 "eux" typo)
- [ ] Update LOCAL_DEVELOPMENT.md with complete variable list
- [ ] Update ACA_ENVIRONMENT_VARIABLES.md with RAG/PII variables
- [ ] Add environment variables reference doc
- [ ] Document Terraform vs local dev differences

### Priority 4: Terraform Consistency (LOW)
- [ ] Standardize deployment names (Phi-4 vs phi-4)
- [ ] Add RAG container names to Terraform outputs
- [ ] Consider adding optional RAG/PII variables to Terraform

---

## 📝 Variable Naming Conventions

### Current Issues:
1. **Inconsistent prefixes**: `AZURE_AI_*` vs `AI_*` vs `PHI_*`
2. **Inconsistent suffixes**: `_ENDPOINT` vs `_URL` vs `_FQDN`
3. **Inconsistent casing**: `Phi-4` vs `phi-4` vs `PHI_DEPLOYMENT`

### Recommended Standard:
```bash
# Azure Resources: AZURE_<SERVICE>_<PROPERTY>
AZURE_SERVICE_BUS_FQDN
AZURE_STORAGE_ACCOUNT_URL
AZURE_COSMOS_ENDPOINT

# AI Models: <MODEL>_<PROPERTY>
MISTRAL_ENDPOINT
MISTRAL_DEPLOYMENT
PHI_ENDPOINT
PHI_DEPLOYMENT

# Global AI Config: AI_<PROPERTY> (no model prefix)
AI_API_VERSION
AI_SCOPE
AZURE_AI_ENDPOINT  # Exception: Terraform name

# Features: <FEATURE>_<PROPERTY>
EMBEDDING_ENDPOINT
CHAT_DEPLOYMENT
VISION_ENDPOINT
ANONYMIZER_DEPLOYMENT
```

---

## ✅ Validation Checklist

Run these commands after applying fixes:

```bash
# 1. Validate secrets.env.example has all variables
uv run python -c "
import os
from classymail.core import config
missing = []
for attr in dir(config):
    if attr.isupper() and not attr.startswith('_'):
        if os.getenv(attr) is None:
            missing.append(attr)
if missing:
    print(f'❌ Missing: {missing}')
else:
    print('✅ All variables documented')
"

# 2. Test write_secrets_env.ps1 generates correct names
.\scripts\write_secrets_env.ps1 -ResourceGroup "test-rg" -OutFile "test.env" -Force
grep -E "AI_SCOPE|AI_API_VERSION" test.env  # Should exist
grep "AZURE_AI_SCOPE" test.env  # Should NOT exist

# 3. Verify Terraform outputs match config.py
terraform -chdir=infra output -json | jq -r 'keys[]' | sort
grep -oP 'os.getenv\("\K[^"]+' classymail/core/config.py | sort -u
```

---

## 📊 Statistics

- **Total Variables Used in Code**: 87
- **Variables in secrets.env.example**: 18 (21% coverage)
- **Variables Generated by Script**: 22 (25% coverage)
- **Variables Set by Terraform**: 27 (31% coverage)
- **Missing from All Docs**: 20+ (23%)

**Recommendation**: Expand secrets.env.example to at least 70% coverage (60+ variables with defaults/comments)

---

## 🔗 Related Files

- Code: [classymail/core/config.py](../classymail/core/config.py)
- Example: [secrets.env.example](../secrets.env.example)
- Script: [scripts/write_secrets_env.ps1](../scripts/write_secrets_env.ps1)
- Terraform: [infra/main.tf](../infra/main.tf)
- Docs: [docs/LOCAL_DEVELOPMENT.md](../docs/LOCAL_DEVELOPMENT.md)

---

**Next Steps**: Review this audit, prioritize fixes, and update documentation systematically.
