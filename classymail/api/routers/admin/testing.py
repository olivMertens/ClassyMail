"""Admin testing — simulate flow, connectivity checks, model connection tests."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from classymail.core import config
from classymail.core.llm_compat import build_chat_params
from classymail.services.azure_clients import Clients, get_clients, blob_id_from_url, get_cosmos_container as azure_get_cosmos_container
from classymail.services.generator import generate_email_pdf
from azure.servicebus import ServiceBusMessage
import logging
import uuid
import json
import os
from datetime import datetime, timezone

router = APIRouter()
logger = logging.getLogger("ClassyMail.admin")


class SimulateFlowRequest(BaseModel):
    use_aoai: bool = False


@router.post("/debug/simulate-flow")
async def simulate_flow(
    request: SimulateFlowRequest,
    clients: Clients = Depends(get_clients)
):
    """Simulates a complete flow by creating and uploading a realistic French email PDF."""
    try:
        use_aoai = request.use_aoai or bool(os.getenv("AZURE_OPENAI_ENDPOINT"))

        logger.info("[SIMULATION] Starting E2E simulation flow with realistic email")

        logger.info("[SIMULATION] Step 1: Generating realistic French email PDF")
        pdf_bytes, category, subject = generate_email_pdf(use_aoai=use_aoai)
        aoai_status = "enhanced" if use_aoai else "template"
        logger.info(f"[SIMULATION] Generated {aoai_status} PDF: {len(pdf_bytes)} bytes, Category: {category}")

        logger.info("[SIMULATION] Step 2: Uploading to Blob Storage")
        container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y/%m/%d")
        filename = f"simulation_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
        blob_name = f"uploads/{today}/{filename}"

        logger.info(f"[SIMULATION] Blob path: {blob_name}")
        blob_client = container_client.get_blob_client(blob_name)

        await blob_client.upload_blob(bytes(pdf_bytes), overwrite=True)
        blob_url = blob_client.url
        logger.info(f"[SIMULATION] Upload complete: {blob_url}")

        item_id = blob_id_from_url(blob_url)
        logger.info(f"[SIMULATION] Generated item_id: {item_id}")

        logger.info("[SIMULATION] Step 3: Creating PENDING record in Cosmos DB")
        try:
            await clients.ensure_cosmos_container()
            pending_start = datetime.now(timezone.utc).isoformat()
            pending_doc = {
                "id": item_id,
                "file_url": blob_url,
                "status": "PENDING",
                "subject": f"[TEST] {subject}",
                "created_at": pending_start,
                "updated_at": pending_start,
                "markdown": None,
                "classification": None,
                "test_mode": True,
                "expected_category": category,
                "processing_log": [{"ts": pending_start, "stage": "simulation", "event": "e2e_test_email"}]
            }
            await clients.cosmos_container.upsert_item(pending_doc)
            logger.info(f"[SIMULATION] PENDING record created: {item_id}")
        except Exception as e:
            logger.error(f"[SIMULATION] Failed to create pending record: {e}")

        logger.info("[SIMULATION] Step 4: Sending message to Service Bus")
        sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
        async with sender:
            message_payload = {"blob_url": blob_url}
            await sender.send_messages(ServiceBusMessage(json.dumps(message_payload)))
            logger.info(f"[SIMULATION] Message sent to queue: {config.SERVICE_BUS_QUEUE}")

        logger.info(f"[SIMULATION] Flow complete. Track with item_id: {item_id}")
        return {
            "status": "uploaded_and_queued",
            "item_id": item_id,
            "blob_url": blob_url,
            "test_mode": True,
            "expected_category": category,
            "generated_subject": subject
        }

    except Exception as e:
        logger.error(f"[SIMULATION] Simulation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debug/connectivity")
async def check_connectivity(clients: Clients = Depends(get_clients)):
    """Performs active write/delete tests to verify permissions and connectivity."""
    results = {
        "storage_upload": "pending",
        "cosmos_write": "pending",
        "servicebus_connect": "pending"
    }

    try:
        container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)
        test_blob_name = f"debug-test-{uuid.uuid4()}.txt"
        test_blob = container_client.get_blob_client(test_blob_name)
        await test_blob.upload_blob(b"debug connectivity check", overwrite=True)
        await test_blob.delete_blob()
        results["storage_upload"] = "ok"
    except Exception as e:
        results["storage_upload"] = str(e)

    try:
        container = await azure_get_cosmos_container(clients)
        test_id = f"debug-{uuid.uuid4()}"
        test_item = {"id": test_id, "type": "debug_check", "timestamp": str(uuid.uuid4())}
        await container.create_item(test_item)
        await container.delete_item(item=test_id, partition_key=test_id)
        results["cosmos_write"] = "ok"
    except Exception as e:
        results["cosmos_write"] = str(e)

    try:
        sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
        async with sender:
            pass

        receiver = clients.sb_client.get_queue_receiver(queue_name=config.SERVICE_BUS_QUEUE)
        async with receiver:
            await receiver.peek_messages(max_message_count=1)

        results["servicebus_connect"] = "ok"
    except Exception as e:
        results["servicebus_connect"] = str(e)

    return results


@router.get("/test-phi4")
async def test_phi4_connection(clients: Clients = Depends(get_clients)):
    """Test Phi-4 model connection"""
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        if not config.PHI_ENDPOINT:
            return {"status": "error", "error": "PHI_ENDPOINT not configured", "model": config.PHI_DEPLOYMENT}

        headers = await auth_headers(clients, model_type="openai")
        endpoint = f"{config.PHI_ENDPOINT.rstrip('/')}/openai/deployments/{config.PHI_DEPLOYMENT}/chat/completions?api-version={config.AI_API_VERSION}"

        payload = {
            "messages": [{"role": "user", "content": "Say 'Connection OK'"}],
            **build_chat_params(config.PHI_DEPLOYMENT, temperature=0, max_output_tokens=10),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.is_error:
                error_detail = response.text
                logger.error(f"Phi-4 error response: {error_detail}")
                return {"status": "error", "error": f"HTTP {response.status_code}: {error_detail}", "model": config.PHI_DEPLOYMENT}
            data = response.json()

        return {
            "status": "success",
            "model": config.PHI_DEPLOYMENT,
            "response": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
            "status_code": response.status_code
        }
    except Exception as e:
        logger.error(f"Phi-4 connection test failed: {e}")
        return {"status": "error", "error": str(e), "model": config.PHI_DEPLOYMENT}


@router.get("/blob-info")
async def blob_info(blob_url: str, clients: Clients = Depends(get_clients)):
    """Check blob existence, return container/blob info and SAS."""
    from azure.storage.blob.aio import BlobClient
    from urllib.parse import urlparse

    parsed = urlparse(blob_url)
    container = parsed.path.lstrip('/').split('/')[0] if parsed.path else ''
    blob_name = '/'.join(parsed.path.lstrip('/').split('/')[1:]) if parsed.path else ''
    exists = False
    try:
        blob_client = BlobClient.from_blob_url(blob_url, credential=clients.credential)
        exists = await blob_client.exists()
    except Exception as e:
        return {"error": str(e), "container": container, "blob": blob_name, "exists": exists}

    return {"container": container, "blob": blob_name, "exists": exists, "sas_url": None}


@router.get("/test-mistral-ocr")
async def test_mistral_ocr_connection(clients: Clients = Depends(get_clients)):
    """Test Mistral OCR connection"""
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        if not config.MISTRAL_ENDPOINT:
            return {"status": "error", "error": "MISTRAL_ENDPOINT not configured in environment", "model": config.MISTRAL_DEPLOYMENT}

        headers = await auth_headers(clients, model_type="mistral")

        base_mistral = config.MISTRAL_ENDPOINT.rstrip("/")
        if base_mistral.endswith("/providers/mistral/azure/ocr"):
            endpoint = base_mistral
        else:
            endpoint = f"{base_mistral}/providers/mistral/azure/ocr"
        if "?" not in endpoint:
            endpoint = f"{endpoint}?api-version={config.MISTRAL_API_VERSION}"

        one_px_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAuMBg4eM8sYAAAAASUVORK5CYII="
        payload = {
            "model": config.MISTRAL_DEPLOYMENT,
            "document": {
                "type": "image_url",
                "image_url": f"data:image/png;base64,{one_px_png}"
            },
            "include_image_base64": False
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.is_error:
                error_detail = response.text
                logger.error(f"Mistral OCR error response: {error_detail}")
                return {"status": "error", "error": f"HTTP {response.status_code}: {error_detail}", "model": config.MISTRAL_DEPLOYMENT}
            data = response.json()

        return {
            "status": "success",
            "model": config.MISTRAL_DEPLOYMENT,
            "pages_returned": len(data.get("pages", [])),
            "status_code": response.status_code
        }
    except Exception as e:
        logger.error(f"Mistral OCR connection test failed: {e}")
        return {"status": "error", "error": str(e), "model": config.MISTRAL_DEPLOYMENT}


@router.get("/test-gpt")
async def test_gpt_connection(model: str | None = None, clients: Clients = Depends(get_clients)):
    """Test GPT connection (defaults to configured fallback, or specific model)."""
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        gpt_endpoint = getattr(config, "GPT_ENDPOINT", config.PHI_ENDPOINT)

        if not gpt_endpoint:
            return {"status": "error", "error": "GPT_ENDPOINT/PHI_ENDPOINT not configured", "model": "unknown"}

        if model:
            gpt_deployment = model
        else:
            gpt_deployment = getattr(config, "GPT_DEPLOYMENT", config.PHI_FALLBACK_DEPLOYMENT)

        api_version = config.AI_API_VERSION

        headers = await auth_headers(clients, model_type="openai")
        endpoint = f"{gpt_endpoint.rstrip('/')}/openai/deployments/{gpt_deployment}/chat/completions?api-version={api_version}"

        payload = {
            "messages": [{"role": "user", "content": "Say 'GPT Connection OK'"}],
            **build_chat_params(gpt_deployment, temperature=0, max_output_tokens=10),
        }

        logger.info(f"[TEST-GPT] Testing {gpt_deployment} at {endpoint}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.is_error:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_message = error_json.get("error", {}).get("message", error_detail)
                except Exception:
                    error_message = error_detail

                logger.error(f"GPT error response for {gpt_deployment}: {error_message}")
                return {
                    "status": "error",
                    "error": f"HTTP {response.status_code}: {error_message}",
                    "model": gpt_deployment,
                    "endpoint": gpt_endpoint,
                    "deployment": gpt_deployment,
                    "details": "Check if deployment exists in Microsoft AI Foundry and has proper RBAC permissions"
                }
            data = response.json()

        return {
            "status": "success",
            "model": gpt_deployment,
            "endpoint": gpt_endpoint,
            "response": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
            "usage": data.get("usage"),
            "api_version": api_version,
            "status_code": response.status_code
        }
    except Exception as e:
        logger.error(f"GPT connection test failed for {model}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "model": model or getattr(config, "GPT_DEPLOYMENT", config.PHI_FALLBACK_DEPLOYMENT)
        }


@router.get("/test-language-service")
async def test_language_service(clients: Clients = Depends(get_clients)):
    """Test Azure AI Language service connection for PII detection."""
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        language_endpoint = getattr(config, "AZURE_LANGUAGE_ENDPOINT", None)

        if not language_endpoint:
            return {
                "status": "not_configured",
                "message": "AZURE_LANGUAGE_ENDPOINT not configured (optional service)"
            }

        api_version = "2023-04-01"
        headers = await auth_headers(clients, model_type="cognitive")
        headers["Content-Type"] = "application/json"

        endpoint = f"{language_endpoint.rstrip('/')}/language/:analyze-text?api-version={api_version}"

        payload = {
            "kind": "PiiEntityRecognition",
            "parameters": {
                "modelVersion": "latest"
            },
            "analysisInput": {
                "documents": [
                    {
                        "id": "1",
                        "language": "fr",
                        "text": "Test de connexion"
                    }
                ]
            }
        }

        logger.info(f"[TEST-LANGUAGE] Testing Azure AI Language at {endpoint}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)

            if response.is_error:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_message = error_json.get("error", {}).get("message", error_detail)
                except Exception:
                    error_message = error_detail

                logger.error(f"Language service error response: {error_message}")
                return {
                    "status": "error",
                    "error": f"HTTP {response.status_code}: {error_message}",
                    "endpoint": language_endpoint,
                    "details": "Check if Language service is deployed and has proper RBAC permissions (Cognitive Services Language Reader)"
                }

            data = response.json()
            documents = data.get("results", {}).get("documents", [])
            categories_detected = len(documents[0].get("entities", [])) if documents else 0

        return {
            "status": "success",
            "endpoint": language_endpoint,
            "categories_detected": categories_detected,
            "api_version": api_version,
            "status_code": response.status_code,
            "message": "Azure AI Language service is accessible"
        }
    except Exception as e:
        logger.error(f"Language service connection test failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "endpoint": getattr(config, "AZURE_LANGUAGE_ENDPOINT", "not configured")
        }
