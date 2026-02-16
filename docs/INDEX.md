# Documentation

> 📊 **Diagrammes Interactifs** : Ouvrez [index.html](./index.html) pour une documentation interactive avec zoom et téléchargement des diagrammes !
> Voir aussi : [README_DIAGRAMS.md](./README_DIAGRAMS.md) | [Outil d'export](./mermaid-export.html)

> 🆕 **Dernière mise à jour** : Février 2026 - Nouvelles features: Category Assessment AI, PII Detection, Per-Email Reprocessing, Dynamic Cost Tracking, GPT-5 Reasoning Models

## Navigation

### 🏗️ Core Architecture
- [ARCHITECTURE](ARCHITECTURE.md) - Architecture système, RBAC, et détails du pipeline de traitement
- [MODELS](MODELS.md) - Modèles AI requis, API parameters (standard vs reasoning models)
- [COSTS_LOGIC](COSTS_LOGIC.md) - Logique d'analyse de coûts et comparaison de modèles (12+ modèles)
- [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md) - État d'avancement des features (Feb 2026)

### 🚀 Déploiement & Infrastructure
- [DEPLOY_FROM_SCRATCH](DEPLOY_FROM_SCRATCH.md) - **Déploiement complet depuis zéro** dans un nouveau tenant Azure (guide + script bootstrap)
- [INFRASTRUCTURE](INFRASTRUCTURE.md) - Déploiement Terraform, configuration Azure, Event Grid, RBAC, **Required Models**
- [AZURE_AI_FOUNDRY_SETUP](AZURE_AI_FOUNDRY_SETUP.md) - Setup Azure AI Foundry : déploiement modèles, env vars, Container Apps
- [ACA_ENVIRONMENT_VARIABLES](ACA_ENVIRONMENT_VARIABLES.md) - Variables d'environnement requises pour les Container Apps
- [CLI_REFERENCE](CLI_REFERENCE.md) - Commandes CLI complètes : setup, authentification, identité managée, RAG

### 💻 Développement Local
- [LOCAL_DEVELOPMENT](LOCAL_DEVELOPMENT.md) - Setup, exécution locale, build Docker, testing, troubleshooting

### 🔄 CI/CD
- [CICD_GITHUB](CICD_GITHUB.md) - Pipeline CI/CD GitHub

### 🧪 Testing & Quality
- [SCENARIO_E2E](SCENARIO_E2E.md) - Scénarios end-to-end
- [TESTING_EMAIL_GENERATION](TESTING_EMAIL_GENERATION.md) - Génération d'emails de test
- [FINE_TUNING_DATA](FINE_TUNING_DATA.md) - Génération de datasets fine-tuning
- [PII_ANONYMIZATION_AND_USER_CORRECTIONS](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md) - Anonymisation PII et système de corrections utilisateur
- [COMPARISON_ADVERSARIAL](COMPARISON_ADVERSARIAL.md) - Guide comparaison adversariale Phi-4 vs GPT-4o-mini

### 📱 Interface & Features
- [USER_INTERFACE](USER_INTERFACE.md) - Guide complet interface utilisateur (PII indicators, reprocessing, AI advice)
- [INTEGRATION_CLIENT_G2S](INTEGRATION_CLIENT_G2S.md) - Preprocessing avancé, slugs, export CSV (**G2S-specific**)
- [G2S_CUSTOMIZATION](G2S_CUSTOMIZATION.md) - **Configuration G2S** : tags, catégories assurance, branding, policy Azure
- [ADR_OCR_STRATEGY](ADR_OCR_STRATEGY.md) - Architecture Decision Record: OCR Strategy
- [VISION_STRATEGY_PERFORMANCE_ANALYSIS](VISION_STRATEGY_PERFORMANCE_ANALYSIS.md) - Analyse de performance de la stratégie Vision (PDF-to-JPEG, latence)
- [RBAC_AUDIT](RBAC_AUDIT.md) - Audit et troubleshooting RBAC détaillé
- [TROUBLESHOOTING_MAP](TROUBLESHOOTING_MAP.md) - Architecture & troubleshooting map (connexions ACA/SB/Storage/Identity)

### 🆕 Nouvelles Fonctionnalités (Février 2026)
- **Category Assessment AI**: [USER_INTERFACE.md#categories-tab](USER_INTERFACE.md) - Analyse qualité catégories avec GPT-5 Nano
- **Per-Email Reprocessing**: [USER_INTERFACE.md#review--classify-tab](USER_INTERFACE.md) - Retraitement avec sélection modèle/stratégie
- **PII Detection**: [USER_INTERFACE.md#email-list-view](USER_INTERFACE.md) - Indicateurs DCP/PII dans dashboard
- **Dynamic Costs**: [COSTS_LOGIC.md](COSTS_LOGIC.md) - 12+ modèles avec pricing configurable
- **GPT-5 Support**: [MODELS.md#api-parameter-differences](MODELS.md) - Reasoning models (max_completion_tokens, no temperature)

## Liens rapides

- **Démarrage rapide** : [LOCAL_DEVELOPMENT](LOCAL_DEVELOPMENT.md)
- **Déploiement infrastructure** : [INFRASTRUCTURE](INFRASTRUCTURE.md) et [infra/deploy.ps1](../infra/deploy.ps1)
- **Modèles requis** : [MODELS.md#required-models-for-poc](MODELS.md)
- **Analyse de coûts** : [COSTS_LOGIC](COSTS_LOGIC.md)
- **Test E2E** : [SCENARIO_E2E](SCENARIO_E2E.md)
- **Génération d'emails de test** : [TESTING_EMAIL_GENERATION](TESTING_EMAIL_GENERATION.md)
