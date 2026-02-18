"""
Test de validation pour l'analyse de coûts (UI).

Ce test vérifie que la logique "Emails / Month Projection" et "Pricing Source"
fonctionne correctement avec les deux modes: fixed et retail.
"""

import pytest
from unittest.mock import AsyncMock, patch
from classymail.api.routers.costs import costs_summary
from classymail.services.azure_clients import Clients


@pytest.fixture
def mock_clients():
    """Mock des clients Azure."""
    clients = AsyncMock(spec=Clients)
    clients.credential = AsyncMock()
    return clients


@pytest.mark.asyncio
async def test_costs_summary_fixed_mode(mock_clients):
    """Test du mode 'fixed' (Fixed Estimate POC)."""

    # Mock des fonctions de repository
    with patch("classymail.api.routers.costs.count_by_status") as mock_count, \
         patch("classymail.api.routers.costs.sum_phi4_cost_usd") as mock_phi4, \
         patch("classymail.api.routers.costs.sum_mistral_cost_usd") as mock_mistral, \
         patch("classymail.api.routers.costs.sum_di_cost_usd") as mock_di, \
         patch("classymail.api.routers.costs.sum_llm_tokens") as mock_tokens, \
         patch("classymail.api.routers.costs.count_items_with_any_usage_cost") as mock_usage:

        # Simuler 100 emails traités
        mock_count.side_effect = lambda status, **_: {
            "PROCESSED": 80,
            "REVIEW_REQUIRED": 15,
            "ERROR": 5,
        }[status]

        # Coûts réels observés pour 100 emails
        mock_phi4.return_value = 0.50  # 0.005 USD par email
        mock_mistral.return_value = 1.00  # 0.01 USD par email
        mock_di.return_value = 0.0
        mock_tokens.return_value = {"prompt_tokens": 50000, "completion_tokens": 10000}
        mock_usage.return_value = 100

        # Test avec projection de 10,000 emails/mois
        result = await costs_summary(
            emails_per_month=10_000,
            pricing_source="fixed",
            region="swedencentral",
            clients=mock_clients
        )

        # Vérifications
        assert result["counts"]["total"] == 100
        assert result["counts"]["emails_with_usage"] == 100

        # Coûts AI réels
        assert result["actual_usd"]["phi4"] == 0.50
        assert result["actual_usd"]["mistral_ocr"] == 1.00
        assert result["actual_usd"]["ai_total"] == 1.50

        # Moyenne par email
        assert result["avg_usd_per_email"]["ai_total"] == 0.015  # (0.50 + 1.00) / 100

        # Projection pour 10,000 emails
        projected_ai = result["projection_monthly_usd"]["ai_variable"]
        assert projected_ai == pytest.approx(150.0, rel=0.01)  # 0.015 * 10,000

        # Coûts fixes (valeurs par défaut)
        fixed_total = result["fixed_monthly_estimates_usd"]["total"]
        assert fixed_total == pytest.approx(34.0, rel=0.01)  # 9 + 5 + 20 + 0 + 0

        # Total projeté
        total = result["projection_monthly_usd"]["total"]
        assert total == pytest.approx(184.0, rel=0.01)  # 150 + 34

        # Pricing source
        assert result["pricing"]["source"] == "fixed"
        assert result["pricing"]["retail"] is None


@pytest.mark.asyncio
async def test_costs_summary_retail_mode(mock_clients):
    """Test du mode 'retail' (Azure Retail Prices API)."""

    with patch("classymail.api.routers.costs.count_by_status") as mock_count, \
         patch("classymail.api.routers.costs.sum_phi4_cost_usd") as mock_phi4, \
         patch("classymail.api.routers.costs.sum_mistral_cost_usd") as mock_mistral, \
         patch("classymail.api.routers.costs.sum_di_cost_usd") as mock_di, \
         patch("classymail.api.routers.costs.sum_llm_tokens") as mock_tokens, \
         patch("classymail.api.routers.costs.count_items_with_any_usage_cost") as mock_usage, \
         patch("classymail.api.routers.costs.get_retail_unit_prices") as mock_retail:

        # Mock repository data
        mock_count.side_effect = lambda status, **_: {
            "PROCESSED": 50,
            "REVIEW_REQUIRED": 5,
            "ERROR": 0,
        }[status]
        mock_phi4.return_value = 0.25
        mock_mistral.return_value = 0.50
        mock_di.return_value = 0.0
        mock_tokens.return_value = {"prompt_tokens": 25000, "completion_tokens": 5000}
        mock_usage.return_value = 55

        # Mock Azure Retail Prices API response
        mock_retail.return_value = {
            "aca": {
                "vcpu_seconds": {"unit_price": 0.000024, "unit_of_measure": "1 Second"},
                "gib_seconds": {"unit_price": 0.0000026, "unit_of_measure": "1 Second"},
                "requests": {"unit_price": 0.000001, "unit_of_measure": "1 Request"},
            },
            "service_bus": {
                "operations": {"unit_price": 0.00000008, "unit_of_measure": "1 Operation"}
            },
            "log_analytics": {
                "data_ingestion": {"unit_price": 2.30, "unit_of_measure": "1 GB"}
            },
            "assumptions": {
                "aca_worker_seconds_per_email": 10.0,
                "aca_worker_vcpu": 0.5,
                "aca_worker_gib": 1.0,
                "aca_api_min_replicas": 1.0,
                "aca_api_idle_hours_per_month": 720.0,  # 24h/day * 30 days
                "sb_ops_per_email": 5.0,
                "log_gb_per_email": 0.0001,  # 100 KB per email
            }
        }

        # Test avec retail pricing
        result = await costs_summary(
            emails_per_month=5_000,
            pricing_source="retail",
            region="swedencentral",
            clients=mock_clients
        )

        # Vérifications
        assert result["pricing"]["source"] == "retail"
        assert result["pricing"]["retail"] is not None
        assert result["pricing"]["retail_estimates_usd"] is not None

        # Les estimations retail doivent être présentes
        retail_estimates = result["pricing"]["retail_estimates_usd"]
        assert "container_apps" in retail_estimates
        assert "service_bus" in retail_estimates
        assert "app_insights" in retail_estimates

        # Tous les coûts doivent être positifs
        assert retail_estimates["container_apps"] > 0
        assert retail_estimates["service_bus"] > 0


