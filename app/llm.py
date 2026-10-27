"""HTTP-клиент модели с поддержкой Chat Completions и tool calling."""

import os

import httpx


class LLMError(RuntimeError):
    pass


class ChatModel:
    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key.strip() or not model.strip():
            raise LLMError("Укажи LLM_API_KEY и LLM_MODEL в .env.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("LLM_API_KEY", ""),
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            os.getenv("LLM_MODEL", ""),
        )

    async def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        # Для выбранной модели tool calling поддерживается через Responses API.
        responses_api = self.model == "gpt-6.1-terra"
        payload = {"model": self.model, "messages": messages, "tools": tools}
        if responses_api:
            items = []
            for message in messages:
                if message.get("_response_items") is not None:
                    items.extend(message["_response_items"])
                elif message["role"] == "tool":
                    items.append({"type": "function_call_output",
                                  "call_id": message["tool_call_id"], "output": message["content"]})
                else:
                    items.append({"role": message["role"], "content": message["content"]})
            payload = {"model": self.model, "input": items, "store": False,
                       "reasoning": {"effort": "none"}, "max_output_tokens": 1500,
                       "tools": [{"type": "function", **tool["function"], "strict": False} for tool in tools]}
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{self.base_url}/" + ("responses" if responses_api else "chat/completions"),
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            data = response.json()
            if responses_api:
                output = data["output"]
                message = {"role": "assistant", "_response_items": output,
                           "content": "".join(part["text"] for item in output
                                              if item["type"] == "message"
                                              for part in item["content"] if part["type"] == "output_text"),
                           "tool_calls": [{"id": item["call_id"], "type": "function",
                                           "function": {"name": item["name"], "arguments": item["arguments"]}}
                                          for item in output if item["type"] == "function_call"]}
            else:
                message = data["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            return message
        except httpx.HTTPStatusError as error:
            # Не выводим тело ответа: оно может содержать чувствительные данные.
            raise LLMError(
                f"API модели вернул HTTP {error.response.status_code}. "
                "Проверь адрес API, ключ, название модели и доступный баланс."
            ) from None
        except httpx.RequestError:
            raise LLMError("Не удалось связаться с API модели. Проверь соединение и адрес.") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("API модели вернул неожиданный формат ответа.") from None
