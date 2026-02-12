import json
from pathlib import Path
from classymail.core.paths import project_root

DATA_FILE = Path(project_root()) / "data" / "settings.json"

DEFAULT_CATEGORIES = [
    {
        "name": "Attestation habitation",
        "slug": "ddedoc_habitation",
        "description": "- Demande d'attestation habitation pour son logement résidentiel.\n- Demande d'attestation habitation pour son logement résidentiel locatif.\n- Demande d'attestation habitation pour son local ou lieu professionnel.\n- Demande d'attestation habitation pour un logement étudiant.",
        "exclusions": "- Demande d'attestation habitation avec pour motif le télétravail.\n- Demande d'attestation habitation pour une location de salle de fête.\n- Demande d'attestation habitation avec pour motif une résidence de villégiature (location saisonnière avec une date de fin, séjour temporaire avec mention d'une durée ou d'une date de fin).\n- Demande d'attestation ne portant pas sur l'assurance habitation.\n- Autres demandes.\n- Demande vague de document"
    },
    {
        "name": "Relevé de compte",
        "slug": "ddedoc_relevecompte",
        "description": "Demande de document Relevé de compte",
        "exclusions": ""
    },
    {
        "name": "Attestation scolaire",
        "slug": "ddedoc_scolaire",
        "description": "Demande de doc attestation scolaire",
        "exclusions": ""
    },
    {
        "name": "Dommages électriques",
        "slug": "dommageselectriques",
        "description": "L'assuré déclare qu'un de ses biens a des problèmes de surtension, court-circuit, court-jus\nL'assuré déclare qu'un de ses biens a des problèmes de coupure électrique, coupure de courant\nL'assuré parle d'avarie sur le réseau, enedis, ERDF\nRenvoi d'Enedis vers l'assureur\nL'assuré déclare des dégâts suite à la chute de la foudre\nL'assuré déclare une situation où il n'y a pas de dommages visuels, mais où le matériel ne fonctionne plus.\nDommage lié au remplacement de la platine, de pièces ou de composants électriques.\nRebobinage du moteur.",
        "exclusions": "Problème électrique sur un véhicule\nIncendie quel que soit la cause\nDommages suite à une tempête.\nSouscription d'un contrat dommages électriques (et d'un contrat sinistre de manière générale)."
    },
    {
        "name": "Événements naturels",
        "slug": "evenementsnaturels",
        "description": "L'assuré est victime d'inondations, tempêtes, grêles, vent, sécheresse, éboulement, tornade, ouragan.\nL'assuré parle d'intempérie.\nLe client vient d'être victime d'une catastrophe naturelles (arrêté de catastrophe naturelle) : d'inondations, tempêtes, vent, sécheresse, éboulement.\nL'habitation du client a été touchée suite à un orage\nLe client vient d'être victime d'un « Dommage de mouilles », infiltration suite à une tempête.",
        "exclusions": "Souscription à un contrat d'assurance intempéries.\nSouscription à un contrat d'assurance événements naturels.\nDéclaration d'un sinistre incendie.\nL'assuré est victime d'inondations, tempêtes, grêles, vent, sécheresse, éboulement sur sa voiture."
    }
]

DEFAULT_SETTINGS = {
    "cost_overrides": {},
    "categories": DEFAULT_CATEGORIES,
    "processing_strategy": "standard",  # standard | reasoning | vision
    "ai_model": "phi4",
    "adversarial_model": None, # Default comparison model
    "finetune_min_examples": 5,
    "ocr_max_attempts": 3,
    "email_preprocessing": {
        "enabled": True,
        "include_subject": True,
        "extract_last_conversation": True,
        "detect_pii": True,  # Enable PII detection by default (name, email, phone, address extraction)
        "pii_detection_method": "llm",  # llm | azure_language | both
        "pii_llm_model": "auto",  # auto (reuse ai_model) | gpt-4o-mini | gpt-5-nano | ...
    },
    "g2s_export": {
        "unclassified_label": "autre",  # Label shown in CSV when no category matches
        "show_model": True,              # Include MODELE column in enriched CSV
        "show_pii": True,                # Include PII_DETECTE and PII_TYPES columns
        "show_justification": True,      # Include JUSTIFICATION column
        "show_visual_proofs": True,       # Include PREUVES_VISUELLES column
        "show_quality": True,             # Include QUALITE column
        "show_time": True,               # Include TEMPS_S column
    },
    "ai_assessment_model": "gpt-4.1-nano",  # Model for category assessment (fast non-reasoning preferred)
}
PROCESSING_STRATEGY_ENV = "PROCESSING_STRATEGY"

