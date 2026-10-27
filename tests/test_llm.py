import unittest
from unittest.mock import patch

import httpx

from app.llm import ChatModel, LLMError


class LLMTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_request_format(self):
        def respond(request):
            self.assertEqual(str(request.url), "https://example.test/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            return httpx.Response(200, json={"choices": [{"message": {"content": "Ответ"}}]})

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch("app.llm.httpx.AsyncClient", return_value=http):
            result = await ChatModel("test-key", "https://example.test/v1", "test-model").complete([], [])
        self.assertEqual(result["content"], "Ответ")

    async def test_api_error_does_not_expose_response_body(self):
        http = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="secret-provider-details")
        ))
        with patch("app.llm.httpx.AsyncClient", return_value=http):
            with self.assertRaises(LLMError) as caught:
                await ChatModel("test-key", "https://example.test/v1", "test-model").complete([], [])
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("secret-provider-details", str(caught.exception))

    async def test_responses_tool_call_and_result_roundtrip(self):
        import json
        requests = []
        call = {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1',
                'name': 'search_ideas', 'arguments': '{}', 'status': 'completed'}
        def respond(request):
            self.assertTrue(str(request.url).endswith('/responses'))
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(200, json={'output': [call]})
            self.assertEqual(requests[-1]['input'][-2], call)
            self.assertEqual(requests[-1]['input'][-1]['type'], 'function_call_output')
            return httpx.Response(200, json={'output': [{
                'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'Записей нет.'}]
            }]})
        model = ChatModel('test-key', 'https://example.test/v1', 'gpt-6.1-terra')
        messages = [{'role': 'user', 'content': 'Поиск'}]
        for step in range(2):
            http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch('app.llm.httpx.AsyncClient', return_value=http):
                result = await model.complete(messages, [])
            if step == 0:
                self.assertEqual(result['tool_calls'][0]['function']['name'], 'search_ideas')
                messages.extend([result, {'role': 'tool', 'tool_call_id': 'call_1', 'content': '{}'}])
        self.assertEqual(result['content'], 'Записей нет.')
