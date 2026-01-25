"""Generate dummy PDFs for dataset testing (hardcore / chaos-mode).

Creates noisy, realistic-looking (but fake) email-like PDFs with mixed language, slang,
typos, incomplete info, multi-topic confusion, and occasional user details (fake name,
address, phone). Use ONLY for testing.

By default this generates ~75 PDFs and tries to make bodies long (≈300 words) to
stress OCR + classification.

Usage:
    python scripts/generate_dummy_pdfs.py --count 75
    python scripts/generate_dummy_pdfs.py --count 100 --out dataset/pdf

Optional Azure OpenAI generation/expansion:
    set AZURE_OPENAI_ENDPOINT=...
    set AZURE_OPENAI_API_KEY=...
    set AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
    python scripts/generate_dummy_pdfs.py --count 25 --use-aoai --require-aoai

Notes:
- Requires: fpdf2 (module name: fpdf)
- Filenames include the category for ground-truth control.
- PDFs are encoded in latin-1 with replacements (simulates legacy pipelines).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import string
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

try:
    from fpdf import FPDF
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: fpdf2 (module 'fpdf'). Install with: pip install fpdf2") from exc


def load_env_from_file(path: str = "secrets.env", *, override: bool = False) -> None:
    """Minimal env loader for KEY=VALUE lines (ignores comments/blank lines)."""

    p = Path(path)
    if not p.exists():
        return

    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class SeedEmail:
    text: str
    category: str


FIRST_NAMES = [
    "Jean",
    "Marie",
    "Camille",
    "Thomas",
    "Sophie",
    "Lucas",
    "Emma",
    "Hugo",
    "Chloé",
    "Louis",
    "Manon",
    "Nicolas",
    "Julie",
    "Antoine",
    "Léa",
]

LAST_NAMES = [
    "Martin",
    "Bernard",
    "Dubois",
    "Thomas",
    "Robert",
    "Richard",
    "Petit",
    "Durand",
    "Leroy",
    "Moreau",
    "Simon",
    "Laurent",
    "Lefebvre",
    "Michel",
    "Garcia",
]

STREETS = [
    "Rue de la Paix",
    "Avenue Victor Hugo",
    "Boulevard Saint-Germain",
    "Rue Nationale",
    "Rue du Général Leclerc",
    "Avenue de la République",
    "Rue des Lilas",
    "Rue Pasteur",
]

CITIES = [
    ("Paris", "75015"),
    ("Lyon", "69003"),
    ("Marseille", "13008"),
    ("Toulouse", "31000"),
    ("Nantes", "44000"),
    ("Lille", "59000"),
    ("Bordeaux", "33000"),
]

SUBJECTS = [
    "Question",
    "Urgent",
    "Demande",
    "Problème",
    "Hello",
    "Info",
    "Re:",
    "No Subject",
    "Assurance",
]


SEED_EMAILS: list[SeedEmail] = [
    SeedEmail("Hello, I need my home insurance certificate for my landlord. ASAP please.", "habitation"),
    SeedEmail(
        "Wesh l'équipe, mon proprio me met la pression pour l'attestation appart. Vous pouvez m'envoyer ça ? Cimer.",
        "habitation",
    ),
    SeedEmail("bjr il me fo le papier pr la mizon pour le bailleur mrc", "habitation"),
    SeedEmail("Hola, necesito el certificado de seguro de hogar para mi nuevo piso en Paris.", "habitation"),
    SeedEmail("Je voudrais le paperasse pour la baraque. L'attestation là.", "habitation"),

    SeedEmail("Hi, school starts tomorrow. Need insurance proof for my kid.", "scolaire"),
    SeedEmail("slt c pour lecol de mon gamin il veu lassurance", "scolaire"),
    SeedEmail("Yo, faut l'attest pour le p'tit, sinon il peut pas faire la cantine. Envoie ça stp.", "scolaire"),
    SeedEmail("Please send certificate school liability. Urgent.", "scolaire"),
    SeedEmail("Attestation périscolaire + centre aéré demandée.", "scolaire"),

    SeedEmail("C'est quoi ce binz ? Vous m'avez prélevé deux fois ! Rendez l'argent !", "releve_compte"),
    SeedEmail("I don't understand the last payment regarding my contract. Please send statement.", "releve_compte"),
    SeedEmail("jcomprend R a vos comptes la, envoyez le relevé detaillé svp", "releve_compte"),
    SeedEmail("Wesh vous m'avez sbeul mon compte ou quoi ? C'est quoi ces 50 balles en moins ?", "releve_compte"),
    SeedEmail("Need invoice for tax purpose. Year 2024.", "releve_compte"),

    SeedEmail("My TV is dead after the storm. Electrical surge I think.", "domm_elec"),
    SeedEmail("Mon ordi a cramé. Y'a eu un éclair et paf, plus rien. Ça puait le grillé.", "domm_elec"),
    SeedEmail("panne de courant pui surtension frigo HS tou la bouffe a la poubel", "domm_elec"),
    SeedEmail("La playstation ne s'allume plus wesh. C'est à cause de l'orage d'hier soir.", "domm_elec"),
    SeedEmail("Bonjour, suite coupure Enedis, volets roulants bloqués et moteur portail HS.", "domm_elec"),

    SeedEmail("It was raining like crazy and now water is in the basement.", "evt_naturel"),
    SeedEmail("La toiture a pris cher avec le vent. Y'a des tuiles partout dans le jardin.", "evt_naturel"),
    SeedEmail("innondation cave c la cata, envoyez un expert vite", "evt_naturel"),
    SeedEmail("Tempête de ouf hier, mon velux est explosé.", "evt_naturel"),
    SeedEmail("Gros grêlons sur la véranda. Impact visible.", "evt_naturel"),

    SeedEmail(
        "Yo, ma télé a grillé (orage) et il me faut l'attestation pour le foot du petit. Tu gères ?",
        "domm_elec_scolaire",
    ),
    SeedEmail(
        "Hello, I moved out. Need attestation habitation for new place and please check why I paid 20 euros more this month.",
        "habitation_releve",
    ),
    SeedEmail("c'est la hess, on a été inondé et en plus mon frigo marche plus. help.", "evt_naturel_domm_elec"),

    SeedEmail("Vends canapé cuir bon état, venir chercher sur place.", "hors_sujet"),
    SeedEmail("Fwd: Recette Crêpes Chandeleur", "hors_sujet"),
    SeedEmail("Please unsubscribe me from this list.", "hors_sujet"),
    SeedEmail("mdr t'as vu la vidéo du chat ?", "hors_sujet"),
    SeedEmail("kjsdhf kjsdhf ksjdhf", "incompréhensible"),

    SeedEmail("Quel est le prix pour assurer une BMW Série 3 ?", "auto"),
    SeedEmail("J'ai mal aux dents, ma mutuelle couvre ça ?", "sante"),
    SeedEmail("Mon fils a cassé la vitre du voisin avec son ballon.", "resp_civile"),
]


def _digits(n: int) -> str:
    return "".join(random.choice(string.digits) for _ in range(n))


def generate_phone_fr() -> str:
    prefix = random.choice(["06", "07"])
    rest = _digits(8)
    return " ".join([prefix, rest[0:2], rest[2:4], rest[4:6], rest[6:8]])


def generate_address() -> dict:
    city, zip_code = random.choice(CITIES)
    return {
        "street_number": str(random.randint(1, 220)),
        "street": random.choice(STREETS),
        "zip": zip_code,
        "city": city,
    }


def make_identity() -> dict:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    addr = generate_address()
    email = (
        f"{first.lower()}.{last.lower()}@example.fr"
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
    )
    return {
        "first": first,
        "last": last,
        "email": email,
        "phone": generate_phone_fr(),
        "address": addr,
    }


def _maybe_broken(s: str) -> str:
    if random.random() < 0.25:
        s = s.replace("'", " ")
    if random.random() < 0.20:
        s = s.replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a").replace("ô", "o")
    if random.random() < 0.15:
        s = re.sub(r"\s+", " ", s)
    if random.random() < 0.10:
        s = s.lower()
    return s


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))


def _noise_blocks(identity: dict) -> list[str]:
    addr = identity["address"]
    blocks: list[str] = []

    blocks.append(
        """
