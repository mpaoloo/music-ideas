"""Локальный веб-сервис: библиотека, аудио и AI-помощник."""
import json
import re
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from app.agent import AgentError, run_agent
from app.llm import ChatModel, LLMError
from app.mcp_client import PROJECT_ROOT, connect_mcp

load_dotenv(PROJECT_ROOT / '.env')
UPLOADS = PROJECT_ROOT / 'uploads'
MAX_AUDIO_BYTES = 20 * 1024 * 1024
AUDIO_NAME = re.compile(r'^[0-9a-f]{32}\.(mp3|wav|m4a|ogg)$')


class Card(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    instrument: str | None = Field(default=None, max_length=100)
    mood: str | None = Field(default=None, max_length=100)
    bpm: int | None = Field(default=None, gt=0)
    tags: list[str] = Field(default_factory=list, max_length=30)
    audio_path: str | None = None


def error(message, status=400):
    return JSONResponse({'error': message}, status_code=status)


async def index(request):
    return FileResponse(Path(__file__).parent / 'static' / 'index.html')


async def library(request):
    async with connect_mcp() as client:
        result = await client.call_tool('search_ideas', {'query': request.query_params.get('q', '')})
        if result.isError:
            return error('Не удалось прочитать библиотеку.', 502)
        return JSONResponse(result.structuredContent)


async def create(request):
    try:
        card = Card.model_validate(await request.json())
    except (ValueError, ValidationError):
        return error('Проверь поля: название обязательно, BPM — положительное целое число.')
    if card.audio_path and (not AUDIO_NAME.fullmatch(card.audio_path)
                            or not (UPLOADS / card.audio_path).is_file()):
        return error('Аудиофайл не найден. Загрузи файл заново.')
    async with connect_mcp() as client:
        result = await client.call_tool('create_idea', card.model_dump())
        if result.isError:
            return error('Не удалось сохранить карточку. Проверь название и BPM.')
        return JSONResponse(result.structuredContent, status_code=201)


async def delete(request):
    # Этот маршрут вызывается интерфейсом только после явного подтверждения.
    async with connect_mcp() as client:
        result = await client.call_tool('delete_idea', {'idea_id': request.path_params['idea_id']})
        if result.isError:
            return error('Не удалось удалить карточку.', 502)
        if not result.structuredContent['deleted']:
            return error('Карточка уже удалена или не существует.', 404)
        return JSONResponse({'deleted': True})


async def upload(request):
    # Тело запроса — сам файл, без multipart-обёртки. Ограничиваем размер по мере чтения.
    extension = request.headers.get('x-audio-extension', '').lower()
    if extension not in {'mp3', 'wav', 'm4a', 'ogg'}:
        return error('Поддерживаются MP3, WAV, M4A и OGG.')
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / f'{uuid4().hex}.{extension}'
    size = 0
    complete = False
    try:
        with path.open('wb') as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    return error('Максимальный размер файла — 20 МБ.', 413)
                target.write(chunk)
        if size == 0:
            return error('Файл пуст.')
        complete = True
        return JSONResponse({'audio_path': path.name}, status_code=201)
    finally:
        if not complete:
            path.unlink(missing_ok=True)


async def audio(request):
    name = request.path_params['name']
    if not AUDIO_NAME.fullmatch(name) or not (UPLOADS / name).is_file():
        return error('Файл не найден.', 404)
    return FileResponse(UPLOADS / name)


async def ask(request):
    try:
        body = await request.json()
        text = body.get('text') if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip() or len(text) > 5000:
            return error('Введи запрос от 1 до 5000 символов.')
        model = ChatModel.from_env()
    except ValueError:
        return error('Ожидается JSON с полем text.')
    except LLMError as exc:
        return error('AI-помощник пока не подключён. Ты можешь добавлять наброски вручную и искать их в библиотеке.', 503)
    async with connect_mcp() as client:
        try:
            result = await run_agent(text, model, client)
            # Путь к аудио задаёт приложение после загрузки, не модель.
            if result.pending_create:
                result.pending_create.pop('audio_path', None)
            return JSONResponse(asdict(result))
        except LLMError:
            return error('Помощник сейчас недоступен. Попробуй позже. Библиотека и сохранение записей продолжают работать.', 502)
        except AgentError:
            return error('Не удалось обработать запрос. Попробуй уточнить инструмент, настроение или темп.', 422)


async def unexpected_error(request, exc):
    return error('Внутренняя ошибка сервиса. Повтори запрос; подробности в журнале сервера.', 500)


app = Starlette(routes=[
    Route('/', index), Route('/api/ideas', library),
    Route('/api/ideas', create, methods=['POST']),
    Route('/api/ideas/{idea_id}', delete, methods=['DELETE']),
    Route('/api/upload', upload, methods=['POST']),
    Route('/api/ask', ask, methods=['POST']),
    Route('/audio/{name}', audio),
], exception_handlers={Exception: unexpected_error})
