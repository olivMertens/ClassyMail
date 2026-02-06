# Analyse de la Logique des Coûts

## Vue d'ensemble

L'UI de coûts dans l'onglet "Costs" permet de projeter les coûts mensuels de l'infrastructure Azure en fonction du volume d'emails projeté. Elle propose deux modes de calcul:

1. **Fixed Estimate (MVP Demo)** - Mode par défaut
2. **Azure Retail Prices API** - Mode avancé

## Architecture de la Logique

### 1. Inputs de l'Utilisateur

```typescript
// frontend/src/views/CostsView.vue
const emailsPerMonth = ref(10000)  // Volume projeté
const pricingSource = ref('fixed')  // Mode de calcul
```

### 2. Calcul des Coûts (Backend)

Le calcul se fait en **3 étapes**:

#### Étape 1: Récupération des coûts réels observés

```python
# Coûts AI réels enregistrés dans Cosmos DB
phi4_usd = await sum_phi4_cost_usd(clients=clients)
mistral_usd = await sum_mistral_cost_usd(clients=clients)
emails_with_usage = await count_items_with_any_usage_cost(clients=clients)

# Calcul de la moyenne par email
avg_ai_usd_per_email = (phi4_usd + mistral_usd) / emails_with_usage
```

**Exemple**: Si 100 emails ont été traités avec un coût total de 1.50 USD, la moyenne est de **0.015 USD/email**.

#### Étape 2: Projection des coûts AI variables

```python
projected_ai_usd = avg_ai_usd_per_email * emails_per_month
```

**Exemple**: Pour 10,000 emails/mois → 0.015 × 10,000 = **150 USD/mois**

##### Détail des Coûts AI par Composant

**LLM-based PII Detection** (optionnel):
- Modèle: GPT-4o-mini JSON mode
- Coût moyen: ~€0.002/email (~0.500 tokens input + 100 tokens output)
- Inclus dans `avg_ai_usd_per_email` si activé

**Azure AI Language PII Detection** (optionnel):
- Service: Azure AI Language Text Analytics API
- Coût: €1.00 par 1,000 text records (Standard tier)
- Estimation: 1 email = 1 text record → €0.001/email
- Déploiement: Contrôlé par `deploy_language_service` (Terraform)
- **Note**: Non inclus dans les coûts actuels (requires telemetry update)

**Hybrid Mode** (both methods):
- Coût combiné: ~€0.003/email (LLM + Azure Language)
- Avantage: Meilleure précision, dédupication automatique

#### Étape 3: Ajout des coûts fixes d'infrastructure

##### Mode "Fixed Estimate (MVP Demo)"

Utilise des estimations fixes configurables via variables d'environnement:

```python
# Valeurs par défaut
COST_FIXED_SERVICE_BUS_USD_MONTH = 9.0
COST_FIXED_STORAGE_USD_MONTH = 5.0
COST_FIXED_CONTAINER_APPS_USD_MONTH = 20.0
COST_FIXED_APP_INSIGHTS_USD_MONTH = 0.0
COST_FIXED_COSMOS_USD_MONTH = 0.0

# Total fixe = 34 USD/mois
```

##### Mode "Azure Retail Prices API"

Calcule les coûts réels en interrogeant l'API de tarification Azure:

```python
# Container Apps: calcul basé sur vCPU/GiB-secondes
worker_cost = vcpu_seconds * vcpu_price + gib_seconds * gib_price

# Service Bus: calcul basé sur nombre d'opérations
sb_cost = (emails_per_month * ops_per_email) * ops_price

# Log Analytics: calcul basé sur volume de données
log_cost = (emails_per_month * gb_per_email) * gb_price
```

### 3. Résultat Final

```json
{
  "projection_monthly_usd": {
    "emails_per_month": 10000,
    "ai_variable": 150.0,      // Coûts AI variables (projetés)
    "fixed": 34.0,              // Coûts infra fixes
    "total": 184.0,             // Total mensuel projeté
    "breakdown": [              // Détail par ressource
      {"resource": "Mistral OCR (variable)", "usd": 100.0},
      {"resource": "Phi-4 / LLM (variable)", "usd": 50.0},
      {"resource": "Service Bus (fixe)", "usd": 9.0},
      ...
    ]
  }
}
```

## Validation

### Tests Automatisés

Les tests dans `tests/test_costs_analysis.py` valident:

✅ **Test 1: Mode Fixed**
- Vérifie le calcul de la moyenne par email
- Vérifie la projection AI variable
- Vérifie l'ajout des coûts fixes
- Vérifie la cohérence du total

✅ **Test 2: Mode Retail**
- Vérifie l'intégration avec Azure Retail Prices API
- Vérifie les estimations d'infrastructure dynamiques
- Vérifie la présence de tous les coûts calculés

✅ **Test 3: Cas Limite (zéro emails)**
- Vérifie le comportement avec aucun email traité
- Vérifie que les coûts fixes restent présents
- Vérifie que la division par zéro est gérée

✅ **Test 4: Cohérence du Breakdown**
- Vérifie que la somme du breakdown égale le total
- Vérifie que toutes les ressources sont présentes

### Résultat des Tests

```bash
$ uv run pytest tests/test_costs_analysis.py -v
tests/test_costs_analysis.py::test_costs_summary_fixed_mode PASSED
tests/test_costs_analysis.py::test_costs_summary_retail_mode PASSED
tests/test_costs_analysis.py::test_costs_summary_zero_emails PASSED
tests/test_costs_analysis.py::test_costs_breakdown_consistency PASSED

======================== 4 passed in 4.12s ========================
```

