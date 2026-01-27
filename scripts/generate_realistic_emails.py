"""
Generate realistic email PDFs for testing the classification pipeline.

Usage:
    python scripts/generate_realistic_emails.py --count 10 --out dataset/pdf
"""

import argparse
import random
import string
import time
from datetime import datetime
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("Error: fpdf2 is required. Install it with: pip install fpdf2")
    exit(1)


# Realistic email templates by category
EMAIL_TEMPLATES = {
    "Attestation habitation": [
        {
            "subject": "Demande d'attestation d'assurance habitation",
            "sender": "Marie Dubois <marie.dubois@email.com>",
            "body": """Bonjour,

Je souhaiterais recevoir une attestation d'assurance habitation pour mon logement situé au 15 rue des Fleurs, 75001 Paris.

Cette attestation est nécessaire pour la signature de mon contrat de location prévu le 15 février prochain.

Pourriez-vous me l'envoyer par email dans les plus brefs délais ?

Merci d'avance,
Cordialement,
Marie Dubois
Contrat n° 12345678"""
        },
        {
            "subject": "Attestation urgente pour agence immobilière",
            "sender": "Jean Martin <j.martin@gmail.com>",
            "body": """Madame, Monsieur,

Mon agence me réclame une attestation d'assurance habitation pour mon nouveau logement.

Adresse : 42 Avenue de la République, 69003 Lyon
Numéro de contrat : HAB-2026-001234

Merci de me la faire parvenir rapidement.

Bien à vous,
Jean Martin"""
        }
    ],
    "Résiliation": [
        {
            "subject": "Résiliation contrat auto suite déménagement",
            "sender": "Sophie Laurent <sophie.l@outlook.fr>",
            "body": """Bonjour,

Je vous informe de mon déménagement à l'étranger (Belgique) prévu pour fin mars 2026.

Je souhaite résilier mon contrat d'assurance auto n° AUTO-45678912 pour ma Renault Clio immatriculée AB-123-CD.

Date de résiliation souhaitée : 31/03/2026

Merci de me confirmer la procédure et les documents nécessaires.

Cordialement,
Sophie Laurent"""
        },
        {
            "subject": "Annulation assurance habitation - vente appartement",
            "sender": "Pierre Durand <p.durand@wanadoo.fr>",
            "body": """Madame, Monsieur,

J'ai vendu mon appartement du 78 boulevard Voltaire, 75011 Paris.
La vente est effective depuis le 20 janvier 2026.

Je souhaite résilier mon contrat d'assurance habitation n° HAB-78901234.

Veuillez me confirmer la date d'effet de la résiliation et me transmettre le solde de ma cotisation si applicable.

Merci,
Pierre Durand
Tél: 06 12 34 56 78"""
        }
    ],
    "Dommages électriques": [
        {
            "subject": "Sinistre suite orage - équipements endommagés",
            "sender": "Isabelle Moreau <i.moreau@free.fr>",
            "body": """Bonjour,

Suite à l'orage violent du 25 janvier, plusieurs équipements électriques de mon domicile ont été endommagés :

- Télévision Samsung 55" (valeur : 800€)
- Box internet Freebox
- Micro-ondes Whirlpool
- Console de jeux PlayStation 5

J'ai fait constater les dégâts par un électricien (devis ci-joint).

Contrat habitation n° HAB-567890
Adresse : 33 rue du Commerce, 44000 Nantes

Pourriez-vous m'indiquer la procédure à suivre pour déclarer ce sinistre ?

Cordialement,
Isabelle Moreau"""
        }
    ],
    "Sinistre dégât des eaux": [
        {
            "subject": "URGENT - Fuite d'eau appartement du dessus",
            "sender": "Thomas Bernard <thomas.bernard@gmail.com>",
            "body": """Bonjour,

Je déclare un sinistre dégât des eaux survenu ce matin à 7h30.

Situation : Une fuite importante provient de l'appartement du dessus et a causé des dégâts dans ma salle de bain et ma chambre.

Dégâts constatés :
- Plafond de la salle de bain effondré partiellement
- Murs humides avec traces de moisissure
- Parquet de la chambre gondolé
- Mobilier endommagé (lit, armoire)

J'ai prévenu le syndic et fait un constat amiable avec mon voisin.

Contrat : MRH-345678
Adresse : Appt 23, 5 rue Pasteur, 33000 Bordeaux

Merci de me rappeler rapidement pour l'expertise.

Urgent,
Thomas Bernard
06 98 76 54 32"""
        }
    ],
    "Modification contrat": [
        {
            "subject": "Ajout conducteur secondaire",
            "sender": "Caroline Petit <c.petit@yahoo.fr>",
            "body": """Bonjour,

Je souhaite ajouter ma fille de 22 ans comme conductrice secondaire sur mon contrat d'assurance auto.

Contrat n° AUTO-123456
Véhicule : Peugeot 308 - FG-789-HJ

Informations conductrice :
- Nom : PETIT Emma
- Date de naissance : 15/06/2003
- Permis obtenu le : 08/09/2021
- Aucun sinistre

Merci de me communiquer le surcoût éventuel.

Cordialement,
Caroline Petit"""
        }
    ],
    "Demande de devis": [
        {
            "subject": "Devis assurance multirisque habitation",
            "sender": "Alexandre Roux <a.roux@hotmail.com>",
            "body": """Madame, Monsieur,

Je recherche une assurance multirisque habitation pour mon futur logement :

Type : Appartement T3
Surface : 65 m²
Adresse : 12 avenue Jean Jaurès, 31000 Toulouse
Valeur mobilier estimée : 15 000€
Date d'effet souhaitée : 01/03/2026

Options souhaitées :
- Protection juridique
- Assistance 24h/24
- Garantie dommages électriques

Pourriez-vous m'établir un devis ?

Merci,
Alexandre Roux
07 11 22 33 44"""
        }
    ],
    "Réclamation": [
        {
            "subject": "Contestation refus de prise en charge",
            "sender": "Valérie Rousseau <v.rousseau@gmail.com>",
            "body": """Madame, Monsieur,

Je conteste votre décision de refuser la prise en charge de mon sinistre déclaré le 10 janvier 2026 (dossier n° SIN-2026-1234).

Vous invoquez une clause d'exclusion que je ne comprends pas. Mon contrat MRH-987654 mentionne clairement la garantie vol avec effraction.

Le vol a bien eu lieu avec effraction constatée par la police (PV n° 2026/0123).

Je demande le réexamen de mon dossier et une prise en charge conforme à mes garanties.

Dans l'attente de votre retour,
Valérie Rousseau"""
        }
    ]
}


