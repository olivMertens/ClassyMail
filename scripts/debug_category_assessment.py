"""
Debug script: test the category assessment flow directly from CLI.

Usage:
    uv run python scripts/debug_category_assessment.py
    uv run python scripts/debug_category_assessment.py --name "Relevé de compte" --slug "ddedoc_relevecompte"
    uv run python scripts/debug_category_assessment.py --name "New" --slug "new" --description "" --exclusions ""
"""

import argparse
import asyncio

# Load env vars before importing app modules
from dotenv import load_dotenv
load_dotenv("secrets.env")

from classymail.core.llm_compat import is_reasoning_model  # noqa: E402
from classymail.services.azure_clients import auth_headers, Clients  # noqa: E402
from classymail.services.llm_pipeline import resolve_model_config  # noqa: E402
from classymail.api.category_assessment import assess_category, CategoryAssessmentRequest  # noqa: E402


def separator(title: str = ""):
    print(f"\n{'=' * 60}")
    if title:
        print(f"  {title}")
        print('=' * 60)


async def test_assessment(
    name: str = "Attestation habitation",
    slug: str = "ddedoc_habitation",
    description: str = "Demande d'attestation habitation pour son logement résidentiel.\nDemande d'attestation habitation pour son logement résidentiel locatif.",
    exclusions: str = "Demande d'attestation habitation avec pour motif le télétravail.\nDemande d'attestation habitation pour une location de salle de fête.",
    language: str = "fr",
):
    separator("Category Assessment Debug")

    # --- Step 1: Show resolved model config ---
    print("\n[1] Resolving model config for 'gpt-5-nano'...")
    try:
        endpoint, deployment, api_version = resolve_model_config("gpt-5-nano")
        print(f"    Endpoint:   {endpoint}")
        print(f"    Deployment: {deployment}")
        print(f"    API Version:{api_version}")
        print(f"    Reasoning:  {is_reasoning_model(deployment)}")
    except Exception as e:
        print(f"    FAILED: {type(e).__name__}: {e}")
        return

    if not endpoint or not deployment:
        print("    ERROR: Model not configured. Set PHI_ENDPOINT in secrets.env.")
        return

    # --- Step 2: Test authentication ---
    print("\n[2] Testing authentication...")
    try:
        clients = Clients()
        headers = await auth_headers(clients=clients)
        # Mask the token for display
        auth_val = headers.get("Authorization", headers.get("api-key", ""))
        masked = auth_val[:20] + "..." if len(auth_val) > 20 else auth_val
        print(f"    Auth header: {masked}")
        print(f"    Method: {'API Key' if 'api-key' in headers else 'Bearer Token'}")
    except Exception as e:
        print(f"    AUTH FAILED: {type(e).__name__}: {e}")
        print("    -> Ensure 'az login' is done, or set AZURE_AI_KEY in secrets.env")
        return

    # --- Step 3: Show request details ---
    separator("Request Details")
    print(f"  Name:        {name}")
    print(f"  Slug:        {slug}")
    print(f"  Description: {description[:80]}{'...' if len(description) > 80 else ''}")
    print(f"  Exclusions:  {exclusions[:80]}{'...' if len(exclusions) > 80 else ''}")
    print(f"  Language:    {language}")

    # --- Step 4: Call the actual endpoint handler ---
    separator("Calling assess_category()")
    request = CategoryAssessmentRequest(
        name=name,
        slug=slug,
        description=description,
        exclusions=exclusions,
        language=language,
    )

    try:
        result = await assess_category(request)
        separator("SUCCESS - Assessment Result")
        print(f"  Quality Score: {result.quality_score}")
        print(f"  Advice:        {result.advice}")
        if result.specific_suggestions:
            print(f"  Suggestions ({len(result.specific_suggestions)}):")
            for i, s in enumerate(result.specific_suggestions, 1):
                print(f"    {i}. {s[:120]}{'...' if len(s) > 120 else ''}")
        else:
            print("  Suggestions:   (none)")
        print()
    except Exception as e:
        separator("FAILED")
        print(f"  Error Type: {type(e).__name__}")
        print(f"  Detail:     {e}")
        # If HTTPException, show status
        if hasattr(e, "status_code"):
            print(f"  HTTP Status: {e.status_code}")
        if hasattr(e, "detail"):
            print(f"  HTTP Detail: {e.detail}")
        import traceback
        print("\n  Full traceback:")
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Debug category assessment flow")
    parser.add_argument("--name", default="Attestation habitation", help="Category name")
    parser.add_argument("--slug", default="ddedoc_habitation", help="Category slug")
    parser.add_argument("--description", default=None, help="Category description (empty string for empty)")
    parser.add_argument("--exclusions", default=None, help="Category exclusions (empty string for empty)")
    parser.add_argument("--language", default="fr", choices=["fr", "en"], help="Response language")
    parser.add_argument("--empty", action="store_true", help="Test with empty description and exclusions")
    args = parser.parse_args()

    # Default descriptions if not overridden
    desc = args.description
    excl = args.exclusions

    if args.empty:
        desc = ""
        excl = ""
    elif desc is None:
        desc = (
            "Demande d'attestation habitation pour son logement résidentiel.\n"
            "Demande d'attestation habitation pour son logement résidentiel locatif."
        )
    if excl is None:
        excl = (
            "Demande d'attestation habitation avec pour motif le télétravail.\n"
            "Demande d'attestation habitation pour une location de salle de fête."
        )

    asyncio.run(test_assessment(
        name=args.name,
        slug=args.slug,
        description=desc,
        exclusions=excl,
        language=args.language,
    ))


if __name__ == "__main__":
    main()
