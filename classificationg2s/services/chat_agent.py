from __future__ import annotations

import json
import logging
import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients
from classificationg2s.services.repository import (
    search_email_records,
    get_email_by_id,
    search_email_by_text,
    search_similar_emails,
    get_latest_errors,
    get_stats_summary,
    get_top_intents,
    get_low_confidence_items,
    get_processing_stats_by_day,
)

logger = logging.getLogger("classimail.chatbot")


def _enrich_with_links(item: dict | None) -> dict | None:
    if not item or not isinstance(item, dict):
        return item
    rid = item.get("id")
    if rid:
        links = item.get("_links", {}) or {}
        links.setdefault("view", f"/email/{rid}")
        links.setdefault("api", f"/api/emails/{rid}")
        links.setdefault("ui", "Dashboard > Table/View")
        item["_links"] = links
    return item


def _enrich_list_with_links(items: list | None) -> list | None:
    if not items:
        return items
    if isinstance(items, list):
        return [_enrich_with_links(x) for x in items]
    return items


class ChatAgent:
    def __init__(self):
        self.deployment = config.CHAT_DEPLOYMENT
        # Construct standard Azure OpenAI URL
        # Format: https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version={version}

        # Strip trailing slash just in case
        base = (config.CHAT_ENDPOINT or "").rstrip("/")

        # If user provided a URL that already looks like an OpenAI deployment URL, respect it
        if "/openai/deployments" in base:
             # Just append chat/completions if missing
             if "chat/completions" not in base:
                 self.endpoint_url = f"{base}/chat/completions?api-version={config.CHAT_API_VERSION}"
             else:
                 self.endpoint_url = f"{base}&api-version={config.CHAT_API_VERSION}" if "?" not in base else base
        elif base:
            # Assume it's the base resource URL (https://xyz.openai.azure.com/)
            if not self.deployment:
                # Fallback if deployment is missing
                self.deployment = "gpt-4o"

            self.endpoint_url = f"{base}/openai/deployments/{self.deployment}/chat/completions?api-version={config.CHAT_API_VERSION}"
        else:
            self.endpoint_url = ""

        self._token_provider = None
        self._auth_header_func = None

    def _ensure_auth(self):
        if self._auth_header_func:
            return

        api_key = getattr(config, "AI_API_KEY", None)
        if api_key:
            self._auth_header_func = lambda: {"api-key": api_key}
        else:
            # Use Entra ID
            cred = DefaultAzureCredential()
            scope = "https://cognitiveservices.azure.com/.default"
            self._token_provider = get_bearer_token_provider(cred, scope)
            self._auth_header_func = lambda: {"Authorization": f"Bearer {self._token_provider()}"}

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
        if not self.endpoint_url:
            return {"role": "assistant", "content": "Chatbot is not configured (missing CHAT_ENDPOINT)."}

        self._ensure_auth()

        # Define tools in OpenAI format
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_emails",
                    "description": "Search for emails in the database by keyword, subject, or ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The search query (keyword, subject snippet, or ID)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_email_by_id",
                    "description": "Get a full email record by ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Email ID"}
                        },
                        "required": ["id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_email_by_text",
                    "description": "Search email records by search_text field (full-text snippet).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search text"},
                            "limit": {"type": "integer", "description": "Max items", "default": 5}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_similar_emails",
                    "description": "Search for emails semantically similar to the query using Vector Search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The text to find similar emails for."},
                            "limit": {"type": "integer", "description": "Max items", "default": 5}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_latest_errors",
                    "description": "List latest errored emails (id, subject, error, updated_at).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max items", "default": 5}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stats_summary",
                    "description": "Get summary stats (total, pending, processing, processed, error, review_required, average_confidence).",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_intents",
                    "description": "Get top intents with document counts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max intents", "default": 5}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_low_confidence_items",
                    "description": "Get lowest-confidence processed emails. Optionally scope to an intent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max items", "default": 5},
                            "intent": {"type": "string", "description": "Filter by intent"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_processing_stats_by_day",
                    "description": "Get daily processing stats (count, avg_ms, sum_ms) for last N days.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {"type": "integer", "description": "Number of days (max 30)", "default": 7}
                        },
                        "required": []
                    }
                }
            }
        ]

        # Ensure system prompt
        conversation = list(messages)
        if not conversation or conversation[0].get("role") != "system":
            system_prompt = (
                "You are a dedicated AI assistant for the 'ClassificationG2S' email processing system. "
                "Your ONLY purpose is to help users manage and search for insurance emails processed by this system. "
                "You have access to a database via the 'search_emails' tool. "
                "RULES:\n"
                "1. If the user asks about anything unrelated to this system (e.g., general knowledge, coding, other brands, sports, weather), "
                "politely refuse and state that you can only assist with email classification tasks.\n"
                "2. extensive use of the 'search_emails' tool is encouraged to provide specific details.\n"
                "3. Never mention or promote competitor brands. Stay focused on this internal system.\n"
                "4. Be concise and professional.\n"
                "5. When you reference any email by id, include direct links if available (view/api).\n"
                "6. If asked about throughput or durations, use get_processing_stats_by_day and report per-day count and avg/sum durations in seconds."
            )
            conversation.insert(0, {"role": "system", "content": system_prompt})

        try:
            # First turn
            response_json = await self._call_llm(conversation, tools)
            if "choices" not in response_json or not response_json["choices"]:
                 logger.error(f"Unexpected LLM response: {response_json}")
                 return {"role": "assistant", "content": "Error: unexpected response from LLM."}

            message = response_json["choices"][0]["message"]

            # Handle tool calls
            tool_calls = message.get("tool_calls")
            if tool_calls:
                conversation.append(message)  # Add assistant's request to history

                for tool_call in tool_calls:
                    fn = tool_call["function"]
                    fname = fn["name"]
                    args_str = fn["arguments"]
                    call_id = tool_call["id"]

                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = {}

                    logger.info(f"Chatbot executing tool: {fname} args={args}")

                    content_str = "{}"
                    try:
                        if fname == "search_emails":
                            results = await search_email_records(args.get("query"), limit=5, clients=clients)
                            results = _enrich_list_with_links(results)
                            content_str = json.dumps(results, default=str)
                        elif fname == "get_email_by_id":
                            result = await get_email_by_id(args.get("id"), clients=clients)
                            result = _enrich_with_links(result)
                            content_str = json.dumps(result, default=str)
                        elif fname == "search_email_by_text":
                            limit = args.get("limit", 5)
                            # Ensure limit is int
                            if isinstance(limit, str) and limit.isdigit():
                                limit = int(limit)
                            results = await search_email_by_text(args.get("query"), limit=limit, clients=clients)
                            results = _enrich_list_with_links(results)
                            content_str = json.dumps(results, default=str)
                        elif fname == "search_similar_emails":
                            limit = args.get("limit", 5)
                            if isinstance(limit, str) and limit.isdigit():
                                limit = int(limit)
                            results = await search_similar_emails(args.get("query"), limit=limit, clients=clients)
                            results = _enrich_list_with_links(results)
                            content_str = json.dumps(results, default=str)
                        elif fname == "get_latest_errors":
                            limit = args.get("limit", 5)
                            if isinstance(limit, str) and limit.isdigit():
                                limit = int(limit)
                            results = await get_latest_errors(limit=limit, clients=clients)
                            results = _enrich_list_with_links(results)
                            content_str = json.dumps(results, default=str)
                        elif fname == "get_stats_summary":
                            result = await get_stats_summary(clients=clients)
                            content_str = json.dumps(result, default=str)
                        elif fname == "get_top_intents":
                            limit = args.get("limit", 5)
                            if isinstance(limit, str) and limit.isdigit():
                                limit = int(limit)
                            result = await get_top_intents(limit=limit, clients=clients)
                            content_str = json.dumps(result, default=str)
                        elif fname == "get_low_confidence_items":
                            limit = args.get("limit", 5)
                            if isinstance(limit, str) and limit.isdigit():
                                limit = int(limit)
                            result = await get_low_confidence_items(limit=limit, intent=args.get("intent"), clients=clients)
                            result = _enrich_list_with_links(result)
                            content_str = json.dumps(result, default=str)
                        elif fname == "get_processing_stats_by_day":
                            days = args.get("days", 7)
                            if isinstance(days, str) and days.isdigit():
                                days = int(days)
                            result = await get_processing_stats_by_day(days=days, clients=clients)
                            content_str = json.dumps(result, default=str)
                        else:
                             content_str = json.dumps({"error": f"Unknown function {fname}"})
                    except Exception as e:
                        logger.error(f"Tool execution failed: {e}", exc_info=True)
                        content_str = json.dumps({"error": str(e)})

                    conversation.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": content_str
                    })

                # Second turn
                final_response = await self._call_llm(conversation)
                if "choices" in final_response and final_response["choices"]:
                    return {
                        "role": "assistant",
                        "content": final_response["choices"][0]["message"]["content"]
                    }
                else:
                    return {"role": "assistant", "content": "I processed the data but received an empty response."}

            # Simple message response
            return {
                "role": "assistant",
                "content": message["content"]
            }

        except Exception as e:
            logger.error(f"Chatbot error: {e}", exc_info=True)
            return {
                "role": "assistant",
                "content": f"I encountered an error processing your request: {str(e)}",
            }

    async def _call_llm(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        headers = self._auth_header_func()
        payload = {
            "messages": messages,
            "max_completion_tokens": 800,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        logger.info(f"Calling Chat LLM: {self.endpoint_url}")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.endpoint_url, json=payload, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                logger.error(f"Chat LLM Failed: {ex.response.status_code} - {ex.response.text}")
                raise
            return resp.json()

# Global instance
agent = ChatAgent()
