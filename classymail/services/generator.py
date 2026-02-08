import random
import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
import httpx

from classymail.core.llm_compat import build_chat_params

logger = logging.getLogger(__name__)

# Realistic email templates (French)
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

def generate_email_pdf(subject: str = None, sender: str = None, body: str = None, category: str = None, use_aoai: bool = False) -> tuple[bytes, str, str]:
    """
    Generate a simple PDF email using FPDF.

    Parameters:
    -----------
    subject : str, optional
        Email subject line. If None, picks from template.
    sender : str, optional
        Sender name. If None, picks from template.
    body : str, optional
        Email body text. If None, picks from template OR generates with AOAI if use_aoai=True.
    category : str, optional
        Insurance category (for template selection). If None, random category chosen.
    use_aoai : bool, optional
        If True, attempt to use Azure OpenAI to enhance/generate the body text.
        Falls back to template if AOAI unavailable. Default: False.

    Returns:
    --------
    tuple[bytes, str, str]
        (pdf_bytes, category, subject)

    Example:
    --------
    # Random template
    pdf, cat, subj = generate_email_pdf()

    # With AOAI enhancement
    pdf, cat, subj = generate_email_pdf(category="Sinistre dégât des eaux", use_aoai=True)
    """
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError("fpdf2 is required. Install it via 'pip install fpdf2'.")

    # If any specific detail is missing, go for random generation or fill gaps
    if not all([subject, sender, body]):
        # Pick random if category not specific or finding a template
        if not category or category not in EMAIL_TEMPLATES:
            # If no category provided, pick any random category
            category_key = random.choice(list(EMAIL_TEMPLATES.keys()))
        else:
            category_key = category

        # Pick a random template from the chosen category
        templates = EMAIL_TEMPLATES[category_key]
        chosen_subject, chosen_sender, chosen_body = random.choice(templates)

        # Override with any provided values (though unlikely mixed usage)
        subject = subject or chosen_subject
        sender = sender or chosen_sender
        body = body or chosen_body
        category = category_key
    else:
        if not category:
            category = "Custom"

    # Optionally enhance body with AOAI
    if use_aoai and not all([subject, sender]):
        # Only enhance if caller didn't provide all details
        enhanced_body = _aoai_enhance_body(body, category)
        if enhanced_body:
            body = enhanced_body

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
    # multi_cell for subject if long
    pdf.multi_cell(170, 10, txt=subject)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 10, txt="Date:", ln=False)
    pdf.set_font("Arial", "", 10)
    pdf.cell(170, 10, txt=datetime.now().strftime("%d/%m/%Y %H:%M"), ln=True)

    pdf.ln(10)
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(0, 6, txt=body)

    # Output to byte buffer
    return bytes(pdf.output()), category, subject


