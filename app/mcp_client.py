"""Соединение приложения с отдельным процессом MCP-сервера."""

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def connect_mcp(database_path: str | Path | None = None) -> AsyncIterator[ClientSession]:
    """Запустить сервер, установить MCP-сессию, закрыть её и процесс при выходе."""
    environment = dict(os.environ)
    if database_path is not None:
        environment["IDEAS_DB_PATH"] = str(Path(database_path).resolve())
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT),
        env=environment,
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(
            read_stream, write_stream, read_timeout_seconds=timedelta(seconds=15)
        ) as session:
            await session.initialize()
            yield session
