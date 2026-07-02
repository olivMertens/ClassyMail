import json
import os
from pathlib import Path
from classymail.core.paths import project_root

DATA_FILE = Path(project_root()) / "data" / "settings.json"

# OCR providers selectable from the UI as the *primary* engine. Document
# Intelligence is intentionally excluded — it remains the universal fallback.
VALID_OCR_PROVIDERS = ("mistral", "content_understanding")

DEFAULT_CATEGORIES = [
    {
        "name": "Billing inquiry",
        "slug": "billing-inquiry",
        "description": "Questions about invoices, payments, charges, refunds, or account balance.",
        "exclusions": "General account questions not related to billing."
    },
    {
        "name": "Technical support",
        "slug": "technical-support",
        "description": "Requests for help with technical issues, product malfunctions, or troubleshooting.",
        "exclusions": ""
    },
    {
        "name": "Account management",
        "slug": "account-management",
        "description": "Requests related to account creation, modification, closure, or profile updates.",
        "exclusions": ""
    },
    {
        "name": "Document request",
        "slug": "document-request",
        "description": "Requests for certificates, statements, certificates, or official documents.",
        "exclusions": ""
    },
    {
        "name": "General inquiry",
        "slug": "general-inquiry",
        "description": "General questions, feedback, or inquiries that do not fit other categories.",
        "exclusions": ""
    }
]