def _sanitize_ocr_attempts(val) -> int:
    try:
        v = int(val)
    except Exception:
        return 3
    if v < 1:
        v = 1
    if v > 10:
        v = 10
    return v

def _apply_env_overrides(settings: dict) -> dict:
    import os
    env_strategy = os.getenv(PROCESSING_STRATEGY_ENV)
    if env_strategy in ("standard", "reasoning", "vision"):
        settings["processing_strategy"] = env_strategy
    return settings

def _migrate_categories(categories: list) -> list:
    """Migrate old categories to new format with slug and exclusions."""
    migrated = []
    for c in categories:
        if isinstance(c, dict):
            name = c.get("name", "")
            # Auto-generate slug if missing
            if "slug" not in c:
                slug = name.lower().replace(" ", "_").replace("é", "e").replace("è", "e").replace("à", "a")
                slug = "".join(ch for ch in slug if ch.isalnum() or ch == "_")
            else:
                slug = c["slug"]

            migrated.append({
                "name": name,
                "slug": slug,
                "description": c.get("description", ""),
                "exclusions": c.get("exclusions", "")
            })
    return migrated

def load_settings() -> dict:
    if not DATA_FILE.exists():
        return _apply_env_overrides(DEFAULT_SETTINGS.copy())
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        # Merge with defaults to ensure keys exist
        if "categories" not in data:
            data["categories"] = DEFAULT_CATEGORIES
        else:
            # Migrate old categories to new format
            data["categories"] = _migrate_categories(data["categories"])
        if "cost_overrides" not in data:
            data["cost_overrides"] = {}
        if "processing_strategy" not in data:
            data["processing_strategy"] = "standard"
        if "ai_model" not in data:
            data["ai_model"] = "phi4"
        if "adversarial_model" not in data:
            data["adversarial_model"] = None
        if "finetune_min_examples" not in data:
            data["finetune_min_examples"] = 5
        if "ocr_max_attempts" not in data:
            data["ocr_max_attempts"] = 3
        else:
            data["ocr_max_attempts"] = _sanitize_ocr_attempts(data["ocr_max_attempts"])
        if "email_preprocessing" not in data or not isinstance(data["email_preprocessing"], dict):
            data["email_preprocessing"] = DEFAULT_SETTINGS["email_preprocessing"].copy()
        if "g2s_export" not in data or not isinstance(data["g2s_export"], dict):
            data["g2s_export"] = DEFAULT_SETTINGS["g2s_export"].copy()
        if "ai_assessment_model" not in data:
            data["ai_assessment_model"] = "gpt-4.1-nano"
        return _apply_env_overrides(data)
    except Exception:
        return _apply_env_overrides(DEFAULT_SETTINGS.copy())

async def load_settings_async(clients=None) -> dict:
    try:
        if clients and getattr(clients, "cosmos_container", None):
            item = await clients.cosmos_container.read_item(item="settings", partition_key="settings")
            if item:
                s = item.copy()
                s.pop("id", None)
                return _apply_env_overrides(s)
    except Exception:
        pass
    return load_settings()

