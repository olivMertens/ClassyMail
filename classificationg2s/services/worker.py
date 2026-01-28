from __future__ import annotations

import asyncio
import json
import time
import logging
from datetime import datetime, timezone

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from azure.servicebus.aio import AutoLockRenewer
from classificationg2s.services.azure_clients import Clients
from classificationg2s.services.pipeline import run_classification_pipeline
from classificationg2s.services.repository import save_to_cosmos
from classificationg2s.models import EmailRecord, OCRFailed
from classificationg2s.services.azure_clients import blob_id_from_url
from classificationg2s.services.messages import extract_blob_url

logger = logging.getLogger(__name__)


async def worker_loop_forever(*, queue_name: str, get_settings, clients: Clients):
    if not clients.sb_client:
        raise RuntimeError("Service Bus client not initialized")

    concurrency = clients.concurrency_limit
    auto_lock_renewer = AutoLockRenewer(max_lock_renewal_duration=600)
    while True:
        try:
            async with clients.sb_client.get_queue_receiver(
                queue_name=queue_name, max_wait_time=5, auto_lock_renewer=auto_lock_renewer
            ) as receiver:
                async for msg in receiver:
                    async with concurrency:
                        await handle_queue_message(receiver, msg, get_settings=get_settings, clients=clients)
        except asyncio.CancelledError:
            break
        except Exception as ex:
            logger.exception("Worker loop error: %s", ex)
            await asyncio.sleep(2)


class ProcessingTimer:
    def __init__(self):
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end_time = time.perf_counter()

    @property
    def duration_ms(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000.0
        return 0.0

async def handle_queue_message(receiver, msg, *, get_settings, clients: Clients):
    body_bytes = b"".join([b for b in msg.body])
    message_id = getattr(msg, "message_id", None)
    delivery_count = getattr(msg, "delivery_count", None)
    logger.info("[msg:%s] Received (delivery=%s, bytes=%s)", message_id, delivery_count, len(body_bytes))

    try:
        payload = json.loads(body_bytes.decode())
    except Exception:
        payload = {"blob_url": None, "raw": body_bytes.decode(errors="ignore")}

    blob_url = extract_blob_url(payload)
    if not blob_url:
        logger.warning("[msg:%s] No blob_url found in message, dead-lettering", message_id)
        await receiver.dead_letter_message(msg, reason="NoBlobUrl")
        return

    logger.info("[msg:%s] → Processing blob: %s", message_id, blob_url)

    try:
        with ProcessingTimer() as timer:
            logger.info("[msg:%s] Starting classification pipeline", message_id)
            result = await run_classification_pipeline(blob_url, settings=get_settings(), clients=clients)
            logger.info("[msg:%s] Pipeline completed in %.0fms", message_id, timer.duration_ms)

        result.processing_time_ms = timer.duration_ms
        logger.info("[msg:%s] Saving result to Cosmos DB (ID: %s)", message_id, result.id)
        await save_to_cosmos(result)
        logger.info("[msg:%s] ✓ Processing complete for %s", message_id, result.id)
        await receiver.complete_message(msg)
    except OCRFailed as ex:
        error_stage = None
        error_text = str(ex)
        processing_log = getattr(ex, "processing_log", None)
        if error_text.startswith("stage="):
            try:
                error_stage = error_text.split(":", 1)[0].split("=", 1)[1].strip()
            except Exception:
                error_stage = None

        if processing_log:
            logger.error("[msg:%s] OCR processing_log: %s", message_id, processing_log)

        record = EmailRecord(
            id=blob_id_from_url(blob_url),
            file_url=blob_url,
            status="ERROR",
            error=error_text,
            error_stage=error_stage,
            updated_at=datetime.now(timezone.utc),
            processing_log=processing_log,
        )
        try:
            await save_to_cosmos(record)
        except Exception as persist_ex:
            logger.exception("[msg:%s] Failed to persist error record: %s", message_id, persist_ex)

        reason = "ProcessingFailed"
        if error_stage == "download":
            reason = "CorruptedOrUnreadablePDF"
        logger.error("[msg:%s] Processing failed for %s: %s", message_id, blob_url, error_text)
        await receiver.dead_letter_message(msg, reason=reason, error_description=error_text)
    except Exception as ex:
        logger.exception("[msg:%s] Processing failed for %s", message_id, blob_url)

        # Persist error state to Cosmos for visibility in Dashboard
        try:
            record = EmailRecord(
                id=blob_id_from_url(blob_url),
                file_url=blob_url,
                status="ERROR",
                error=str(ex),
                error_stage="worker_unhandled",
                updated_at=datetime.now(timezone.utc),
                processing_log=[{"ts": datetime.now(timezone.utc).isoformat(), "stage": "worker", "event": "unhandled_exception", "details": str(ex)}]
            )
            await save_to_cosmos(record)
        except Exception:
            # If saving to Cosmos fails (e.g. connectivity), we fall back to DLQ only
            logger.warning("[msg:%s] Could not persist error record to Cosmos", message_id)

        reason = None
        if isinstance(ex, (ClientAuthenticationError, ResourceNotFoundError)):
            reason = "AuthOrResourceError"
        elif isinstance(ex, HttpResponseError):
            status_code = getattr(ex, "status_code", None)
            if status_code in (401, 403):
                reason = "AuthError"
            elif status_code == 404:
                reason = "ModelNotFound"
        if reason:
            await receiver.dead_letter_message(msg, reason=reason, error_description=str(ex))
        else:
            await receiver.abandon_message(msg)