DEFAULT_SETTINGS = {
    "cost_overrides": {},
    "categories": DEFAULT_CATEGORIES,
    "processing_strategy": "standard",  # standard | reasoning | vision
    "default_locale": "en",  # Default output language for classification (en|fr|de|es|it)
    "ai_model": "phi-4",
    "finetune_min_examples": 5,
    "ocr_max_attempts": 3,
    "ocr_provider": os.getenv("OCR_PROVIDER", "mistral"),  # mistral | content_understanding (DI = fallback)
    "email_preprocessing": {
        "enabled": True,
        "include_subject": True,
        "extract_last_conversation": True,
        "detect_pii": True,  # Enable PII detection by default (name, email, phone, address extraction)
        "pii_detection_method": "llm",  # llm | azure_language | both
        "pii_llm_model": "auto",  # auto (reuse ai_model) | gpt-4.1-mini | gpt-5-nano | ...
    },
    "csv_export": {
        "unclassified_label": "unclassified",  # Label shown in CSV when no category matches
        "show_model": True,              # Include MODELE column in enriched CSV
        "show_pii": True,                # Include PII_DETECTE and PII_TYPES columns
        "show_justification": True,      # Include JUSTIFICATION column
        "show_visual_proofs": True,       # Include PREUVES_VISUELLES column
        "show_quality": True,             # Include QUALITE column
        "show_time": True,               # Include TEMPS_S column
        "show_ocr_provider": True,       # Include SOURCE_OCR column (mistral_ocr | document_intelligence)
    },
    "ai_assessment_model": "gpt-4.1-nano",  # Model for category assessment (fast non-reasoning preferred)
    "agentic": {
        "enabled": False,                          # Feature flag (opt-in)
        "orchestrator_model": "gpt-4.1-nano",      # UI-selectable (or "model-router")
        "orchestrator_routing_mode": "balanced",    # balanced | cost | quality (model-router only)
        "orchestrator_model_subset": [],            # Empty = all models; restrict for cost control
        "agent_tier1_model": "gpt-4.1-nano",       # Simple intents
        "agent_tier2_model": "gpt-4.1-mini",       # Ambiguous intents
        "agent_tier3_model": "gpt-4.1",            # Critical intents
        "red_team_model": "gpt-4.1",               # Quality gate model
        "red_team_threshold": 0.7,                 # Min confidence to skip red team
        "red_team_conflict_delta": 0.15,           # Top-2 delta to trigger red team
        "max_parallel_agents": 6,                  # Max agents in fan-out
        "retrieval_mode": "semantic",              # vector | hybrid | semantic
        "search_top_k": 5,                         # RAG docs per agent query
        "reasoning_effort": "none",                # none | low | medium | high (gpt-5 family)
        "enabled_indexes": {},                      # Per-category index toggle: {slug: true/false}. Empty = all enabled
    },
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

def _sanitize_ocr_provider(val) -> str:
    v = str(val or "").strip().lower()
    if v in VALID_OCR_PROVIDERS:
        return v
    env = os.getenv("OCR_PROVIDER", "mistral").strip().lower()
    return env if env in VALID_OCR_PROVIDERS else "mistral"

def _apply_env_overrides(settings: dict) -> dict:
    import os
    env_strategy = os.getenv(PROCESSING_STRATEGY_ENV)
    if env_strategy in ("standard", "reasoning", "vision", "agentic"):
        settings["processing_strategy"] = env_strategy
    return settings


VALID_STRATEGIES = ("standard", "reasoning", "vision", "agentic")

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
            data["ai_model"] = "phi-4"
        if "finetune_min_examples" not in data:
            data["finetune_min_examples"] = 5
        if "ocr_max_attempts" not in data:
            data["ocr_max_attempts"] = 3
        else:
            data["ocr_max_attempts"] = _sanitize_ocr_attempts(data["ocr_max_attempts"])
        data["ocr_provider"] = _sanitize_ocr_provider(data.get("ocr_provider"))
        if "email_preprocessing" not in data or not isinstance(data["email_preprocessing"], dict):
            data["email_preprocessing"] = DEFAULT_SETTINGS["email_preprocessing"].copy()
        if "csv_export" not in data or not isinstance(data["csv_export"], dict):
            data["csv_export"] = DEFAULT_SETTINGS["csv_export"].copy()
        if "ai_assessment_model" not in data:
            data["ai_assessment_model"] = "gpt-4.1-nano"
        if "agentic" not in data or not isinstance(data.get("agentic"), dict):
            data["agentic"] = DEFAULT_SETTINGS["agentic"].copy()
        else:
            # Ensure all agentic keys exist
            for k, v in DEFAULT_SETTINGS["agentic"].items():
                data["agentic"].setdefault(k, v)
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
        if settings["processing_strategy"] not in ("standard", "reasoning", "vision", "agentic"):
            settings["processing_strategy"] = "standard"

    # Sanitize agentic settings
    if "agentic" not in settings:
        settings["agentic"] = DEFAULT_SETTINGS["agentic"].copy()
    elif isinstance(settings["agentic"], dict):
        ag = settings["agentic"]
        for k, v in DEFAULT_SETTINGS["agentic"].items():
            ag.setdefault(k, v)
        if ag.get("orchestrator_routing_mode") not in ("balanced", "cost", "quality"):
            ag["orchestrator_routing_mode"] = "balanced"
        if ag.get("retrieval_mode") not in ("vector", "hybrid", "semantic"):
            ag["retrieval_mode"] = "semantic"
        try:
            ag["red_team_threshold"] = max(0.0, min(1.0, float(ag["red_team_threshold"])))
        except (ValueError, TypeError):
            ag["red_team_threshold"] = 0.7
        try:
            ag["max_parallel_agents"] = max(1, min(10, int(ag["max_parallel_agents"])))
        except (ValueError, TypeError):
            ag["max_parallel_agents"] = 6

    # Sanitize models
    if "ai_model" in settings:
        settings["ai_model"] = str(settings["ai_model"])

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

    settings["ocr_provider"] = _sanitize_ocr_provider(settings.get("ocr_provider"))

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

    # Sanitize csv_export
    if "csv_export" not in settings:
        settings["csv_export"] = DEFAULT_SETTINGS["csv_export"].copy()
    else:
        ge = settings["csv_export"]
        if not isinstance(ge, dict):
            settings["csv_export"] = DEFAULT_SETTINGS["csv_export"].copy()
        else:
            ge.setdefault("unclassified_label", "unclassified")
            ge.setdefault("show_model", True)
            ge.setdefault("show_pii", True)
            ge.setdefault("show_justification", True)
            ge.setdefault("show_visual_proofs", True)
            ge.setdefault("show_quality", True)
            ge.setdefault("show_time", True)
            ge.setdefault("show_ocr_provider", True)

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
        slug = (c.get('slug') or '').strip()
        desc = (c.get('description') or '').strip()
        excl = (c.get('exclusions') or '').strip()

        # Always use structured format so the LLM sees consistent blocks
        lines.append(f"{idx}. {name} (slug: {slug})" if slug else f"{idx}. {name}")
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
