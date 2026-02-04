from __future__ import annotations

import asyncio
import json
import os
import time
import logging
from datetime import datetime, timezone
import inspect

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from azure.servicebus.aio import AutoLockRenewer
from classificationg2s.core import config
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

    # Use the semaphore to limit concurrent TASKS, not sequential execution blocks.
    concurrency = clients.concurrency_limit
    # Lock renewal: Default 3600s (1 hour) to handle large PDFs (30+ pages)
    # Configurable via WORKER_LOCK_RENEWAL_DURATION
    lock_renewal_duration = int(os.getenv("WORKER_LOCK_RENEWAL_DURATION", "3600"))
    auto_lock_renewer = AutoLockRenewer(max_lock_renewal_duration=lock_renewal_duration)

    logger.info("Worker started with concurrency limit: %s", concurrency._value if hasattr(concurrency, "_value") else "Unknown")

    active_tasks: set[asyncio.Task] = set()

    while True:
        try:
            async with clients.sb_client.get_queue_receiver(
                queue_name=queue_name,
                # max_wait_time=5, # Removed to prevent receiver closure while tasks are running
                auto_lock_renewer=auto_lock_renewer,
                prefetch_count=10  # Prefetch to allow pipelining
            ) as receiver:
                try:
                    async for msg in receiver:
                        # Wait for a semaphore slot
                        await concurrency.acquire()

                        # Spawn task with error handling to prevent semaphore leak
                        # CRITICAL: If create_task fails, we must release the semaphore
                        try:
                            task = asyncio.create_task(
                                process_message_wrapper(
                                    receiver, msg, get_settings=get_settings, clients=clients, semaphore=concurrency
                                )
                            )
                            active_tasks.add(task)
                            task.add_done_callback(active_tasks.discard)
                        except Exception as task_error:
                            # Release semaphore if task creation fails
                            concurrency.release()
                            logger.error("Failed to create processing task: %s", task_error)
                            # Re-raise to trigger outer exception handler
                            raise
                except asyncio.CancelledError:
                    if active_tasks:
                        logger.info("Worker shutting down, waiting for %d active tasks...", len(active_tasks))
                        # Wait for tasks to complete, ensuring receiver stays open
                        await asyncio.gather(*active_tasks, return_exceptions=True)
                    raise
        except asyncio.CancelledError:
            break
        except Exception as ex:
            logger.exception("Worker loop error: %s", ex)
            await asyncio.sleep(2)


async def process_message_wrapper(receiver, msg, *, get_settings, clients: Clients, semaphore: asyncio.Semaphore):
    """
    Wrapper to ensure semaphore is released even if handling crashes.
    """
    try:
        await handle_queue_message(receiver, msg, get_settings=get_settings, clients=clients)
    except Exception as ex:
        logger.exception("Wrapper caught unhandled processing error: %s", ex)
    finally:
        semaphore.release()



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
    item_id = payload.get("item_id")
    reclassify_mode = payload.get("reclassify_mode")

    if not blob_url and not item_id:
        logger.warning("[msg:%s] No blob_url or item_id found in message, dead-lettering", message_id)
        await receiver.dead_letter_message(msg, reason="InvalidPayload")
        return

    target_ref = item_id or blob_url
    logger.info("[msg:%s] → Processing ref: %s (Mode: %s)", message_id, target_ref, reclassify_mode or "Ingestion")

    try:
        result = None
        with ProcessingTimer() as timer:
            if reclassify_mode:
                # Reclassification Branch
                models = payload.get("models")
                # Legacy support
                if not models:
                    m = payload.get("model")
                    if m == "both":
                        models = [config.PHI_DEPLOYMENT, config.PHI_FALLBACK_DEPLOYMENT]
                    elif m:
                        models = [m]

                from classificationg2s.services.pipeline import run_reclassification_pipeline
                result = await run_reclassification_pipeline(item_id or blob_id_from_url(blob_url), models=models, clients=clients)

            else:
                # Standard Ingestion Branch
                if not blob_url:
                     raise ValueError("Ingestion mode requires blob_url")

                # Update status to PROCESSING so it shows up in dashboard immediately
                try:
                    logger.info("[msg:%s] Setting status to PROCESSING for %s", message_id, blob_url)
                    processing_record = EmailRecord(
                        id=blob_id_from_url(blob_url),
                        file_url=blob_url,
                        status="PROCESSING",
                        updated_at=datetime.now(timezone.utc),
                        created_at=getattr(msg, "enqueued_time_utc", datetime.now(timezone.utc))
                    )
                    await save_to_cosmos(processing_record, clients=clients)
                except Exception as e:
                     logger.warning("[msg:%s] Could not set PROCESSING status: %s", message_id, e)

                settings = get_settings()
                if inspect.iscoroutine(settings):
                    settings = await settings
                logger.info("[msg:%s] Starting classification pipeline", message_id)
                result = await run_classification_pipeline(blob_url, settings=settings, clients=clients)

            logger.info("[msg:%s] Pipeline/Task completed in %.0fms", message_id, timer.duration_ms)

        # Update metadata
        # Only overwrite created_at if it's ingestion (fresh processing)
        if not reclassify_mode:
            arrival_time = getattr(msg, "enqueued_time_utc", datetime.now(timezone.utc))
            result.created_at = arrival_time

        # Always track processing time of this operation (though purely additive for history??)
        # Using a transient field or updating the record?
        # EmailRecord logic usually strictly defines schema.
        # For reclassification, we appended to comparison_results. We shouldn't necessarily overwrite the root processing_time_ms
        # unless it represents the *latest* operation.
        # But let's keep it simple: we update what we have.
        if not reclassify_mode:
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

        arrival_time = getattr(msg, "enqueued_time_utc", datetime.now(timezone.utc))
        record = EmailRecord(
            id=blob_id_from_url(blob_url),
            file_url=blob_url,
            status="ERROR",
            error=error_text,
            error_stage=error_stage,
            created_at=arrival_time,
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
        arrival_time = getattr(msg, "enqueued_time_utc", datetime.now(timezone.utc))
        try:
            record = EmailRecord(
                id=blob_id_from_url(blob_url),
                file_url=blob_url,
                status="ERROR",
                error=str(ex),
                error_stage="worker_unhandled",
                created_at=arrival_time,
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
