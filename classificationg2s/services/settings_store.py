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
    "categories": DEFAULT_CATEGORIES
}

def load_settings() -> dict:
    if not DATA_FILE.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        # Merge with defaults to ensure keys exist
        if "categories" not in data:
            data["categories"] = DEFAULT_CATEGORIES
        if "cost_overrides" not in data:
            data["cost_overrides"] = {}
        return data
    except Exception:
        return DEFAULT_SETTINGS.copy()

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

    DATA_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")

def get_categories_prompt_text() -> str:
    settings = load_settings()
    cats = settings.get("categories", DEFAULT_CATEGORIES)
    lines = []
    for idx, c in enumerate(cats, 1):
        desc = f" ({c['description']})" if c.get('description') else ""
        lines.append(f"{idx}. {c['name']}{desc}")
    return "\n".join(lines)
