import json
from pathlib import Path
from classymail.core.paths import project_root

DATA_FILE = Path(project_root()) / "data" / "settings.json"

DEFAULT_CATEGORIES = [
    {
        "name": "Attestation habitation",
        "slug": "attestation_habitation",
        "description": "Documents certifiant la résidence ou l'assurance habitation",
        "exclusions": "Ne concerne pas les attestations professionnelles ou véhicules"
    },
    {
        "name": "Attestation scolaire",
        "slug": "attestation_scolaire",
        "description": "Documents liés à la scolarité et à l'éducation",
        "exclusions": "Ne concerne pas les attestations de travail ou formation professionnelle"
    },
    {
        "name": "Relevé de compte",
        "slug": "releve_compte",
        "description": "Relevés bancaires et transactions financières",
        "exclusions": "Ne concerne pas les factures ou contrats"
    },
    {
        "name": "Dommages électriques",
        "slug": "dommages_electriques",
        "description": "Sinistres liés aux équipements électriques",
        "exclusions": "Ne concerne pas les dommages structurels ou naturels"
    },
    {
        "name": "Événements naturels",
        "slug": "evenements_naturels",
        "description": "Sinistres causés par des phénomènes naturels (inondations, tempêtes, etc.)",
        "exclusions": "Ne concerne pas les dommages causés par l'homme ou les équipements"
    }
]

DEFAULT_SETTINGS = {
    "cost_overrides": {},
    "categories": DEFAULT_CATEGORIES,
    "processing_strategy": "standard",  # standard | reasoning | vision
    "ai_model": "phi4",
    "adversarial_model": None, # Default comparison model
    "finetune_min_examples": 50,
    "ocr_max_attempts": 3,
    "email_preprocessing": {
        "enabled": True,
        "include_subject": True,
        "extract_last_conversation": True,
        "detect_pii": False,  # Enable PII detection
        "pii_detection_method": "llm",  # llm | azure_language | both
    }
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
            data["finetune_min_examples"] = 50
        if "ocr_max_attempts" not in data:
            data["ocr_max_attempts"] = 3
        else:
            data["ocr_max_attempts"] = _sanitize_ocr_attempts(data["ocr_max_attempts"])
        if "email_preprocessing" not in data:
            data["email_preprocessing"] = DEFAULT_SETTINGS["email_preprocessing"].copy()
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
            settings["finetune_min_examples"] = 50

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
            ep.setdefault("detect_pii", False)

    DATA_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")

async def save_settings_async(settings: dict, clients=None):
    save_settings(settings)
    try:
        if clients and getattr(clients, "cosmos_container", None):
            doc = {"id": "settings", **settings}
            await clients.cosmos_container.upsert_item(doc)
    except Exception:
        pass

def get_categories_prompt_text() -> str:
    """Generate professional prompt text for categories with definitions and exclusions."""
    settings = load_settings()
    cats = settings.get("categories", DEFAULT_CATEGORIES)
    lines = []
    for idx, c in enumerate(cats, 1):
        name = c.get('name', '')
        desc = c.get('description', '')
        excl = c.get('exclusions', '')

        # Professional format without emojis
        if desc and excl:
            lines.append(f"{idx}. {name}")
            lines.append(f"   DÉFINITION: {desc}")
            lines.append(f"   EXCLUSIONS: {excl}")
        elif desc:
            lines.append(f"{idx}. {name}: {desc}")
        else:
            lines.append(f"{idx}. {name}")
    return "\n".join(lines)