def _aoai_enhance_body(body: str, category: str) -> Optional[str]:
    """
    Synchronously call Azure OpenAI to enhance/expand email body with realism.
    Returns enhanced body, or None if AOAI unavailable.
    """
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

    if not endpoint:
        return None

    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")
    url = endpoint.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    headers = {"Content-Type": "application/json"}

    if api_key:
        headers["api-key"] = api_key
    else:
        # Try to get token via DefaultAzureCredential
        try:
            from azure.identity import DefaultAzureCredential
            scope = os.getenv("AZURE_OPENAI_SCOPE", "https://cognitiveservices.azure.com/.default")
            credential = DefaultAzureCredential()
            token = credential.get_token(scope)
            headers["Authorization"] = f"Bearer {token.token}"
        except Exception:
            return None

    prompt = (
        f"Enhance this insurance email body with more realistic details, "
        f"occasional typos, and natural French phrasing. "
        f"Category: {category}\n\n"
        f"Original:\n{body}\n\n"
        f"Enhanced (max 200 words):"
    )

    body_payload = {
        **build_chat_params(deployment, temperature=0.7, max_output_tokens=800),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You enhance insurance email bodies with realistic details. "
                    "Keep the original intent but add natural variations, occasional typos (not many), "
                    "and authentic French phrasing. Stay concise."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    try:
        timeout_s = float(os.getenv("AZURE_OPENAI_TIMEOUT", "15"))
        response = httpx.post(url, headers=headers, json=body_payload, timeout=timeout_s)
        if response.status_code >= 400:
            return None
        data = response.json()
        enhanced = (data.get("choices") or [{}])[0].get("message", {}).get("content")
        return enhanced if enhanced else None
    except Exception:
        return None

async def generate_synthetic_from_seeds(seed_examples: list[dict], count: int = 5) -> list[dict]:
    """
    Generates synthetic email records based on seed examples using Azure OpenAI.
    Resulting records mimic the seed's classification but vary in content.
    """
    if not seed_examples or count <= 0:
        return []

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("CHAT_DEPLOYMENT", "gpt-5.2-chat") # User requested gpt5-2 chat specifically
    # Fallback if CHAT_DEPLOYMENT not set or incorrect, try GPT_DEPLOYMENT or just hardcode what we saw in context
    if not deployment:
         deployment = os.getenv("GPT_DEPLOYMENT", "gpt-4o")

    if not endpoint:
        logger.error("Cannot generate synthetic data: AZURE_OPENAI_ENDPOINT not set.")
        return []

    # Get Auth Headers (Async)
    # We duplicate auth logic slightly to avoid heavy deps, or assume client provided.
    # Ideally should use AzureClients but we want to avoid circular deps with repository/clients here if possible.
    # Let's try raw HTTPX async with token resolution if possible, or key.
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AI_API_VERSION", "2024-10-01-preview")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    else:
        try:
             from azure.identity.aio import DefaultAzureCredential
             scope = os.getenv("AZURE_OPENAI_SCOPE", "https://cognitiveservices.azure.com/.default")
             async with DefaultAzureCredential() as credential:
                token = await credential.get_token(scope)
                headers["Authorization"] = f"Bearer {token.token}"
        except ImportError:
             logger.error("azure-identity not installed or async credential failed.")
             return []
        except Exception as e:
             logger.error(f"Failed to get token: {e}")
             return []

    url = endpoint.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    results = []

    # We will generate in batches or one by one. One by one is safer for large context.
    # Let's parallelize slightly or just loop. Loop is safer for rate limits.

    generated_count = 0
    while generated_count < count:
        # Pick a seed
        seed = random.choice(seed_examples)
        seed_md = seed.get("markdown", "")
        seed_cls = seed.get("classification", {})
        seed_subj = seed.get("subject", "")

        # Construct Prompt
        # We want the model to generate a NEW email that matches the intent distribution of the seed
        system_prompt = (
            "You are a synthetic data generator for an insurance email processing system. "
            "Generate a REALISTIC, FRENCH email that matches the classification provided in the example. "
            "Identify the intents and categorization from the seed, and create a NEW, DISTINCT email "
            "with different entities (names, addresses), different phrasing, maybe a different scenario "
            "but the SAME underlying classification intent. "
            "Output strictly valid JSON with keys: 'subject', 'markdown' (the body), and keep the 'classification' roughly the same structure."
        )

        user_prompt = (
            f"SEED EXAMPLE:\n"
            f"Subject: {seed_subj}\n"
            f"Body:\n{seed_md}\n\n"
            f"Classification:\n{json.dumps(seed_cls)}\n\n"
            f"TASK:\n"
            f"Generate 1 new distinct example in JSON format matching this classification/intent."
        )

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": { "type": "json_object" },
            **build_chat_params(deployment, temperature=0.8, max_output_tokens=1000),
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.error(f"Generation failed: {resp.text}")
                    continue

                content = resp.json()["choices"][0]["message"]["content"]
                new_data = json.loads(content)

                # Check structure
                if "markdown" not in new_data:
                    # sometimes puts body in 'body'
                    new_data["markdown"] = new_data.get("body", "")

                # Validate it has classification or copy from seed
                if "classification" not in new_data:
                    new_data["classification"] = seed_cls # Fallback

                # Add metadata
                record = {
                    "id": str(uuid.uuid4()),
                    "status": "PROCESSED",
                    "subject": new_data.get("subject", "Synthetic Email"),
                    "markdown": new_data.get("markdown", ""),
                    "classification": new_data.get("classification"),
                    "file_url": "synthetic://generated",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "reviewed": True, # Mark as reviewed so it counts for export
                    "correction_reason": "Synthetic Generation",
                    "is_synthetic": True
                }

                results.append(record)
                generated_count += 1

        except Exception as e:
            logger.error(f"Error generating synthetic item: {e}")
            # Do not infinite loop if persistent error
            break

    return results
