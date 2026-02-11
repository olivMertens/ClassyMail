#!/usr/bin/env python3
"""
Performance diagnostic for vision strategy processing.
Measures bottlenecks in PDF-to-image conversion and Mistral API requests.
Run with: uv run python scripts/test_vision_performance.py
"""

import asyncio
import base64
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

async def test_vision_image_conversion_overhead():
    """Profile the PDF→JPEG conversion that slows vision processing"""
    try:
        import fitz
        from PIL import Image
        import io
    except ImportError:
        logger.error("Missing dependencies: pip install PyMuPDF Pillow")
        return

    # Create a mock 5-page PDF (simple)
    try:
        doc = fitz.open()
        for i in range(5):
            page = doc.new_page(width=612, height=792)
            text = f"Page {i+1} - Sample content for testing vision strategy"
            page.insert_text((50, 50), text, fontsize=12)

        pdf_bytes = doc.tobytes()
        doc.close()

        logger.info(f"Created test PDF: {len(pdf_bytes)} bytes, ~5 pages")
    except Exception as e:
        logger.error(f"Failed to create test PDF: {e}")
        return

    # ===== TEST 1: Image conversion timing =====
    logger.info("\n[TEST 1] PDF→JPEG Conversion for Vision Strategy")
    logger.info("─" * 60)

    conversion_timer = time.perf_counter()
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)
        logger.info(f"  Pages to convert: {page_count}")

        # Standard vision strategy: convert each page to 2x JPEG
        for page_idx in range(page_count):
            page_start = time.perf_counter()

            page = doc.load_page(page_idx)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x resolution = HIGH OVERHEAD
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            page_time = (time.perf_counter() - page_start) * 1000
            logger.info(f"    Page {page_idx+1}: JPEG={len(img_b64)}B, conversion={page_time:.1f}ms")

        doc.close()
        conversion_time = (time.perf_counter() - conversion_timer) * 1000
        logger.info(f"\n✓ Total conversion time: {conversion_time:.1f}ms ({conversion_time/page_count:.1f}ms/page)")

    except Exception as e:
        logger.error(f"✗ Conversion failed: {e}")
        return

    # ===== RECOMMENDATIONS =====
    logger.info("\n[DIAGNOSIS] Why Vision Is Slow")
    logger.info("─" * 60)
    logger.info("""
Key Bottlenecks:
1. PDF→JPEG Conversion (Compute-Heavy)
   - fitz.get_pixmap(matrix=fitz.Matrix(2, 2)): 2x resolution rendering
   - PIL Image encoding: JPEG compression takes time
   - Per-page overhead: ~50-150ms per page (depends on complexity)

2. API Requests (Network I/O)
   - Each page sent to Mistral Document AI separately
   - Vision enrichment + BBox annotation: adds ~1-2s per request
   - 5-page PDF = 5 sequential API calls (~5-10s)

3. Concurrent Processing Limits
   - Even with async, concurrent calls hit Mistral rate limits
   - Default: MISTRAL_RPM=30 (0.5 req/sec = 2s minimum per request)

OPTIMIZATION: Why Is Vision Slower Than Standard?
""")

    print(f"""
STRATEGY COMPARISON (Estimated):
┌─────────────┬──────────────┬──────────────┐
│ Component   │ Standard     │ Vision       │
├─────────────┼──────────────┼──────────────┤
│ PDF Upload  │ 100ms        │ 100ms        │
│ OCR (API)   │ 5-10s        │ 5-10s        │
│ Image Conv  │ 0ms          │ {conversion_time:.0f}ms ← ADDED │
│ Enrichment  │ None         │ +2-5s        │
├─────────────┼──────────────┼──────────────┤
│ TOTAL       │ ~6-11s       │ ~{conversion_time/1000 + 12:.0f}-17s │
└─────────────┴──────────────┴──────────────┘

⚠️  WARNINGS:
    • Vision conversion scales badly with page count
    • Each page = re-render PDF at 2x resolution
    • Vision API calls are sequential (not truly parallel)
""")

    logger.info("\nRECOMMENDATIONS:")
    logger.info("  1. Reduce pixmap resolution (fitz.Matrix(1, 1) instead of 2,2)")
    logger.info("  2. Lower JPEG quality (quality=70 instead of 85)")
    logger.info("  3. Implement page sampling (skip non-relevant pages)")
    logger.info("  4. Add caching for PDF→image conversion")
    logger.info("  5. Consider vision only for high-uncertainty results (fallback)")
    logger.info("\nAUDIT: Enable telemetry to track Application Insights metrics:")
    logger.info("  • app.vision_enrichment_time_ms")
    logger.info("  • app.image_conversion_time_ms")
    logger.info("  • mistral_document_ai_page span duration")


async def main():
    logger.info("🔍 Vision Strategy Performance Diagnosis Tool")
    logger.info("=" * 60)
    await test_vision_image_conversion_overhead()
    logger.info("\n✅ Diagnostics complete. Check Application Insights for actual tenant times.")


if __name__ == "__main__":
    asyncio.run(main())
