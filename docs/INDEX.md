# Documentation

> 📊 **Diagrammes Interactifs** : Ouvrez [index.html](./index.html) pour une documentation interactive avec zoom et téléchargement des diagrammes !
> Voir aussi : [README_DIAGRAMS.md](./README_DIAGRAMS.md) | [Outil d'export](./mermaid-export.html)

> 🔧 **Documentation consolidée** : Réduite de 21 à 16 fichiers pour une navigation plus claire. Les guides ont été regroupés par thématique.

## Navigation

### 🏗️ Core Architecture
- [ARCHITECTURE](ARCHITECTURE.md) - Architecture système, RBAC, et détails du pipeline de traitement
- [MODELS](MODELS.md) - Modèles AI et configurations
- [COSTS_LOGIC](COSTS_LOGIC.md) - Logique d'analyse de coûts et comparaison de modèles

### 🚀 Déploiement & Infrastructure
- [INFRASTRUCTURE](INFRASTRUCTURE.md) - Déploiement Terraform, configuration Azure, Event Grid, RBAC
- [CLI_SETUP](CLI_SETUP.md) - Configuration CLI et identité managée (commandes rapides)

### 💻 Développement Local
- [LOCAL_DEVELOPMENT](LOCAL_DEVELOPMENT.md) - Setup, exécution locale, build Docker, testing, troubleshooting

### 🔄 CI/CD
- [CICD_GITHUB](CICD_GITHUB.md) - Pipeline CI/CD GitHub

### 🧪 Testing & Quality
- [SCENARIO_E2E](SCENARIO_E2E.md) - Scénarios end-to-end
- [TESTING_EMAIL_GENERATION](TESTING_EMAIL_GENERATION.md) - Génération d'emails de test
- [FINE_TUNING_DATA](FINE_TUNING_DATA.md) - Génération de datasets fine-tuning

### 📱 Interface & ADRs
- [USER_INTERFACE](USER_INTERFACE.md) - Interface utilisateur
- [ADR_OCR_STRATEGY](ADR_OCR_STRATEGY.md) - Architecture Decision Record: OCR Strategy
- [RBAC_AUDIT](RBAC_AUDIT.md) - Audit et troubleshooting RBAC détaillé

## Liens rapides

- **Démarrage rapide** : [LOCAL_DEVELOPMENT](LOCAL_DEVELOPMENT.md)
- **Déploiement infrastructure** : [INFRASTRUCTURE](INFRASTRUCTURE.md) et [infra/deploy.ps1](../infra/deploy.ps1)
- **Analyse de coûts** : [COSTS_LOGIC](COSTS_LOGIC.md)
- **Test E2E** : [SCENARIO_E2E](SCENARIO_E2E.md)
- **Génération d'emails de test** : [TESTING_EMAIL_GENERATION](TESTING_EMAIL_GENERATION.md)
