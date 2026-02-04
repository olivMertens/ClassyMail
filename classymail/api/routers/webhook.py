from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends

from azure.servicebus import ServiceBusMessage

from classymail.core import config
from classymail.services.azure_clients import get_sb_client


router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/ingest")
async def webhook_ingest(events: list = Body(...), sb_client=Depends(get_sb_client)):
    for ev in events:
        if ev.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return {"validationResponse": ev["data"]["validationCode"]}

    sender = sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
    async with sender:
        for ev in events:
            if ev.get("eventType") == "Microsoft.Storage.BlobCreated":
                blob_url = ev.get("data", {}).get("url")
                if not blob_url:
                    continue
                msg = ServiceBusMessage(json.dumps({"blob_url": blob_url}))
                await sender.send_messages(msg)

    return {"status": "enqueued", "count": len(events)}
