"""Хранение карточек музыкальных идей. Не требует сторонних библиотек."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass
class Idea:
    id: str
    title: str
    description: str
    instrument: str | None
    mood: str | None
    bpm: int | None
    tags: list[str]
    audio_path: str | None
    created_at: str


class IdeaStorage:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS ideas (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    instrument TEXT,
                    mood TEXT,
                    bpm INTEGER CHECK (bpm > 0),
                    tags TEXT NOT NULL,
                    audio_path TEXT,
                    created_at TEXT NOT NULL
                )
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _to_idea(row: sqlite3.Row) -> Idea:
        fields = dict(row)
        fields["tags"] = json.loads(fields["tags"])
        return Idea(**fields)

    @staticmethod
    def _validate_bpm(value: int | None) -> None:
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError("BPM должен быть положительным целым числом.")

    def create_idea(
        self,
        title: str,
        description: str = "",
        *,
        instrument: str | None = None,
        mood: str | None = None,
        bpm: int | None = None,
        tags: list[str] | None = None,
        audio_path: str | None = None,
    ) -> Idea:
        """Сохранить карточку. audio_path — только путь, файл здесь не создаётся."""
        title = title.strip()
        if not title:
            raise ValueError("Название не должно быть пустым.")
        self._validate_bpm(bpm)
        # Убираем пустые и повторяющиеся теги, сохраняя порядок.
        clean_tags = list(dict.fromkeys(tag.strip() for tag in (tags or []) if tag.strip()))
        idea = Idea(
            id=str(uuid4()),
            title=title,
            description=description.strip(),
            instrument=(instrument or "").strip() or None,
            mood=(mood or "").strip() or None,
            bpm=bpm,
            tags=clean_tags,
            audio_path=audio_path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO ideas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    idea.id, idea.title, idea.description, idea.instrument,
                    idea.mood, idea.bpm, json.dumps(idea.tags, ensure_ascii=False),
                    idea.audio_path, idea.created_at,
                ),
            )
        return idea

    def get_idea(self, idea_id: str) -> Idea | None:
        """Вернуть карточку или None, если такого ID нет."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ideas WHERE id = ?", (idea_id,)
            ).fetchone()
        return self._to_idea(row) if row else None

    def search_ideas(
        self,
        query: str = "",
        *,
        instrument: str | None = None,
        mood: str | None = None,
        bpm_min: int | None = None,
        bpm_max: int | None = None,
    ) -> list[Idea]:
        """Все фильтры действуют одновременно. Границы BPM включаются.

        query ищет буквальную подстроку в названии, описании и тегах.
        Инструмент и настроение сравниваются целиком, без учёта регистра.
        Пустой запрос без фильтров возвращает всю библиотеку, новые записи первыми.
        """
        self._validate_bpm(bpm_min)
        self._validate_bpm(bpm_max)
        if bpm_min is not None and bpm_max is not None and bpm_min > bpm_max:
            raise ValueError("Нижняя граница BPM не может быть больше верхней.")

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ideas ORDER BY created_at DESC, id DESC"
            ).fetchall()

        # Для маленькой учебной библиотеки фильтруем в Python:
        # casefold корректно работает и с русским текстом.
        query = query.strip().casefold()
        instrument = (instrument or "").strip().casefold()
        mood = (mood or "").strip().casefold()
        result = []
        for row in rows:
            idea = self._to_idea(row)
            if instrument and (idea.instrument or "").casefold() != instrument:
                continue
            if mood and (idea.mood or "").casefold() != mood:
                continue
            if bpm_min is not None and (idea.bpm is None or idea.bpm < bpm_min):
                continue
            if bpm_max is not None and (idea.bpm is None or idea.bpm > bpm_max):
                continue
            text = " ".join([idea.title, idea.description, *idea.tags]).casefold()
            if query and query not in text:
                continue
            result.append(idea)
        return result
