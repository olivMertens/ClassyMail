#!/usr/bin/env python3
"""Test Azure Storage with explicit Azure CLI credential"""
import asyncio
import sys
from azure.identity.aio import AzureCliCredential
from azure.storage.blob.aio import BlobServiceClient

async def test_storage_auth():
    print("Testing with AzureCliCredential...")

    account_url = "https://emailpocst.blob.core.windows.net/"
    container_name = "pdf-inputs"

    try:
        credential = AzureCliCredential()

        # Test getting a token first
        print("Getting storage token...")
        token = await credential.get_token("https://storage.azure.com/.default")
        print(f"✅ Got token (expires: {token.expires_on})")

        blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
        print("✅ Created BlobServiceClient")

        # Skip listing containers, go straight to container access
        print(f"\nTesting container access: {container_name}...")
        container_client = blob_service_client.get_container_client(container_name)
        props = await container_client.get_container_properties()
        print(f"✅ Container properties: {props.name}")

        # Test uploading
        test_blob_name = "test-auth-cli.txt"
        print(f"\n Testing blob upload: {test_blob_name}...")
        blob_client = container_client.get_blob_client(test_blob_name)
        await blob_client.upload_blob(b"CLI credential test", overwrite=True)
        print(f"✅ Upload successful: {blob_client.url}")

        # Clean up
        await blob_client.delete_blob()
        print("✅ Test blob deleted")

        await blob_service_client.close()
        print("\n🎉 All tests passed with AzureCliCredential!")
        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test_storage_auth()))
