"""
Tests for batch email reprocessing API endpoint.

Tests cover successful batch reprocessing, error handling for invalid IDs,
missing/invalid strategy parameters, and Service Bus/Cosmos DB interactions.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from azure.servicebus import ServiceBusMessage

from classymail.api.routers.emails import batch_reprocess_emails


@pytest.fixture
def mock_cosmos_container():
    """Mock Cosmos DB container."""
    container = AsyncMock()
    return container


@pytest.fixture
def mock_sb_client():
    """Mock Service Bus client."""
    client = AsyncMock()

    # Create a proper async context manager mock for the sender
    sender = AsyncMock()
    sender.__aenter__ = AsyncMock(return_value=sender)
    sender.__aexit__ = AsyncMock(return_value=None)

    # Make get_queue_sender return the sender directly (not a coroutine)
    client.get_queue_sender = MagicMock(return_value=sender)

    return client


@pytest.mark.asyncio
async def test_batch_reprocess_success(mock_cosmos_container, mock_sb_client):
    """Test successful batch reprocessing with valid IDs."""
    # Setup
    email_ids = ["email1", "email2", "email3"]
    mock_cosmos_container.read_item.side_effect = [
        {"id": "email1", "file_url": "https://storage.blob/email1.pdf"},
        {"id": "email2", "file_url": "https://storage.blob/email2.pdf"},
        {"id": "email3", "file_url": "https://storage.blob/email3.pdf"},
    ]

    sender = mock_sb_client.get_queue_sender.return_value

    # Execute
    result = await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "standard"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    # Verify
    assert result["enqueued"] == 3
    assert result["failed"] == 0
    assert result["errors"] == []
    assert result["processing_strategy"] == "standard"

    # Verify Cosmos DB queries
    assert mock_cosmos_container.read_item.call_count == 3

    # Verify Service Bus messages
    assert sender.send_messages.call_count == 3


@pytest.mark.asyncio
async def test_batch_reprocess_with_vision_strategy(mock_cosmos_container, mock_sb_client):
    """Test batch reprocessing with vision strategy."""
    email_ids = ["email1", "email2"]
    mock_cosmos_container.read_item.side_effect = [
        {"id": "email1", "file_url": "https://storage.blob/email1.pdf"},
        {"id": "email2", "file_url": "https://storage.blob/email2.pdf"},
    ]

    result = await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "vision"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 2
    assert result["processing_strategy"] == "vision"


@pytest.mark.asyncio
async def test_batch_reprocess_with_reasoning_strategy(mock_cosmos_container, mock_sb_client):
    """Test batch reprocessing with reasoning strategy."""
    email_ids = ["email1"]
    mock_cosmos_container.read_item.return_value = {
        "id": "email1",
        "file_url": "https://storage.blob/email1.pdf"
    }

    result = await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "reasoning"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 1
    assert result["processing_strategy"] == "reasoning"


@pytest.mark.asyncio
async def test_batch_reprocess_without_strategy(mock_cosmos_container, mock_sb_client):
    """Test batch reprocessing without specified strategy."""
    email_ids = ["email1"]
    mock_cosmos_container.read_item.return_value = {
        "id": "email1",
        "file_url": "https://storage.blob/email1.pdf"
    }

    sender = mock_sb_client.get_queue_sender.return_value

    result = await batch_reprocess_emails(
        payload={"ids": email_ids},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 1
    assert result["processing_strategy"] is None

    # Verify message data doesn't include strategy
    call_args = sender.send_messages.call_args_list[0]
    message = call_args[0][0]
    message_data = json.loads(str(message))
    assert "processing_strategy" not in message_data or message_data.get("processing_strategy") is None


@pytest.mark.asyncio
async def test_batch_reprocess_no_ids_provided(mock_cosmos_container, mock_sb_client):
    """Test error when no email IDs are provided."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await batch_reprocess_emails(
            payload={},
            cosmos_container=mock_cosmos_container,
            sb_client=mock_sb_client
        )

    assert exc_info.value.status_code == 400
    assert "No email ids provided" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_batch_reprocess_empty_ids_list(mock_cosmos_container, mock_sb_client):
    """Test error when empty IDs list is provided."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await batch_reprocess_emails(
            payload={"ids": []},
            cosmos_container=mock_cosmos_container,
            sb_client=mock_sb_client
        )

    assert exc_info.value.status_code == 400
    assert "No email ids provided" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_batch_reprocess_missing_file_url(mock_cosmos_container, mock_sb_client):
    """Test handling of emails with missing file_url."""
    email_ids = ["email1", "email2", "email3"]
    mock_cosmos_container.read_item.side_effect = [
        {"id": "email1", "file_url": "https://storage.blob/email1.pdf"},
        {"id": "email2"},  # Missing file_url
        {"id": "email3", "file_url": "https://storage.blob/email3.pdf"},
    ]

    result = await batch_reprocess_emails(
        payload={"ids": email_ids},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 2
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == "email2"
    assert "file_url missing" in result["errors"][0]["error"]


@pytest.mark.asyncio
async def test_batch_reprocess_cosmos_read_error(mock_cosmos_container, mock_sb_client):
    """Test handling of Cosmos DB read errors."""
    email_ids = ["email1", "email2", "email3"]
    mock_cosmos_container.read_item.side_effect = [
        {"id": "email1", "file_url": "https://storage.blob/email1.pdf"},
        Exception("Item not found"),  # Cosmos DB error
        {"id": "email3", "file_url": "https://storage.blob/email3.pdf"},
    ]

    result = await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "standard"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 2
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == "email2"
    assert "Item not found" in result["errors"][0]["error"]


@pytest.mark.asyncio
async def test_batch_reprocess_service_bus_send_error(mock_cosmos_container, mock_sb_client):
    """Test handling of Service Bus send errors."""
    email_ids = ["email1", "email2"]
    mock_cosmos_container.read_item.side_effect = [
        {"id": "email1", "file_url": "https://storage.blob/email1.pdf"},
        {"id": "email2", "file_url": "https://storage.blob/email2.pdf"},
    ]

    sender = mock_sb_client.get_queue_sender.return_value
    sender.send_messages.side_effect = [
        None,  # First send succeeds
        Exception("Service Bus unavailable"),  # Second send fails
    ]

    result = await batch_reprocess_emails(
        payload={"ids": email_ids},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 1
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == "email2"
    assert "Service Bus unavailable" in result["errors"][0]["error"]


@pytest.mark.asyncio
async def test_batch_reprocess_partial_success(mock_cosmos_container, mock_sb_client):
    """Test batch reprocessing with mixed success and errors."""
    email_ids = ["email1", "email2", "email3", "email4"]
    mock_cosmos_container.read_item.side_effect = [
        {"id": "email1", "file_url": "https://storage.blob/email1.pdf"},
        {"id": "email2"},  # Missing file_url
        Exception("Not found"),  # Cosmos error
        {"id": "email4", "file_url": "https://storage.blob/email4.pdf"},
    ]

    result = await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "vision"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 2
    assert result["failed"] == 2
    assert len(result["errors"]) == 2
    assert result["processing_strategy"] == "vision"


@pytest.mark.asyncio
async def test_batch_reprocess_invalid_strategy_ignored(mock_cosmos_container, mock_sb_client):
    """Test that invalid strategy values don't cause errors but are not included in message."""
    email_ids = ["email1"]
    mock_cosmos_container.read_item.return_value = {
        "id": "email1",
        "file_url": "https://storage.blob/email1.pdf"
    }

    sender = mock_sb_client.get_queue_sender.return_value

    result = await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "invalid_strategy"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 1
    assert result["processing_strategy"] == "invalid_strategy"

    # Verify message data doesn't include invalid strategy
    call_args = sender.send_messages.call_args_list[0]
    message = call_args[0][0]
    message_data = json.loads(str(message))
    assert "processing_strategy" not in message_data or message_data.get("processing_strategy") != "invalid_strategy"


