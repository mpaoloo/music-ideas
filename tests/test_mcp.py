"""Проверка настоящих MCP-вызовов через отдельный процесс и stdio."""

import tempfile
import unittest
from pathlib import Path

from app.mcp_client import connect_mcp


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_over_stdio(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ideas.sqlite3"
            async with connect_mcp(database) as client:
                tools = await client.list_tools()
                self.assertEqual(
                    {tool.name for tool in tools.tools},
                    {"create_idea", "get_idea", "search_ideas"},
                )
                created = await client.call_tool("create_idea", {
                    "title": "Рифф для куплета", "instrument": "Гитара",
                    "mood": "Мрачное", "bpm": 95, "tags": ["рок"],
                })
                self.assertFalse(created.isError)
                idea = created.structuredContent
                self.assertEqual(idea["title"], "Рифф для куплета")

                fetched = await client.call_tool("get_idea", {"idea_id": idea["id"]})
                self.assertEqual(fetched.structuredContent["idea"], idea)
                found = await client.call_tool("search_ideas", {
                    "instrument": "гитара", "bpm_min": 90, "bpm_max": 110,
                })
                self.assertEqual(found.structuredContent["ideas"], [idea])
                empty = await client.call_tool("search_ideas", {"bpm_min": 120})
                self.assertEqual(empty.structuredContent, {"ideas": [], "count": 0})
                missing = await client.call_tool("get_idea", {"idea_id": "missing"})
                self.assertEqual(missing.structuredContent, {"found": False, "idea": None})

                # Ошибка возвращается через MCP, соединение продолжает работать.
                invalid = await client.call_tool("create_idea", {"title": "  "})
                self.assertTrue(invalid.isError)
                invalid_range = await client.call_tool(
                    "search_ideas", {"bpm_min": 120, "bpm_max": 90}
                )
                self.assertTrue(invalid_range.isError)
                unchanged = await client.call_tool("search_ideas", {})
                self.assertEqual(unchanged.structuredContent["count"], 1)

            # Новый процесс сервера читает ту же сохранённую карточку.
            async with connect_mcp(database) as client:
                fetched = await client.call_tool("get_idea", {"idea_id": idea["id"]})
                self.assertEqual(fetched.structuredContent["idea"], idea)


if __name__ == "__main__":
    unittest.main()