def save_settings(settings: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Sanitize categories
    if "categories" in settings:
        clean_cats = []
        for c in settings["categories"]:
            # Sanitize: keep name/slug/description/exclusions
            name = str(c.get("name", "")).strip()
            slug = str(c.get("slug", "")).strip()
            desc = str(c.get("description", "")).strip()
            excl = str(c.get("exclusions", "")).strip()

            # Auto-generate slug if missing
            if not slug and name:
                slug = name.lower().replace(" ", "_").replace("é", "e").replace("è", "e").replace("à", "a")
                slug = "".join(ch for ch in slug if ch.isalnum() or ch == "_")

            if name and slug:
                clean_cats.append({
                    "name": name,
                    "slug": slug,
                    "description": desc,
                    "exclusions": excl
                })
        settings["categories"] = clean_cats

    # Sanitize strategy
    if "processing_strategy" in settings:
        if settings["processing_strategy"] not in ("standard", "reasoning", "vision"):
            settings["processing_strategy"] = "standard"

    # Sanitize models
    if "ai_model" in settings:
        settings["ai_model"] = str(settings["ai_model"])
    if "adversarial_model" in settings:
        if settings["adversarial_model"] in (None, "", "none"):
            settings["adversarial_model"] = None
        else:
            settings["adversarial_model"] = str(settings["adversarial_model"])

    # Sanitize finetune_min_examples
    if "finetune_min_examples" in settings:
        try:
            val = int(settings["finetune_min_examples"])
            if val < 5:
                val = 5
            settings["finetune_min_examples"] = val
        except (ValueError, TypeError):
            settings["finetune_min_examples"] = 5

    if "ocr_max_attempts" in settings:
        settings["ocr_max_attempts"] = _sanitize_ocr_attempts(settings["ocr_max_attempts"])

    # Sanitize email_preprocessing
    if "email_preprocessing" not in settings:
        settings["email_preprocessing"] = DEFAULT_SETTINGS["email_preprocessing"].copy()
    else:
        ep = settings["email_preprocessing"]
        if not isinstance(ep, dict):
            settings["email_preprocessing"] = DEFAULT_SETTINGS["email_preprocessing"].copy()
        else:
            # Ensure all keys exist
            ep.setdefault("enabled", True)
            ep.setdefault("include_subject", True)
            ep.setdefault("extract_last_conversation", True)
            ep.setdefault("detect_pii", True)  # PII detection enabled by default
            ep.setdefault("pii_llm_model", "auto")

    # Sanitize g2s_export
    if "g2s_export" not in settings:
        settings["g2s_export"] = DEFAULT_SETTINGS["g2s_export"].copy()
    else:
        ge = settings["g2s_export"]
        if not isinstance(ge, dict):
            settings["g2s_export"] = DEFAULT_SETTINGS["g2s_export"].copy()
        else:
            ge.setdefault("unclassified_label", "autre")
            ge.setdefault("show_model", True)
            ge.setdefault("show_pii", True)
            ge.setdefault("show_justification", True)
            ge.setdefault("show_visual_proofs", True)
            ge.setdefault("show_quality", True)
            ge.setdefault("show_time", True)

    DATA_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")

async def save_settings_async(settings: dict, clients=None):
    save_settings(settings)
    try:
        if clients and getattr(clients, "cosmos_container", None):
            doc = {"id": "settings", **settings}
            await clients.cosmos_container.upsert_item(doc)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to persist settings to Cosmos: %s", e)

def _build_categories_prompt(cats: list) -> str:
    """Build prompt text from a list of category dicts.

    Handles empty list, missing fields, and empty exclusions gracefully.
    """
    if not cats:
        return "(Aucune catégorie configurée / No categories configured)"

    lines: list[str] = []
    idx = 0
    for c in cats:
        name = (c.get('name') or '').strip()
        if not name:
            continue
        idx += 1
        desc = (c.get('description') or '').strip()
        excl = (c.get('exclusions') or '').strip()

        # Always use structured format so the LLM sees consistent blocks
        lines.append(f"{idx}. {name}")
        lines.append(f"   DÉFINITION: {desc if desc else '(non définie)'}")
        lines.append(f"   EXCLUSIONS: {excl if excl else '(aucune)'}")

    return "\n".join(lines) if lines else "(Aucune catégorie configurée / No categories configured)"


def get_categories_prompt_text() -> str:
    """Generate professional prompt text for categories with definitions and exclusions."""
    settings = load_settings()
    cats = settings.get("categories") or []
    return _build_categories_prompt(cats)


async def get_categories_prompt_text_async(clients=None) -> str:
    """Async variant – reads from Cosmos if available, then builds prompt text."""
    settings = await load_settings_async(clients=clients)
    cats = settings.get("categories") or []
    return _build_categories_prompt(cats)