@pytest.mark.asyncio
async def test_batch_reprocess_message_format(mock_cosmos_container, mock_sb_client):
    """Test that Service Bus messages have correct format."""
    email_ids = ["email1"]
    blob_url = "https://storage.blob/email1.pdf"
    mock_cosmos_container.read_item.return_value = {
        "id": "email1",
        "file_url": blob_url
    }

    sender = mock_sb_client.get_queue_sender.return_value
    sent_messages = []

    async def capture_message(msg):
        sent_messages.append(msg)

    sender.send_messages.side_effect = capture_message

    await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "reasoning"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert len(sent_messages) == 1
    message = sent_messages[0]

    # Verify message is ServiceBusMessage type
    assert isinstance(message, ServiceBusMessage)

    # Parse message data
    message_data = json.loads(str(message))
    assert message_data["blob_url"] == blob_url
    assert message_data["processing_strategy"] == "reasoning"


@pytest.mark.asyncio
async def test_batch_reprocess_large_batch(mock_cosmos_container, mock_sb_client):
    """Test batch reprocessing with large number of emails."""
    # Create 50 email IDs
    email_ids = [f"email{i}" for i in range(50)]

    # Mock Cosmos DB responses
    mock_cosmos_container.read_item.side_effect = [
        {"id": email_id, "file_url": f"https://storage.blob/{email_id}.pdf"}
        for email_id in email_ids
    ]

    sender = mock_sb_client.get_queue_sender.return_value

    result = await batch_reprocess_emails(
        payload={"ids": email_ids, "processing_strategy": "standard"},
        cosmos_container=mock_cosmos_container,
        sb_client=mock_sb_client
    )

    assert result["enqueued"] == 50
    assert result["failed"] == 0
    assert mock_cosmos_container.read_item.call_count == 50
    assert sender.send_messages.call_count == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
