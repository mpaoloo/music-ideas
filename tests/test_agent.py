import json
import tempfile
import unittest
from pathlib import Path

from app.agent import AgentError, run_agent
from app.mcp_client import connect_mcp


def tool_call(name, arguments):
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_1", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }]}


class ScriptedModel:
    """Подменяет только ответы модели; MCP и SQLite работают по-настоящему."""
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.requests = []

    async def complete(self, messages, tools):
        self.requests.append(json.loads(json.dumps({"messages": messages, "tools": tools})))
        return next(self.replies)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "ideas.sqlite3"

    async def test_search_result_is_sent_back_to_model(self):
        model = ScriptedModel(
            tool_call("search_ideas", {"instrument": "Гитара", "bpm_max": 110}),
            {"role": "assistant", "content": "Найден рифф для куплета."},
        )
        async with connect_mcp(self.database) as client:
            await client.call_tool("create_idea", {
                "title": "Рифф", "instrument": "Гитара", "bpm": 95,
            })
            result = await run_agent("Найди гитарные идеи до 110 BPM", model, client)
        self.assertEqual(result.trace[0]["result"]["count"], 1)
        returned = json.loads(model.requests[1]["messages"][-1]["content"])
        self.assertEqual(returned["ideas"][0]["title"], "Рифф")
        self.assertEqual(result.answer, "Найден рифф для куплета.")
        names = {tool["function"]["name"] for tool in model.requests[0]["tools"]}
        self.assertEqual(names, {"create_idea", "get_idea", "search_ideas", "delete_idea"})

    async def test_create_waits_for_confirmation_without_writing(self):
        model = ScriptedModel(tool_call("create_idea", {"title": "Новый рифф"}))
        async with connect_mcp(self.database) as client:
            result = await run_agent("Сохрани новый рифф", model, client)
            self.assertEqual(result.pending_create, {"title": "Новый рифф"})
            library = await client.call_tool("search_ideas", {})
            self.assertEqual(library.structuredContent["count"], 0)

    async def test_bad_arguments_and_unknown_tool_are_rejected(self):
        async with connect_mcp(self.database) as client:
            for call in (
                tool_call("search_ideas", {"bpm_max": "быстро"}),
                tool_call("delete_everything", {}),
                tool_call("search_ideas", {"invented_field": 1}),
            ):
                with self.assertRaises(AgentError):
                    await run_agent("Поиск", ScriptedModel(call), client)

    async def test_tool_error_is_returned_to_model(self):
        model = ScriptedModel(
            tool_call("search_ideas", {"bpm_min": 120, "bpm_max": 90}),
            {"content": "Нижняя граница больше верхней. Уточни диапазон."},
        )
        async with connect_mcp(self.database) as client:
            result = await run_agent("Поиск", model, client)
        self.assertTrue(result.trace[0]["is_error"])
        self.assertIn("error", json.loads(model.requests[1]["messages"][-1]["content"]))

    async def test_repeating_model_cannot_loop_forever(self):
        call = tool_call("search_ideas", {})
        async with connect_mcp(self.database) as client:
            with self.assertRaises(AgentError):
                await run_agent("Поиск", ScriptedModel(call, call), client, max_tool_calls=1)

    async def test_delete_is_only_proposed_until_confirmed(self):
        async with connect_mcp(self.database) as client:
            created = await client.call_tool('create_idea', {'title': 'Рифф'})
            idea = created.structuredContent
            model = ScriptedModel(tool_call('delete_idea', {'idea_id': idea['id']}))
            result = await run_agent('Удали рифф', model, client)
            self.assertEqual(result.pending_delete['id'], idea['id'])
            still_exists = await client.call_tool('get_idea', {'idea_id': idea['id']})
            self.assertTrue(still_exists.structuredContent['found'])
            deleted = await client.call_tool('delete_idea', {'idea_id': idea['id']})
            self.assertTrue(deleted.structuredContent['deleted'])
            again = await client.call_tool('delete_idea', {'idea_id': idea['id']})
            self.assertFalse(again.structuredContent['deleted'])

    async def test_delete_nonexistent_id_does_not_offer_confirmation(self):
        async with connect_mcp(self.database) as client:
            model = ScriptedModel(tool_call('delete_idea', {'idea_id': 'missing'}))
            with self.assertRaises(AgentError):
                await run_agent('Удали', model, client)