def generate_random_id(length=6):
    """Generate a random alphanumeric ID."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def create_email_pdf(category, template, output_dir):
    """Create a realistic email PDF."""
    pdf = FPDF()
    pdf.add_page()

    # Email header styling
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, template["subject"], ln=True)
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, f"De: {template['sender']}", ln=True)
    pdf.cell(0, 6, f"Date: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.ln(5)

    # Email body
    pdf.set_font("Arial", "", 11)
    for line in template["body"].split('\n'):
        if line.strip():
            pdf.multi_cell(0, 6, line)
        else:
            pdf.ln(2)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_id = generate_random_id()
    safe_category = category.replace(" ", "_").replace("'", "")
    filename = f"{safe_category}_{timestamp}_{random_id}.pdf"

    filepath = output_dir / filename
    pdf.output(str(filepath))

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Generate realistic email PDFs for testing")
    parser.add_argument("--count", type=int, default=10, help="Number of PDFs to generate")
    parser.add_argument("--out", type=str, default="dataset/pdf", help="Output directory")
    parser.add_argument("--categories", nargs="+", help="Specific categories to generate (default: all)")

    args = parser.parse_args()

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter categories if specified
    categories_to_use = args.categories if args.categories else list(EMAIL_TEMPLATES.keys())

    # Generate PDFs
    generated = []
    for i in range(args.count):
        category = random.choice(categories_to_use)
        if category not in EMAIL_TEMPLATES:
            print(f"Warning: Category '{category}' not found. Skipping.")
            continue

        template = random.choice(EMAIL_TEMPLATES[category])

        try:
            filepath = create_email_pdf(category, template, output_dir)
            generated.append(filepath)
            print(f"[{i+1}/{args.count}] Generated: {filepath.name}")

            # Small delay to ensure unique timestamps
            time.sleep(0.1)
        except Exception as e:
            print(f"Error generating PDF for {category}: {e}")

    print(f"\n✅ Successfully generated {len(generated)} PDFs in {output_dir}")
    print("\nCategories distribution:")
    category_counts = {}
    for fp in generated:
        cat = fp.stem.split('_')[0].replace("_", " ")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    for cat, count in sorted(category_counts.items()):
        print(f"  - {cat}: {count}")


if __name__ == "__main__":
    main()