Mes coordonnées (si besoin):
Nom/Prénom: {first} {last}
Téléphone: {phone}
Adresse: {num} {street}, {zip} {city}
""".strip().format(
            last=identity["last"],
            first=identity["first"],
            phone=identity["phone"],
            num=addr["street_number"],
            street=addr["street"],
            zip=addr["zip"],
            city=addr["city"],
        )
    )

    blocks.append("Pour un éventuel remboursement, je peux fournir un RIB sur demande.")

    blocks.append(
        """
Historique (copié/collé):
> Bonjour,
> merci de traiter ma demande au plus vite.
> j'ai deja relancé 2 fois...
""".strip()
    )

    blocks.append(
        """
Fwd: [Ticket] 2026-01 - suivi
Pièce jointe manquante ? je sais pas si vous l'avez reçu.
Merci.
""".strip()
    )

    blocks.append(
        """
PS: je suis joignable entre 12h et 14h. sinon mail.
PPS: si besoin je peux vous envoyer mon RIB (sur demande).
""".strip()
    )

    return blocks


def build_noisy_email_text(seed: SeedEmail, identity: dict, target_words: int) -> tuple[str, str, str]:
    sender_local = random.choice(
        [
            f"{identity['first'].lower()}.{identity['last'].lower()}",
            "customer",
            "toto",
            "bg_du_93",
            "alice.smith",
            "no-reply",
            "xXx_kikou_xXx",
        ]
    )
    sender = f"{sender_local}@{random.choice(['gmail.com', 'outlook.com', 'free.fr', 'wanadoo.fr', 'example.fr'])}"

    subj_prefix = random.choice(SUBJECTS) if random.random() > 0.2 else ""
    subject_line = f"Subject: {_maybe_broken(subj_prefix)} {random.randint(1, 999)}".strip()
    from_line = f"From: {sender}"

    blocks = [_maybe_broken(seed.text)]

    extra_blocks = _noise_blocks(identity)
    if random.random() < 0.55:
        blocks.extend(["", _maybe_broken(random.choice(extra_blocks))])

    random.shuffle(extra_blocks)
    while _word_count("\n\n".join(blocks)) < target_words:
        if random.random() < 0.80:
            blocks.append("")
            blocks.append(_maybe_broken(random.choice(extra_blocks)))
        if random.random() < 0.35:
            blocks.append(_maybe_broken(seed.text))

    signature = random.choice(
        [
            f"Cdt,\n{identity['first']} {identity['last']}",
            f"merci\n{identity['first']}",
            f"Sent from my iPhone\n{identity['first']}",
            f"--\n{identity['first']} {identity['last']}\n{identity['phone']}",
        ]
    )
    blocks.append("")
    blocks.append(_maybe_broken(signature))

    body = "\n".join(blocks)
    return from_line, subject_line, body


async def aoai_variation(prompt: str, deployment: str) -> Optional[str]:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not endpoint:
        return None

    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")
    url = endpoint.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    else:
        try:
            from azure.identity.aio import DefaultAzureCredential
        except Exception:
            return None

        scope = os.getenv("AZURE_OPENAI_SCOPE", "https://cognitiveservices.azure.com/.default")
        credential = DefaultAzureCredential()
        try:
            token = await credential.get_token(scope)
        except Exception:
            return None
        finally:
            try:
                await credential.close()
            except Exception:
                pass

        headers["Authorization"] = f"Bearer {token.token}"

    body = {
        "temperature": 0.9,
        "max_tokens": 1400,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate noisy, realistic email bodies for an insurance classifier dataset. "
                    "Style constraints: mix FR/EN/ES sometimes, slang/typos/SMS abbreviations sometimes, "
                    "may include quoted replies, forwarded markers, and incomplete punctuation. "
                    "If identity/contact lines are provided, keep them exactly as-is. "
                    "Do NOT invent real personal data; only use the fake identity provided in the prompt. "
                    "Never include full banking coordinates (IBAN/BIC/RIB numbers). If reimbursement is mentioned, "
                    "use a generic sentence like 'RIB disponible sur demande'."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    timeout_s = float(os.getenv("AZURE_OPENAI_TIMEOUT", "30"))
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, headers=headers, content=json.dumps(body).encode("utf-8"))
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content")


def write_pdf(text: str, out_path: Path) -> None:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    def _break_long_tokens(s: str, max_token_len: int = 60) -> str:
        parts: list[str] = []
        for token in re.split(r"(\s+)", s):
            if not token or token.isspace():
                parts.append(token)
                continue
            if len(token) <= max_token_len:
                parts.append(token)
                continue
            chunks = [token[i : i + max_token_len] for i in range(0, len(token), max_token_len)]
            parts.append(" ".join(chunks))
        return "".join(parts)

    for line in text.splitlines():
        try:
            pdf.set_x(pdf.l_margin)
        except Exception:
            pass

        usable_width = float(getattr(pdf, "w", 210)) - float(getattr(pdf, "l_margin", 15)) - float(getattr(pdf, "r_margin", 15))
        safe = (
            line.replace("’", "'")
            .replace("“", '"')
            .replace("”", '"')
            .encode("latin-1", errors="replace")
            .decode("latin-1")
        )
        safe = _break_long_tokens(safe)
        try:
            pdf.multi_cell(usable_width, 8, safe)
        except Exception:
            try:
                spaced = " ".join(list(safe))
                pdf.multi_cell(usable_width, 8, spaced)
            except Exception:
                pdf.multi_cell(usable_width, 8, "[line omitted: rendering error]")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))


async def main() -> int:
    load_env_from_file("secrets.env")

    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=75, help="Number of PDFs to generate (recommended: 50-100)")
    parser.add_argument("--out", type=str, default="dataset_emails_hardcore", help="Output folder")
    parser.add_argument(
        "--target-words",
        type=int,
        default=300,
        help="Target word count for the email body (approx; default: 300)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument(
        "--use-aoai",
        action="store_true",
        help="Use Azure OpenAI to generate/expand the noisy email body before PDF creation",
    )
    parser.add_argument(
        "--require-aoai",
        action="store_true",
        help="Fail if AOAI generation is unavailable (ensures output is AOAI-generated when --use-aoai)",
    )
    parser.add_argument(
        "--aoai-deployment",
        type=str,
        default=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default="secrets.env",
        help="Env file to load for AOAI settings (default: secrets.env)",
    )
    args = parser.parse_args()

    if args.env_file and args.env_file != "secrets.env":
        load_env_from_file(args.env_file, override=True)

    if args.seed is not None:
        random.seed(args.seed)

    if args.count < 1:
        raise SystemExit("--count must be >= 1")
    if args.target_words < 30:
        raise SystemExit("--target-words too small; use something like 300")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(args.count):
        identity = make_identity()
        seed = random.choice(SEED_EMAILS)
        from_line, subject_line, body = build_noisy_email_text(seed, identity, target_words=args.target_words)

        meta_lines = [
            from_line,
            subject_line if random.random() > 0.05 else "Subject:",
            "",
        ]

        final_body = body
        if args.use_aoai:
            prompt = (
                "Generate a single email body for the category implied by the seed. "
                f"Make it about ~{args.target_words} words. "
                "Keep this seed intent but increase noise and realism. "
                "Write it like a real customer email (no dataset labels, no bullet list of identity). "
                "You MAY include some contact info naturally (e.g., in a signature), but it's optional. "
                "Do NOT include a full street address unless the email explicitly needs it. "
                "Constraint: do NOT include any full IBAN/BIC/RIB numbers anywhere. If reimbursement is needed, say 'RIB disponible sur demande'.\n\n"
                "Optional fake identity context (use sparingly and naturally, or not at all):\n"
                f"- First name: {identity['first']}\n"
                f"- Last name: {identity['last']}\n"
                f"- Email: {identity['email']}\n"
                f"- Phone: {identity['phone']}\n\n"
                "Seed message:\n"
                f"{seed.text}\n\n"
                "Draft (you may rewrite/expand):\n"
                f"{body}"
            )
            variation = await aoai_variation(prompt, deployment=args.aoai_deployment)
            if variation:
                final_body = variation
            elif args.require_aoai:
                raise SystemExit(
                    "AOAI generation was requested (--use-aoai --require-aoai) but no response was generated. "
                    "Check AZURE_OPENAI_ENDPOINT/auth (or API key) and network access."
                )

        full_text = "\n".join(meta_lines) + final_body

        file_name = f"sample_{i+1:03d}_{seed.category}_{int(time.time())}_{uuid.uuid4().hex[:8]}.pdf"
        write_pdf(full_text, out_dir / file_name)

        if args.count <= 3:
            print(str(out_dir / file_name))

    print(f"Generated {args.count} PDFs in {out_dir}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
