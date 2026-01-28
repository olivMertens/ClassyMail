import random
import os
from datetime import datetime
from typing import Optional
import httpx

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
        "temperature": 0.7,
        "max_tokens": 800,
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
