#!/usr/bin/env python3
"""
End-to-end test script that generates realistic emails and uploads them via API.

This script:
1. Generates realistic French insurance email PDFs
2. Uploads them to the API (/api/upload)
3. Waits for processing
4. Checks the results

Usage:
    uv run python scripts/test_e2e_flow.py --count 5 --api-url http://localhost:8000
"""

import argparse
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from fpdf import FPDF
except ImportError:
    print("Error: fpdf2 is required. Install it with: uv pip install fpdf2")
    sys.exit(1)


# Realistic email templates
EMAIL_TEMPLATES = {
    "Attestation habitation": [
        ("Demande d'attestation d'assurance habitation", "Marie Dubois",
         "Je souhaiterais recevoir une attestation d'assurance habitation pour mon logement situé au 15 rue des Fleurs, 75001 Paris. Cette attestation est nécessaire pour la signature de mon contrat de location prévu le 15 février prochain."),
        ("Attestation urgente", "Jean Martin",
         "Mon agence me réclame une attestation d'assurance habitation pour mon nouveau logement. Adresse : 42 Avenue de la République, 69003 Lyon. Merci de me la faire parvenir rapidement."),
    ],
    "Résiliation": [
        ("Demande de résiliation de contrat", "Sophie Laurent",
         "Je souhaite résilier mon contrat d'assurance habitation n° HAB-12345 à compter du 31 mars 2026. Je déménage à l'étranger pour raisons professionnelles."),
        ("Résiliation suite déménagement", "Pierre Durand",
         "Suite à mon déménagement, je vous informe de ma volonté de résilier mon contrat d'assurance auto n° AUTO-98765 au 15 février 2026."),
    ],
    "Sinistre dégât des eaux": [
        ("Déclaration sinistre dégât des eaux", "Claire Rousseau",
         "Je déclare un sinistre dégât des eaux survenu le 25 janvier 2026 dans mon appartement. L'eau provient de l'étage supérieur et a endommagé mon salon et ma chambre. Contrat : HAB-54321."),
        ("Dégât des eaux urgent", "Marc Blanc",
         "Fuite d'eau importante dans ma cuisine depuis ce matin. Dégâts matériels importants (meubles, électroménager). Intervention plombier en cours. Besoin expertise rapide."),
    ],
    "Demande de devis": [
        ("Devis assurance auto", "Thomas Petit",
         "Je souhaite obtenir un devis pour assurer ma nouvelle voiture (Renault Clio 2026). Je recherche une formule tous risques avec protection conducteur."),
        ("Devis habitation", "Emma Moreau",
         "Pourriez-vous m'établir un devis pour une assurance habitation ? Appartement de 65m², 2 pièces, Paris 18ème. Locataire. Besoin couverture complète."),
    ],
    "Modification contrat": [
        ("Changement d'adresse", "Lucas Simon",
         "Je déménage le 1er mars 2026. Nouvelle adresse : 28 Boulevard Gambetta, 33000 Bordeaux. Merci de mettre à jour mon contrat HAB-11111."),
        ("Ajout conducteur secondaire", "Julie Bernard",
         "Je souhaite ajouter mon conjoint comme conducteur secondaire sur mon contrat auto n° AUTO-22222. Permis obtenu en 2020, aucun sinistre."),
    ],
}


def generate_email_pdf(subject: str, sender: str, body: str) -> bytes:
    """Generate a PDF email."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(200, 10, txt="EMAIL", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 10, txt="From:", ln=False)
    pdf.set_font("Arial", "", 10)
    pdf.cell(170, 10, txt=sender, ln=True)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 10, txt="Subject:", ln=False)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(170, 10, txt=subject)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 10, txt="Date:", ln=False)
    pdf.set_font("Arial", "", 10)
    pdf.cell(170, 10, txt=datetime.now().strftime("%d/%m/%Y %H:%M"), ln=True)

    pdf.ln(10)
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(0, 6, txt=body)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def upload_pdf(api_url: str, pdf_bytes: bytes, filename: str) -> dict:
    """Upload a PDF via the API."""
    url = f"{api_url.rstrip('/')}/api/upload"

    files = {
        "file": (filename, pdf_bytes, "application/pdf")
    }

    try:
        response = httpx.post(url, files=files, timeout=30.0)
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_email_status(api_url: str, email_id: str) -> dict:
    """Check the status of a processed email."""
    url = f"{api_url.rstrip('/')}/api/emails/{email_id}"

    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return {"success": True, "data": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="E2E test with realistic email generation")
    parser.add_argument("--count", type=int, default=5, help="Number of emails to generate")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--wait", type=int, default=10, help="Seconds to wait between uploads")
    args = parser.parse_args()

    print("=" * 70)
    print("📧 End-to-End Email Classification Test")
    print("=" * 70)
    print()
    print(f"API URL: {args.api_url}")
    print(f"Emails to generate: {args.count}")
    print(f"Wait time: {args.wait}s")
    print()

    # Generate and upload emails
    results = []

    for i in range(args.count):
        # Pick random category and template
        import random
        category = random.choice(list(EMAIL_TEMPLATES.keys()))
        templates = EMAIL_TEMPLATES[category]
        subject, sender, body = random.choice(templates)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_email_{timestamp}_{i+1}.pdf"

        print(f"[{i+1}/{args.count}] Generating email...")
        print(f"  Category: {category}")
        print(f"  Subject: {subject}")

        # Generate PDF
        pdf_bytes = generate_email_pdf(subject, sender, body)
        print(f"  PDF size: {len(pdf_bytes):,} bytes")

        # Upload
        print(f"  Uploading to {args.api_url}...")
        result = upload_pdf(args.api_url, pdf_bytes, filename)

        if result["success"]:
            email_id = result["data"].get("email_id")
            print(f"  ✅ Uploaded! Email ID: {email_id}")
            results.append({
                "filename": filename,
                "category": category,
                "email_id": email_id,
                "uploaded": True
            })
        else:
            print(f"  ❌ Upload failed: {result['error']}")
            results.append({
                "filename": filename,
                "category": category,
                "uploaded": False,
                "error": result["error"]
            })

        print()

        # Wait before next upload (except for last one)
        if i < args.count - 1:
            print(f"⏳ Waiting {args.wait}s before next upload...")
            time.sleep(args.wait)
            print()

    # Summary
    print()
    print("=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)

    uploaded = [r for r in results if r.get("uploaded")]
    failed = [r for r in results if not r.get("uploaded")]

    print(f"\n✅ Successfully uploaded: {len(uploaded)}/{args.count}")
    if uploaded:
        print("\nUploaded emails:")
        for r in uploaded:
            print(f"  • {r['filename']} (ID: {r['email_id']}) - Expected: {r['category']}")

    if failed:
        print(f"\n❌ Failed uploads: {len(failed)}")
        for r in failed:
            print(f"  • {r['filename']}: {r.get('error', 'Unknown error')}")

    print()
    print("💡 Next steps:")
    print(f"  1. Check dashboard: {args.api_url}")
    print("  2. Wait for processing to complete (~30-60s per email)")
    print("  3. Verify classifications match expected categories")
    print()

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
