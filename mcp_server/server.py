"""MCP-инструменты музыкального архива. Запуск: python -m mcp_server.server."""

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.storage import IdeaStorage


PROJECT_ROOT = Path(__file__).resolve().parents[1]
storage = IdeaStorage(
    os.environ.get("IDEAS_DB_PATH", str(PROJECT_ROOT / "data" / "ideas.sqlite3"))
)
mcp = FastMCP("Music Ideas")


@mcp.tool()
def create_idea(
    title: str,
    description: str = "",
    instrument: str | None = None,
    mood: str | None = None,
    bpm: int | None = None,
    tags: list[str] | None = None,
    audio_path: str | None = None,
) -> dict[str, Any]:
    """сохранить музыкальную идею после подтверждения пользователем

    Неизвестные поля оставляй пустыми. Названия инструментов и настроений
    записывай по-русски. audio_path — путь уже загруженного файла, не загрузка
    """
    idea = storage.create_idea(
        title, description, instrument=instrument, mood=mood,
        bpm=bpm, tags=tags, audio_path=audio_path,
    )
    return asdict(idea)


@mcp.tool()
def get_idea(idea_id: str) -> dict[str, Any]:
    """получить карточку по её реальному ID. Если её нет, found будет false"""
    idea = storage.get_idea(idea_id)
    return {"found": idea is not None, "idea": asdict(idea) if idea else None}


@mcp.tool()
def search_ideas(
    query: str = "",
    instrument: str | None = None,
    mood: str | None = None,
    bpm_min: int | None = None,
    bpm_max: int | None = None,
) -> dict[str, Any]:
    """Найти музыкальные идеи. Все фильтры действуют одновременно.

    query — буквальная подстрока в названии, описании и тегах, не весь запрос
    пользователя. Инструмент и настроение — полное совпадение без учёта
    регистра, названия по-русски. Границы BPM включаются. Неизвестный BPM
    не подходит под диапазон. Без параметров возвращается вся библиотека.
    """
    ideas = storage.search_ideas(
        query, instrument=instrument, mood=mood, bpm_min=bpm_min, bpm_max=bpm_max
    )
    return {"ideas": [asdict(idea) for idea in ideas], "count": len(ideas)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
