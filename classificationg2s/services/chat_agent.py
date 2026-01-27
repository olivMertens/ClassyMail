from __future__ import annotations

import json
import logging
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import (
    AssistantMessage,
    ChatCompletionsToolDefinition,
    CompletionsFinishReason,
    FunctionDefinition,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential

from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients
from classificationg2s.services.repository import (
    search_email_records,
    get_email_by_id,
    search_email_by_text,
    get_latest_errors,
    get_stats_summary,
    get_top_intents,
    get_low_confidence_items,
)

logger = logging.getLogger("classimail.chatbot")


class ChatAgent:
    def __init__(self):
        self._client: ChatCompletionsClient | None = None
        self._ensure_client()

    def _ensure_client(self):
        if self._client:
            return

        endpoint = config.CHAT_ENDPOINT
        if not endpoint:
            logger.warning("CHAT_ENDPOINT not configured. Chatbot will fail.")
            return

        # Use Key if available, else DefaultAzureCredential (Entra ID)
        api_key = getattr(config, "AI_API_KEY", None)
        if api_key:
            credential = AzureKeyCredential(api_key)
        else:
            credential = DefaultAzureCredential()

        self._client = ChatCompletionsClient(
            endpoint=endpoint,
            credential=credential,
            api_version=config.CHAT_API_VERSION,
        )

    async def run(
        self,
        messages: list[dict],
        clients: Clients,
    ) -> dict:
        """
        Runs the chat loop:
        1. Send user messages to LLM.
        2. If tool call, execute tool and add result to history.
        3. Send (history + tool result) back to LLM.
        4. Return final response.
        """
        self._ensure_client()
        if not self._client:
            return {"role": "assistant", "content": "Chatbot is not configured."}

        # Convert dict format to SDK models
        conversation = self._convert_messages(messages)

        # Define available tools
        tools = [
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name="search_emails",
                    description="Search for emails in the database by keyword, subject, or ID.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query (keyword, subject snippet, or ID)",
                            },
                        },
                        "required": ["query"],
                    },
                )
            ),
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name="get_email_by_id",
                    description="Get a full email record by ID.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Email ID"},
                        },
                        "required": ["id"],
                    },
                )
            ),
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name="search_email_by_text",
                    description="Search email records by search_text field (full-text snippet).",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search text"},
                            "limit": {"type": "integer", "description": "Max items", "default": 5},
                        },
                        "required": ["query"],
                    },
                )
            ),
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name="get_latest_errors",
                    description="List latest errored emails (id, subject, error, updated_at).",
                    parameters={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max items", "default": 5},
                        },
                        "required": [],
                    },
                )
            ),
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name="get_stats_summary",
                    description="Get summary stats (total, pending, processing, processed, error, review_required, average_confidence).",
                    parameters={"type": "object", "properties": {}},
                )
            ),
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name="get_top_intents",
                    description="Get top intents with document counts.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max intents", "default": 5},
                        },
                        "required": [],
                    },
                )
            ),
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name="get_low_confidence_items",
                    description="Get lowest-confidence processed emails. Optionally scope to an intent.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max items", "default": 5},
                            "intent": {"type": "string", "description": "Filter by intent"}
                        },
                        "required": [],
                    },
                )
            ),
        ]

        try:
            # First turn
            response = self._client.complete(
                messages=conversation,
                tools=tools,
                model=config.CHAT_DEPLOYMENT,
            )

            if response.choices[0].finish_reason == CompletionsFinishReason.TOOL_CALLS:
                tool_calls = response.choices[0].message.tool_calls

                # Append assistant's tool call request to history
                conversation.append(response.choices[0].message)

                # Execute tools
                for tool_call in tool_calls:
                    args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    fname = tool_call.function.name
                    logger.info(f"Chatbot executing tool: {fname} args={args}")

                    content = json.dumps({"error": f"Unknown function: {fname}"})
                    try:
                        if fname == "search_emails":
                            query = args.get("query")
                            results = await search_email_records(query, limit=5, clients=clients)
                            content = json.dumps(results, default=str)
                        elif fname == "get_email_by_id":
                            email_id = args.get("id")
                            result = await get_email_by_id(email_id, clients=clients)
                            content = json.dumps(result, default=str)
                        elif fname == "search_email_by_text":
                            query = args.get("query")
                            limit = args.get("limit", 5)
                            results = await search_email_by_text(query, limit=limit, clients=clients)
                            content = json.dumps(results, default=str)
                        elif fname == "get_latest_errors":
                            limit = args.get("limit", 5)
                            results = await get_latest_errors(limit=limit, clients=clients)
                            content = json.dumps(results, default=str)
                        elif fname == "get_stats_summary":
                            result = await get_stats_summary(clients=clients)
                            content = json.dumps(result, default=str)
                        elif fname == "get_top_intents":
                            limit = args.get("limit", 5)
                            result = await get_top_intents(limit=limit, clients=clients)
                            content = json.dumps(result, default=str)
                        elif fname == "get_low_confidence_items":
                            limit = args.get("limit", 5)
                            intent = args.get("intent")
                            result = await get_low_confidence_items(limit=limit, intent=intent, clients=clients)
                            content = json.dumps(result, default=str)
                    except Exception as e:  # noqa: BLE001
                        logger.exception("Tool execution failed")
                        content = json.dumps({"error": str(e)})

                    conversation.append(
                        ToolMessage(tool_call_id=tool_call.id, content=content)
                    )

                # Second turn (with tool results)
                final_response = self._client.complete(
                    messages=conversation,
                    model=config.CHAT_DEPLOYMENT,
                )
                return {
                    "role": "assistant",
                    "content": final_response.choices[0].message.content,
                }

            # No tool call, just return content
            return {
                "role": "assistant",
                "content": response.choices[0].message.content,
            }

        except Exception as e:
            logger.error(f"Chatbot error: {e}", exc_info=True)
            return {
                "role": "assistant",
                "content": f"I encountered an error processing your request: {str(e)}",
            }

    def _convert_messages(self, raw_messages: list[dict]) -> list:
        # Simple converter. Supports system/user/assistant text messages.
        # Tool history logic is handled internally in the run loop for this simple implementation.
        sdk_messages = []
        for m in raw_messages:
            role = m.get("role")
            content = m.get("content")
            if role == "system":
                sdk_messages.append(SystemMessage(content=content))
            elif role == "user":
                sdk_messages.append(UserMessage(content=content))
            elif role == "assistant":
                sdk_messages.append(AssistantMessage(content=content))

        # Ensure system prompt if not present
        if not sdk_messages or not isinstance(sdk_messages[0], SystemMessage):
            system_prompt = (
                "You are a dedicated AI assistant for the 'ClassificationG2S' email processing system. "
                "Your ONLY purpose is to help users manage and search for insurance emails processed by this system. "
                "You have access to a database via the 'search_emails' tool. "
                "RULES:\n"
                "1. If the user asks about anything unrelated to this system (e.g., general knowledge, coding, other brands, sports, weather), "
                "politely refuse and state that you can only assist with email classification tasks.\n"
                "2. extensive use of the 'search_emails' tool is encouraged to provide specific details.\n"
                "3. Never mention or promote competitor brands. Stay focused on this internal system.\n"
                "4. Be concise and professional."
            )
            sdk_messages.insert(0, SystemMessage(content=system_prompt))

        return sdk_messages


# Global instance
agent = ChatAgent()
