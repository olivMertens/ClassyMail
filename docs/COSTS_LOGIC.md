# Analyse de la Logique des Coûts

## Vue d'ensemble

L'UI de coûts dans l'onglet "Costs" permet de projeter les coûts mensuels de l'infrastructure Azure en fonction du volume d'emails projeté. Elle propose deux modes de calcul:

1. **Fixed Estimate (POC)** - Mode par défaut
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

#### Étape 3: Ajout des coûts fixes d'infrastructure

##### Mode "Fixed Estimate (POC)"

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

La logique actuelle est **correcte et pertinente** pour un POC:

1. **Coûts AI réels**: Basés sur l'usage observé (très précis)
2. **Projection linéaire**: Simple et efficace pour les estimations
3. **Coûts fixes**: Appropriés pour l'infrastructure stable
4. **Deux modes**: Permet flexibilité (POC vs Production)

### 📊 Usage Recommandé

#### Pour un POC (≤ 1000 emails/mois)
→ Utiliser **"Fixed Estimate (POC)"**
- Estimations rapides et simples
- Pas besoin d'API externe
- Coûts fixes suffisamment précis

#### Pour la Production (> 1000 emails/mois)
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
✅ **Pertinente pour POC et Production**
✅ **Facilement configurable via variables d'environnement**
✅ **Deux modes adaptés aux différents besoins**

**Recommandation**: Conserver la logique actuelle et utiliser le mode "Fixed Estimate (POC)" pour les démonstrations, puis passer au mode "Retail" pour les projections de production.
