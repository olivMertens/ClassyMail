from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from classificationg2s.services.azure_clients import Clients
from classificationg2s.services.pipeline import run_classification_pipeline
from classificationg2s.services.repository import save_to_cosmos
from classificationg2s.models import EmailRecord, OCRFailed
from classificationg2s.services.azure_clients import blob_id_from_url


def _extract_blob_url(payload) -> str | None:
    """Extract a blob URL from either:
    - our internal message format: {"blob_url": "https://..."}
    - Event Grid event(s) delivered to Service Bus (EventGrid schema or CloudEvents)
    """
    if isinstance(payload, dict):
        if payload.get("blob_url"):
            return payload["blob_url"]
        # Some producers may already send the Event Grid event as a dict.
        candidates = [payload]
    elif isinstance(payload, list):
        candidates = payload
    else:
        return None

    for ev in candidates:
        if not isinstance(ev, dict):
            continue
        # Event Grid schema
        data = ev.get("data") or {}
        if isinstance(data, dict):
            url = data.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
        # CloudEvents schema
        data = ev.get("data") or {}
        if isinstance(data, dict):
            url = data.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
    return None

async def worker_loop_forever(*, queue_name: str, get_cost_overrides, clients: Clients):
    if not clients.sb_client:
        raise RuntimeError("Service Bus client not initialized")

    concurrency = clients.concurrency_limit
    while True:
        try:
            async with clients.sb_client.get_queue_receiver(queue_name=queue_name, max_wait_time=5) as receiver:
                async for msg in receiver:
                    async with concurrency:
                        await handle_queue_message(receiver, msg, get_cost_overrides=get_cost_overrides, clients=clients)
        except asyncio.CancelledError:
            break
        except Exception as ex:
            print(f"[worker] Error: {ex}")
            await asyncio.sleep(2)


async def handle_queue_message(receiver, msg, *, get_cost_overrides, clients: Clients):
    body_bytes = b"".join([b for b in msg.body])
    try:
        payload = json.loads(body_bytes.decode())
    except Exception:
        payload = {"blob_url": None, "raw": body_bytes.decode(errors="ignore")}

    blob_url = _extract_blob_url(payload)
    if not blob_url:
        await receiver.dead_letter_message(msg, reason="No blob_url in message")
        return

    try:
        result = await run_classification_pipeline(blob_url, cost_overrides=get_cost_overrides(), clients=clients)
        await save_to_cosmos(result)
        await receiver.complete_message(msg)
    except OCRFailed as ex:
        # Persist a visible ERROR record so the UI can show stage-1 failures (corrupted PDF, download errors, etc.)
        error_stage = None
        error_text = str(ex)
        if error_text.startswith("stage="):
            try:
                error_stage = error_text.split(":", 1)[0].split("=", 1)[1].strip()
            except Exception:
                error_stage = None

        record = EmailRecord(
            id=blob_id_from_url(blob_url),
            file_url=blob_url,
            status="ERROR",
            error=error_text,
            error_stage=error_stage,
            updated_at=datetime.now(timezone.utc),
            processing_log=getattr(ex, "processing_log", None),
        )
        try:
            await save_to_cosmos(record)
        except Exception as persist_ex:
            print(f"[worker] Failed to persist error record: {persist_ex}")

        reason = "ProcessingFailed"
        if error_stage == "download":
            reason = "CorruptedOrUnreadablePDF"
        print(f"[worker] Processing failed for {blob_url}: {error_text}")
        await receiver.dead_letter_message(msg, reason=reason, error_description=error_text)
    except Exception as ex:
        print(f"[worker] Processing failed for {blob_url}: {ex}")
        await receiver.abandon_message(msg)