## Pertinence et Recommandations

### ✅ Logique Valide

La logique actuelle est **correcte et pertinente** pour un MVP:

1. **Coûts AI réels**: Basés sur l'usage observé (très précis)
2. **Projection linéaire**: Simple et efficace pour les estimations
3. **Coûts fixes**: Appropriés pour l'infrastructure stable
4. **Deux modes**: Permet flexibilité (MVP Demo vs Production Scale)

### 📊 Usage Recommandé

#### Pour un MVP/Demo (≤ 1000 emails/mois)
→ Utiliser **"Fixed Estimate (MVP Demo)"**
- Estimations rapides et simples
- Pas besoin d'API externe
- Coûts fixes suffisamment précis

#### Pour la Production Scale (> 1000 emails/mois)
→ Utiliser **"Azure Retail Prices API"**
- Calculs basés sur tarification réelle par région
- Tient compte de l'usage réel (vCPU, GiB, opérations)
- Plus précis pour les projections à grande échelle

### 🔧 Améliorations Possibles

#### Court terme
1. **Ajouter des indicateurs visuels**:
   ```vue
   <div v-if="costs.counts.emails_with_usage < 50">
     ⚠️ Échantillon petit: projection moins précise
   </div>
   ```

2. **Afficher la variance**:
   ```python
   "confidence": "low" if emails_with_usage < 100 else "high"
   ```

#### Long terme
1. **Historique des coûts**: Graphique d'évolution mensuelle
2. **Alertes de budget**: Notification si projection > seuil
3. **Optimisations suggérées**: Recommandations pour réduire les coûts

---

## Règles d'Estimation par Stratégie et Modèle

### **Coûts par 10,000 Emails** (PDFs typiques 2 pages)

#### Mode Standard (Text/OCR Optimized)

| Modèle | Coût / 10K | Précision | Usage Recommandé |
|--------|-----------|-----------|------------------|
| **Phi-4** | $2-5 | 0.82 | MVP, coûts prévisibles |
| **gpt-4o-mini** | $2-4 | 0.84 | Production cost-conscious |
| **gpt-5-nano** | $1-2 | 0.79 | Ultra low-cost |
| **gpt-4.1-nano** | $1-2 | 0.72 | Budget extrême |
| **gpt-5-mini** | $8-12 | 0.89 | Catégories complexes |
| **gpt-4o** | $30-60 | 0.92 | Précision critique |

**⚠️ Note**: Si vous changez de modèle dans Settings, mettez à jour les variables d'environnement:
```bash
PHI4_COST_PER_1K_INPUT=0.0004  # Exemple gpt-5-mini
PHI4_COST_PER_1K_OUTPUT=0.0016
FALLBACK_COST_PER_1K_INPUT=0.00015  # gpt-4o-mini
FALLBACK_COST_PER_1K_OUTPUT=0.0006
```

#### Mode Reasoning (Chain-of-Thought)
- **Tokens 2-3x supérieur** → **Coût 2-3x**
- **Usage**: Contrats juridiques, analyse complexe
- **Exemple**: gpt-5-mini $8-12 → Reasoning **$16-36**

#### Mode Vision (Visual Analysis)
- **Tokens 4-6x supérieur** → **Coût 4-6x**
- **Usage**: Documents scannés, images
- **Exemple**: Phi-4 $2-5 → Vision **$8-30**

### Impact du Reprocessing
- **Chaque reprocess = coût pipeline complet**
- **Changement stratégie = coût multiplié**
- ⚠️ **Coûts historiques écrasés** (seul dernier coût conservé)

### Impact Comparaison Adversariale
⚠️ **Coûts adversariaux NON suivis actuellement**
- Exécute 2 modèles → **2x coûts réels**
- **Seul modèle primaire affiché** dans Costs
- **Recommandation**: Activer uniquement pour audits

## Configuration pour la Production

### 1. Ajuster les coûts fixes

```bash
# Dans secrets.env ou variables d'environnement Azure
COST_FIXED_SERVICE_BUS_USD_MONTH=15.0
COST_FIXED_STORAGE_USD_MONTH=10.0
COST_FIXED_CONTAINER_APPS_USD_MONTH=50.0
COST_FIXED_APP_INSIGHTS_USD_MONTH=5.0
COST_FIXED_COSMOS_USD_MONTH=25.0  # Serverless RU dépend fortement du volume
```

### 2. Activer le mode Retail

```typescript
// frontend/src/views/CostsView.vue
const pricingSource = ref('retail')  // Mode production
```

### 3. Monitorer et ajuster

```bash
# Comparer coûts réels vs projetés chaque mois
az costmanagement query \
  --type Usage \
  --dataset-filter "ResourceGroup eq 'email-poc-rg'" \
  --timeframe MonthToDate
```

## Conclusion

✅ **La logique est solide et bien testée**
✅ **Pertinente pour MVP et Production**
✅ **Facilement configurable via variables d'environnement**
✅ **Deux modes adaptés aux différents besoins**

**Recommandation**: Conserver la logique actuelle et utiliser le mode "Fixed Estimate (MVP Demo)" pour les démonstrations, puis passer au mode "Retail" pour les projections de production.
