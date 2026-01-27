from __future__ import annotations

from typing import Any, Optional


def extract_blob_url(payload: Any) -> Optional[str]:
    """Extract a blob URL from either:
    - internal format: {"blob_url": "https://..."}
    - Event Grid schema (data.url)
    - CloudEvents schema (data.url)
    """
    if isinstance(payload, dict):
        if payload.get("blob_url"):
            return payload["blob_url"]
        candidates = [payload]
    elif isinstance(payload, list):
        candidates = payload
    else:
        return None

    for ev in candidates:
        if not isinstance(ev, dict):
            continue
        data = ev.get("data") or {}
        if isinstance(data, dict):
            url = data.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
    return None
