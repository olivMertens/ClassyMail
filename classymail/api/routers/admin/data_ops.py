"""Admin data operations — reset, purge-dlq, replay-dlq, reprocess-all, generate-synthetic."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from classymail.core import config
from classymail.services.azure_clients import Clients, get_clients, get_cosmos_container as azure_get_cosmos_container
from classymail.services.repository import get_seed_examples_for_synthesis, save_synthetic_record
from classymail.services.generator import generate_synthetic_from_seeds
from classymail.services.messages import extract_blob_url
from azure.servicebus import ServiceBusMessage, ServiceBusSubQueue
import logging
import json
from datetime import datetime

router = APIRouter()
logger = logging.getLogger("ClassyMail.admin")


class ResetRequest(BaseModel):
    confirm_1: bool
    confirm_2: bool


class GenerateSyntheticRequest(BaseModel):
    target_count: int = 50


class ReprocessAllRequest(BaseModel):
    processing_strategy: str | None = None


class DeadLetterMessage(BaseModel):
    message_id: str | None = None
    delivery_count: int | None = None
    dead_letter_reason: str | None = None
    dead_letter_error_description: str | None = None
    dead_letter_source: str | None = None
    blob_url: str | None = None
    blob_id: str | None = None
    enqueued_time_utc: datetime | None = None
    sequence_number: int | None = None
    content_type: str | None = None
    subject: str | None = None
    correlation_id: str | None = None
    application_properties: dict | None = None
    body_preview: str | None = None
    cosmos_status: str | None = None
    cosmos_error: str | None = None
    cosmos_error_stage: str | None = None
    processing_log: list[dict] | None = None


class DeadLetterSummary(BaseModel):
    count: int
    messages: list[DeadLetterMessage]


@router.post("/generate-synthetic", status_code=status.HTTP_200_OK)
async def generate_synthetic_data(
    req: GenerateSyntheticRequest,
    clients: Clients = Depends(get_clients)
):
    """Generate synthetic data to reach the target count for fine-tuning."""
    try:
        seeds = await get_seed_examples_for_synthesis(limit=20, clients=clients)
        if not seeds:
            raise HTTPException(
                status_code=400,
                detail="No processed emails found to use as seed data. Upload and process at least 1 email via the Upload page before generating synthetic data."
            )

        count_to_generate = min(req.target_count, 10)
        generated_items = await generate_synthetic_from_seeds(seed_examples=seeds, count=count_to_generate)

        saved_count = 0
        for item in generated_items:
            await save_synthetic_record(item, clients=clients)
            saved_count += 1

        return {
            "status": "success",
            "generated_count": saved_count,
            "message": f"Generated {saved_count} synthetic items based on {len(seeds)} seeds."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate synthetic data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_environment(
    req: ResetRequest,
    clients: Clients = Depends(get_clients),
):
    """DANGER: Resets the environment by deleting all input blobs and Cosmos DB records."""
    if not (req.confirm_1 and req.confirm_2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Double confirmation required."
        )

    deleted_blobs = 0
    deleted_records = 0
    errors = []

    try:
        container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)
        async for blob in container_client.list_blobs():
            await container_client.delete_blob(blob.name)
            deleted_blobs += 1
    except Exception as e:
        logger.error(f"Failed to delete blobs: {e}")
        errors.append(f"Storage: {str(e)}")

    try:
        container = await azure_get_cosmos_container(clients)
        query = "SELECT c.id, c.id as partitionKey FROM c"
        items = [x async for x in container.query_items(query)]

        for item in items:
            await container.delete_item(item=item["id"], partition_key=item["partitionKey"])
            deleted_records += 1

    except Exception as e:
        logger.error(f"Failed to clean Cosmos DB: {e}")
        errors.append(f"DB: {str(e)}")

    deleted_dlq = 0
    try:
        if clients.sb_client:
            receiver = clients.sb_client.get_queue_receiver(
                queue_name=config.SERVICE_BUS_QUEUE,
                sub_queue=ServiceBusSubQueue.DEAD_LETTER,
                prefetch_count=50,
            )
            async with receiver:
                while True:
                    messages = await receiver.receive_messages(max_message_count=50, max_wait_time=2)
                    if not messages:
                        break
                    for msg in messages:
                        await receiver.complete_message(msg)
                        deleted_dlq += 1
    except Exception as e:
        logger.error(f"Failed to purge DLQ: {e}")
        errors.append(f"Service Bus DLQ: {str(e)}")

    if errors:
        return {
            "status": "partial_success",
            "deleted_blobs": deleted_blobs,
            "deleted_records": deleted_records,
            "deleted_dlq": deleted_dlq,
            "errors": errors
        }

    return {
        "status": "success",
        "deleted_blobs": deleted_blobs,
        "deleted_records": deleted_records,
        "deleted_dlq": deleted_dlq
    }


@router.post("/purge-dlq", status_code=status.HTTP_200_OK)
async def purge_dlq(clients: Clients = Depends(get_clients)):
    """Purges just the Dead Letter Queue (Service Bus)."""
    deleted_dlq = 0

    try:
        if clients.sb_client:
            receiver = clients.sb_client.get_queue_receiver(
                queue_name=config.SERVICE_BUS_QUEUE,
                sub_queue=ServiceBusSubQueue.DEAD_LETTER,
                prefetch_count=50,
            )
            async with receiver:
                while True:
                    messages = await receiver.receive_messages(max_message_count=50, max_wait_time=2)
                    if not messages:
                        break
                    for msg in messages:
                        await receiver.complete_message(msg)
                        deleted_dlq += 1
    except Exception as e:
        logger.error(f"Failed to purge DLQ: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to purge DLQ: {str(e)}")

    return {
        "status": "success",
        "deleted_dlq": deleted_dlq
    }


@router.post("/replay-dlq", status_code=status.HTTP_200_OK)
async def replay_dlq(clients: Clients = Depends(get_clients)):
    """Replay all Dead Letter Queue messages back into the active queue."""
    if not clients.sb_client:
        raise HTTPException(status_code=503, detail="Service Bus client not initialized")

    replayed = 0
    errors = []

    try:
        receiver = clients.sb_client.get_queue_receiver(
            queue_name=config.SERVICE_BUS_QUEUE,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER,
            prefetch_count=50,
        )
        sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)

        async with receiver, sender:
            while True:
                messages = await receiver.receive_messages(max_message_count=50, max_wait_time=5)
                if not messages:
                    break
                for msg in messages:
                    try:
                        body_bytes = b"".join([b for b in msg.body])
                        payload = json.loads(body_bytes.decode())
                        blob_url = extract_blob_url(payload)
                        if not blob_url:
                            errors.append(f"Message {msg.message_id}: no blob_url found")
                            await receiver.complete_message(msg)
                            continue

                        new_message = ServiceBusMessage(
                            json.dumps({"blob_url": blob_url})
                        )
                        await sender.send_messages(new_message)
                        await receiver.complete_message(msg)
                        replayed += 1
                    except Exception as e:
                        errors.append(f"Message {getattr(msg, 'message_id', '?')}: {e}")
                        try:
                            await receiver.abandon_message(msg)
                        except Exception:
                            pass
    except Exception as e:
        logger.error(f"Failed to replay DLQ: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to replay DLQ: {str(e)}")

    return {
        "status": "success" if not errors else "partial",
        "replayed": replayed,
        "errors": errors,
    }


@router.post("/reprocess-all", status_code=status.HTTP_200_OK)
async def reprocess_all(
    payload: ReprocessAllRequest,
    clients: Clients = Depends(get_clients),
):
    """Re-enqueue ALL processed emails for full pipeline reprocessing, then replay DLQ."""
    if not clients.sb_client:
        raise HTTPException(status_code=503, detail="Service Bus client not initialized")

    await clients.ensure_cosmos_container()

    query = (
        "SELECT c.id, c.file_url FROM c "
        "WHERE c.status IN ('PROCESSED', 'REVIEW_REQUIRED') "
        "AND IS_DEFINED(c.file_url) AND c.file_url != null"
    )

    enqueued = 0
    errors = []
    dlq_replayed = 0

    try:
        sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
        async with sender:
            async for item in clients.cosmos_container.query_items(query):
                try:
                    message_data: dict = {"blob_url": item["file_url"]}
                    if payload.processing_strategy in ("standard", "reasoning", "vision", "agentic"):
                        message_data["processing_strategy"] = payload.processing_strategy
                    await sender.send_messages(
                        ServiceBusMessage(json.dumps(message_data))
                    )
                    enqueued += 1
                except Exception as e:
                    errors.append({"id": item.get("id", "?"), "error": str(e)})

            try:
                receiver = clients.sb_client.get_queue_receiver(
                    queue_name=config.SERVICE_BUS_QUEUE,
                    sub_queue=ServiceBusSubQueue.DEAD_LETTER,
                    prefetch_count=50,
                )
                async with receiver:
                    while True:
                        messages = await receiver.receive_messages(
                            max_message_count=50, max_wait_time=5
                        )
                        if not messages:
                            break
                        for msg in messages:
                            try:
                                body_bytes = b"".join([b for b in msg.body])
                                msg_payload = json.loads(body_bytes.decode())
                                blob_url = extract_blob_url(msg_payload)
                                if not blob_url:
                                    await receiver.complete_message(msg)
                                    continue
                                new_msg = ServiceBusMessage(
                                    json.dumps({"blob_url": blob_url})
                                )
                                await sender.send_messages(new_msg)
                                await receiver.complete_message(msg)
                                dlq_replayed += 1
                            except Exception:
                                try:
                                    await receiver.abandon_message(msg)
                                except Exception:
                                    pass
            except Exception as dlq_err:
                logger.warning(f"DLQ replay during reprocess-all failed: {dlq_err}")

    except Exception as e:
        logger.error(f"Failed to reprocess-all: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reprocess-all: {str(e)}")

    return {
        "status": "success" if not errors else "partial",
        "enqueued": enqueued,
        "dlq_replayed": dlq_replayed,
        "errors": errors,
    }
