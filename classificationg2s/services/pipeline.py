from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from classificationg2s.models import EmailRecord, ClassificationResult
from classificationg2s.services.azure_clients import download_blob_as_base64, blob_id_from_url, Clients
from classificationg2s.services.llm_pipeline import ocr_with_mistral, classify_with_phi4, process_agent_response
from classificationg2s.services.costing import compute_cost_llm, compute_cost_mistral


def estimate_pdf_pages(pdf_bytes: bytes) -> int:
    try:
        return max(pdf_bytes.count(b"/Type /Page"), 1)
    except Exception:
        return 1


async def run_classification_pipeline(
    blob_url: str,
    *,
    cost_overrides: Optional[dict] = None,
    clients: Clients | None = None,
) -> EmailRecord:
    processing_log: list[dict] = []

    def log(stage: str, event: str, detail: Optional[str] = None) -> None:
        processing_log.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "event": event,
                "detail": detail,
            }
        )

    try:
        log("download", "start")
        pdf_b64, pdf_bytes = await download_blob_as_base64(blob_url, return_bytes=True, clients=clients)
        log("download", "ok")
    except Exception as ex:
        from classificationg2s.models import OCRFailed

        log("download", "error", f"{type(ex).__name__}: {ex}")
        err = OCRFailed(f"stage=download: {type(ex).__name__}: {ex}")
        setattr(err, "processing_log", processing_log)
        raise err from ex

    try:
        log("ocr", "start")
        ocr_result = await ocr_with_mistral(pdf_b64, clients=clients)
        log("ocr", "ok")
    except Exception as ex:
        from classificationg2s.models import OCRFailed

        log("ocr", "error", f"{type(ex).__name__}: {ex}")
        err = OCRFailed(f"stage=ocr: {type(ex).__name__}: {ex}")
        setattr(err, "processing_log", processing_log)
        raise err from ex

    markdown = ocr_result.get("markdown")

    try:
        log("classify", "start")
        classification_raw = await classify_with_phi4(markdown, clients=clients)
        log("classify", "ok")
    except Exception as ex:
        from classificationg2s.models import OCRFailed

        log("classify", "error", f"{type(ex).__name__}: {ex}")
        err = OCRFailed(f"stage=classify: {type(ex).__name__}: {ex}")
        setattr(err, "processing_log", processing_log)
        raise err from ex
    processed = process_agent_response(classification_raw)

    status = "REVIEW_REQUIRED" if processed.get("needs_review") else "PROCESSED"
    markdown_trunc = markdown[:30000] if markdown else None

    mistral_usage = ocr_result.get("usage") or {}
    pages = mistral_usage.get("pages_processed") or mistral_usage.get("pages") or estimate_pdf_pages(pdf_bytes)

    llm_usage = classification_raw.get("usage") if isinstance(classification_raw, dict) else None
    fallback_used = bool(classification_raw.get("fallback_used")) if isinstance(classification_raw, dict) else False
    llm_cost = compute_cost_llm(llm_usage, fallback_used=fallback_used, overrides=cost_overrides)

    usage = {
        "phi4": llm_usage,
        "phi4_cost_usd": llm_cost,
        "phi4_model": classification_raw.get("model") if isinstance(classification_raw, dict) else None,
        "phi4_fallback_used": fallback_used,
        "phi4_context_truncated": bool(classification_raw.get("context_truncated")) if isinstance(classification_raw, dict) else False,
        "mistral": {
            "estimated_pages": pages,
            "cost_usd": compute_cost_mistral(pages, overrides=cost_overrides),
        },
    }

    return EmailRecord(
        id=blob_id_from_url(blob_url),
        file_url=blob_url,
        markdown=markdown_trunc,
        classification=ClassificationResult(
            **{
                "detected_intents": processed.get("intents", []),
                "global_complexity": processed.get("raw_response", {}).get("global_complexity")
                if processed.get("raw_response")
                else None,
                "needs_review": processed.get("needs_review", False),
                "raw_response": processed.get("raw_response"),
            }
        ),
        status=status,
        usage=usage,
        updated_at=datetime.now(timezone.utc),
        processing_log=processing_log,
    )
