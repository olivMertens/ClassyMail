#!/usr/bin/env python3
"""Test Azure Storage authentication with DefaultAzureCredential"""
import asyncio
import sys
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient

async def test_storage_auth():
    print("Testing Azure Storage authentication...")

    account_url = "https://emailpocst.blob.core.windows.net/"
    container_name = "pdf-inputs"

    try:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)

        print(f"✅ Created BlobServiceClient for {account_url}")

        # Test listing containers
        print("Testing list containers...")
        async for container in blob_service_client.list_containers():
            print(f"  - Found container: {container.name}")
        print("✅ List containers successful")

        # Test container access
        print(f"\nTesting access to container: {container_name}...")
        container_client = blob_service_client.get_container_client(container_name)
        props = await container_client.get_container_properties()
        print(f"✅ Container properties retrieved: {props.name}")

        # Test uploading a small blob
        test_blob_name = "test-auth-check.txt"
        print(f"\nTesting blob upload: {test_blob_name}...")
        blob_client = container_client.get_blob_client(test_blob_name)
        await blob_client.upload_blob(b"Authentication test", overwrite=True)
        print(f"✅ Blob upload successful: {blob_client.url}")

        # Clean up test blob
        await blob_client.delete_blob()
        print("✅ Test blob deleted")

        await blob_service_client.close()
        print("\n🎉 All authentication tests passed!")
        return 0

    except Exception as e:
        print(f"\n❌ Authentication test failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test_storage_auth()))
