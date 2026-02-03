from __future__ import annotations

import json
import logging
import uuid
import re
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
                    "description": "Search emails by exact ID or subject line only (metadata search). NOT for full-text content search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Email ID or exact subject line snippet"}
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
                    "description": "PRIMARY SEARCH TOOL. Search the full OCR content (markdown) of emails for any keyword or phrase. Use this for general searches like 'accident', 'address change', customer names, etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Keyword or phrase to search in email content (OCR markdown)"},
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

        # Ensure developer prompt (Reasoning models prefer 'developer' over 'system')
        conversation = list(messages)

        # specific handling for reasoning models (gpt-5.x, o1, etc)
        # 1. Convert any existing 'system' messages to 'developer'
        # 2. Or insert developer prompt if missing

        has_context = False
        for msg in conversation:
            if msg.get("role") == "system":
                msg["role"] = "developer"
                has_context = True
            elif msg.get("role") == "developer":
                has_context = True

        if not has_context:
            system_prompt = (
                "You are a dedicated AI assistant for the 'ClassificationG2S' email processing system. "
                "Your ONLY purpose is to help users manage and search for insurance emails processed by this system. "
                "You have access to multiple search tools - ALWAYS use 'search_email_by_text' for general keyword searches (it searches the full OCR content). "
                "RULES:\n"
                "1. If the user asks about anything unrelated to this system (e.g., general knowledge, coding, other brands, sports, weather), "
                "politely refuse and state that you can only assist with email classification tasks.\n"
                "2. For ANY keyword search (like 'accident', 'address change', customer names), ALWAYS use 'search_email_by_text' first (it searches OCR markdown content).\n"
                "3. Use 'search_similar_emails' for semantic/concept searches when exact keywords might not match.\n"
                "4. Use 'search_emails' ONLY if user provides exact email ID or subject line.\n"
                "5. Never mention or promote competitor brands. Stay focused on this internal system.\n"
                "6. Be concise and professional.\n"
                "7. When you reference any email by id, include direct links if available (view/api).\n"
                "8. If asked about throughput or durations, use get_processing_stats_by_day and report per-day count and avg/sum durations in seconds.\n"
                "9. NEVER output raw JSON or internal reasoning in the final response. If you use a tool, do not repeat its arguments or explain your decision process. Just provide the final answer.\n"
                "10. CRITICAL: Do not expose your internal thinking process. Only output the final user-facing response.\n"
                "11. NEVER output a raw JSON object as your final answer. If you want to perform a search, you MUST use the provided tools (function calling) instead of writing the JSON parameters in the text.\n"
                "12. optimization: Call tools only when necessary. If the user greets you, just reply greeting."
            )
            conversation.insert(0, {"role": "developer", "content": system_prompt})

        try:
            # Main Loop for multi-turn tool execution (Reasoning models do sequential calls)
            MAX_TURNS = 5
            turn_count = 0

            while turn_count < MAX_TURNS:
                turn_count += 1

                # Call LLM
                response_json = await self._call_llm(conversation, tools)

                if "choices" not in response_json or not response_json["choices"]:
                     logger.error(f"Unexpected LLM response: {response_json}")
                     return {"role": "assistant", "content": "Error: unexpected response from LLM."}

                message = response_json["choices"][0]["message"]
                tool_calls = message.get("tool_calls")
                content = message.get("content")

                # HEURISTIC FIX: Recover from hallucinated JSON in content
                if not tool_calls and content:
                    json_match = re.search(r'\{.*"query":.*\}', content.strip(), re.DOTALL)
                    if json_match:
                        try:
                            json_str = json_match.group(0)
                            _ = json.loads(json_str)
                            logger.warning("Chatbot recovered from hallucinated JSON tool call.")
                            tool_calls = [{
                                "id": f"call_{uuid.uuid4()}",
                                "type": "function",
                                "function": {
                                    "name": "search_email_by_text",
                                    "arguments": json_str
                                }
                            }]
                            content = None # Clear content as we converted it
                        except Exception:
                            pass

                # If no tools, we have our final answer (or just text)
                if not tool_calls:
                    content = self._extract_final_answer(content)
                    return {"role": "assistant", "content": content}

                # Handle Tool Calls
                conversation.append(message)  # Add assistant's request to history

                # Execute all requested tools (usually 1 if parallel=False, but loop handles list generic)
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

                # Loop continues to next turn to let Model see tool results and decide next step...

            return {"role": "assistant", "content": "Error: Chatbot exceeded maximum turns."}

        except Exception as e:
            logger.error(f"Chatbot error: {e}", exc_info=True)
            return {
                "role": "assistant",
                "content": f"I encountered an error processing your request: {str(e)}",
            }

    async def _call_llm(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        headers = self._auth_header_func()
        # Reasoning models (e.g. gpt-5.x, o1, o3) do not support 'temperature' or 'top_p'.
        # We rely on their internal reasoning for consistency.
        payload = {
            "messages": messages,
            "max_completion_tokens": 4000, # Increased limit to accommodate reasoning/CoT tokens
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            # Explicitly DISABLE parallel tool calls (NOT supported by reasoning models like o1)
            payload["parallel_tool_calls"] = False

        logger.info(f"Calling Chat LLM: {self.endpoint_url}")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.endpoint_url, json=payload, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                logger.error(f"Chat LLM Failed: {ex.response.status_code} - {ex.response.text}")
                raise
            return resp.json()

    def _extract_final_answer(self, content: str) -> str:
        """
        Extract final answer from reasoning models that expose CoT.
        Reasoning models (o1, o3, gpt-5.x-chat) may prefix responses with thinking traces.
        Heuristic: Look for common markers like final answer section or clean up verbose reasoning.
        """
        if not content:
            return content

        # Common patterns in reasoning model outputs
        markers = [
            "\n\nFinal Answer:",
            "\n\nAnswer:",
            "\n\n---\n\n",
            "\n\nLet me provide the results:",
        ]

        for marker in markers:
            if marker in content:
                parts = content.split(marker, 1)
                if len(parts) > 1:
                    return parts[1].strip()

        # Clean specific technical junk observed in logs
        if "<njson" in content:
            content = re.sub(r'<njson.*?>', '', content, flags=re.DOTALL)
        if "to=functions" in content:
            content = re.sub(r'to=functions\.[a-zA-Z0-9_]+', '', content)

        # Remove standalone JSON blocks if mixed with text
        # This regex matches { "key": ... } blocks
        if "{" in content and "}" in content:
             content = re.sub(r'\{.*"query":.*\}', '', content, flags=re.DOTALL)

        # If content starts with obvious reasoning traces, try to extract the substantive part
        lines = content.split("\n")
        # Filter out lines that look like internal reasoning
        reasoning_keywords = [
            "I need to call",
            "Let's do.",
            "I'll call",
            "Let me try",
            "Actually tools not listed",
            "I think function name is",
            "Oops I need function",
            "This is going nowhere",
            "Given issue",
            "Oops formatting",
            "Need proper function call",
            "Actually tool calling",
            "Actually same mistake"
        ]

        filtered_lines = []
        for line in lines:
            if not any(keyword.lower() in line.lower() for keyword in reasoning_keywords):
                filtered_lines.append(line)

        filtered_content = "\n".join(filtered_lines).strip()

        # Only return filtered if it's substantially different and not empty
        if filtered_content and len(filtered_content) > 10:
            return filtered_content

        return content

# Global instance
agent = ChatAgent()
