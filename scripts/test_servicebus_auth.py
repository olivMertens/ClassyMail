#!/usr/bin/env python3
"""Test Azure Service Bus authentication"""
import asyncio
import sys
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient

async def test_servicebus_auth():
    print("Testing Service Bus authentication...")

    fqdn = "email-poc-sbus.servicebus.windows.net"
    queue_name = "pdf-processing-queue"

    try:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        sb_client = ServiceBusClient(fully_qualified_namespace=fqdn, credential=credential)

        print(f"✅ Created ServiceBusClient for {fqdn}")

        # Test getting a queue receiver
        print(f"\nTesting queue receiver: {queue_name}...")
        async with sb_client.get_queue_receiver(queue_name=queue_name) as receiver:
            print("✅ Queue receiver created successfully")

            # Try to peek a message (non-destructive)
            print("Peeking messages...")
            messages = await receiver.peek_messages(max_message_count=1)
            print(f"✅ Peek successful ({len(messages)} messages in queue)")

        await sb_client.close()
        print("\n🎉 Service Bus authentication test passed!")
        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test_servicebus_auth()))