@pytest.mark.asyncio
async def test_costs_summary_zero_emails(mock_clients):
    """Test avec zéro email (cas limite)."""

    with patch("classymail.api.routers.costs.count_by_status") as mock_count, \
         patch("classymail.api.routers.costs.sum_phi4_cost_usd") as mock_phi4, \
         patch("classymail.api.routers.costs.sum_mistral_cost_usd") as mock_mistral, \
         patch("classymail.api.routers.costs.sum_di_cost_usd") as mock_di, \
         patch("classymail.api.routers.costs.sum_llm_tokens") as mock_tokens, \
         patch("classymail.api.routers.costs.count_items_with_any_usage_cost") as mock_usage:

        mock_count.return_value = 0
        mock_phi4.return_value = 0.0
        mock_mistral.return_value = 0.0
        mock_di.return_value = 0.0
        mock_tokens.return_value = {"prompt_tokens": 0, "completion_tokens": 0}
        mock_usage.return_value = 0

        result = await costs_summary(
            emails_per_month=10_000,
            pricing_source="fixed",
            region="swedencentral",
            clients=mock_clients
        )

        # Avec zéro emails traités, la moyenne doit être 0
        assert result["avg_usd_per_email"]["ai_total"] == 0.0

        # La projection AI variable doit être 0
        assert result["projection_monthly_usd"]["ai_variable"] == 0.0

        # Mais les coûts fixes doivent toujours être présents
        assert result["projection_monthly_usd"]["fixed"] > 0


@pytest.mark.asyncio
async def test_costs_breakdown_consistency(mock_clients):
    """Vérifie la cohérence entre le total et le breakdown."""

    with patch("classymail.api.routers.costs.count_by_status") as mock_count, \
         patch("classymail.api.routers.costs.sum_phi4_cost_usd") as mock_phi4, \
         patch("classymail.api.routers.costs.sum_mistral_cost_usd") as mock_mistral, \
         patch("classymail.api.routers.costs.sum_di_cost_usd") as mock_di, \
         patch("classymail.api.routers.costs.sum_llm_tokens") as mock_tokens, \
         patch("classymail.api.routers.costs.count_items_with_any_usage_cost") as mock_usage:

        mock_count.return_value = 100
        mock_phi4.return_value = 1.0
        mock_mistral.return_value = 2.0
        mock_di.return_value = 0.0
        mock_tokens.return_value = {"prompt_tokens": 100000, "completion_tokens": 20000}
        mock_usage.return_value = 100

        result = await costs_summary(
            emails_per_month=1_000,
            pricing_source="fixed",
            region="swedencentral",
            clients=mock_clients
        )

        # Somme du breakdown doit égaler le total
        breakdown = result["projection_monthly_usd"]["breakdown"]
        breakdown_total = sum(item["usd"] for item in breakdown)
        expected_total = result["projection_monthly_usd"]["total"]

        assert breakdown_total == pytest.approx(expected_total, rel=0.01)

        # Le breakdown doit contenir toutes les ressources
        resources = [item["resource"] for item in breakdown]
        assert "Mistral OCR (variable)" in resources
        assert "Phi-4 / LLM (variable)" in resources
        assert "Service Bus (fixe)" in resources
        assert "Storage (fixe)" in resources
        assert "Container Apps (fixe)" in resources


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
