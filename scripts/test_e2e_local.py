import os
import asyncio
import httpx
import json
import subprocess

from pathlib import Path

async def launch_e2e():
    print("🎯 Starting E2E Test Flow...")

    # 1. Generate a dummy PDF
    pdf_dir = Path("dataset/pdf_test_e2e")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old files
    for f in pdf_dir.glob("*.pdf"):
        f.unlink()

    print("📄 Step 1: Generating a dummy PDF...")
    gen_proc = subprocess.run([
        "uv", "run", "python", "scripts/generate_dummy_pdfs.py",
        "--count", "1",
        "--out", str(pdf_dir),
        "--target-words", "100"
    ], capture_output=True, text=True)

    if gen_proc.returncode != 0:
        print(f"❌ PDF Generation failed: {gen_proc.stderr}")
        return

    pdf_file = next(pdf_dir.glob("*.pdf"), None)
    if not pdf_file:
        print("❌ No PDF generated.")
        return
    print(f"✅ Generated: {pdf_file.name}")

    # 2. Start API + Worker locally in background
    print("🚀 Step 2: Starting API + Worker locally...")
    env = os.environ.copy()
    env["ENABLE_WORKER"] = "true"
    # Port 8001 to avoid conflicts if 8000 is used
    api_port = "8001"

    # Use subprocess.Popen so it keeps running
    api_log = open("api_worker.log", "w")
    api_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "main:app", "--port", api_port],
        env=env,
        stdout=api_log,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Wait for API to be ready
    api_ready = False
    for _ in range(30):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://127.0.0.1:{api_port}/healthz")
                if resp.status_code == 200:
                    api_ready = True
                    break
        except Exception:
            pass
        await asyncio.sleep(1)

    if not api_ready:
        print("❌ API failed to start in time.")
        api_proc.terminate()
        return
    print("✅ API/Worker is ready.")

    # 3. Upload PDF
    print(f"📤 Step 3: Uploading {pdf_file.name} to local API...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            with open(pdf_file, 'rb') as f:
                files = {'files': (pdf_file.name, f, 'application/pdf')}
                resp = await client.post(f"http://127.0.0.1:{api_port}/api/upload", files=files)

            if resp.status_code != 200:
                print(f"❌ Upload failed: {resp.text}")
                api_proc.terminate()
                return

            upload_result = resp.json()
            blob_url = upload_result['results'][0].get('blob_url')
            print(f"✅ Uploaded! Blob URL: {blob_url}")

            # 4. Monitor Cosmos DB for processing
            print("⏳ Step 4: Waiting for processing completion (polling API)...")
            from classificationg2s.services.azure_clients import blob_id_from_url
            doc_id = blob_id_from_url(blob_url)

            processed = False
            for _ in range(60): # 1 minute timeout
                resp = await client.get(f"http://127.0.0.1:{api_port}/api/emails/{doc_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status")
                    print(f"   Current status: {status}")
                    if status == "PROCESSED":
                        processed = True
                        print("\n🎉 E2E FLOW COMPLETED SUCCESSFULLY!")
                        print(f"📝 Subject: {data.get('subject')}")
                        print(f"🏷️ Intents: {json.dumps(data.get('classification', {}).get('detected_intents', []), indent=2)}")
                        break
                    elif status == "ERROR":
                        processed = True
                        print("\n❌ E2E FLOW FAILED WITH ERROR:")
                        print(f"🔌 Stage: {data.get('error_stage')}")
                        print(f"💥 Error: {data.get('error')}")
                        print(f"📜 Log Summary: {json.dumps(data.get('processing_log', [])[-3:] if data.get('processing_log') else [], indent=2)}")
                        break
                await asyncio.sleep(2)

            if not processed:
                print("❌ Processing timed out or failed.")
                # Show last logs from API/Worker
                print("\nLast Worker/API logs:")
                # We can't easily read from the pipe while it's running without blocking/complexities
                # but let's try a quick read
                api_proc.terminate()
                return

    except Exception as e:
        print(f"💥 E2E Test crashed: {e}")
    finally:
        api_proc.terminate()

if __name__ == "__main__":
    asyncio.run(launch_e2e())
