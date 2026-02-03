import json
from pathlib import Path
from classificationg2s.core.paths import project_root

DATA_FILE = Path(project_root()) / "data" / "settings.json"

DEFAULT_CATEGORIES = [
    {"name": "Attestation habitation", "description": ""},
    {"name": "Attestation scolaire", "description": ""},
    {"name": "Relevé de compte", "description": ""},
    {"name": "Dommages électriques", "description": ""},
    {"name": "Événements naturels", "description": ""}
]

DEFAULT_SETTINGS = {
    "cost_overrides": {},
    "categories": DEFAULT_CATEGORIES,
    "processing_strategy": "standard",  # standard | reasoning | vision
    "ai_model": "phi4",
    "adversarial_model": "gpt4.1-nano", # Default comparison model
    "finetune_min_examples": 50,
    "ocr_max_attempts": 3,
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

def load_settings() -> dict:
    if not DATA_FILE.exists():
        return _apply_env_overrides(DEFAULT_SETTINGS.copy())
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        # Merge with defaults to ensure keys exist
        if "categories" not in data:
            data["categories"] = DEFAULT_CATEGORIES
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
            # Simple sanitization: keep only name/desc and ensure they are strings
            name = str(c.get("name", "")).strip()
            desc = str(c.get("description", "")).strip()
            if name:
               clean_cats.append({"name": name, "description": desc})
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
    settings = load_settings()
    cats = settings.get("categories", DEFAULT_CATEGORIES)
    lines = []
    for idx, c in enumerate(cats, 1):
        desc = f" ({c['description']})" if c.get('description') else ""
        lines.append(f"{idx}. {c['name']}{desc}")
    return "\n".join(lines)
