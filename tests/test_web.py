import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.main import app
from app.llm import LLMError


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def test_library_upload_and_create_through_mcp(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'IDEAS_DB_PATH': str(Path(folder) / 'test.sqlite3')}), patch('app.main.UPLOADS', Path(folder) / 'uploads'):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                    page = await client.get('/')
                    self.assertEqual(page.status_code, 200)
                    self.assertIn('AI-помощник', page.text)
                    # Минимальный WAV: заголовок и один пустой аудиосэмпл.
                    import io
                    import wave
                    buffer = io.BytesIO()
                    with wave.open(buffer, 'wb') as audio:
                        audio.setnchannels(1)
                        audio.setsampwidth(2)
                        audio.setframerate(8000)
                        audio.writeframes(b'\x00\x00')
                    payload = buffer.getvalue()
                    uploaded = await client.post('/api/upload', content=payload, headers={'x-audio-extension': 'wav'})
                    self.assertEqual(uploaded.status_code, 201)
                    name = uploaded.json()['audio_path']
                    saved = await client.post('/api/ideas', json={'title': 'Гитарный рифф', 'bpm': 95, 'audio_path': name})
                    self.assertEqual(saved.status_code, 201)
                    library = await client.get('/api/ideas?q=РИФФ')
                    self.assertEqual(library.json()['count'], 1)
                    self.assertEqual(library.json()['ideas'][0]['id'], saved.json()['id'])
                    played = await client.get('/audio/' + name)
                    self.assertEqual(played.content, payload)
                    partial = await client.get('/audio/' + name, headers={'Range': 'bytes=0-3'})
                    self.assertEqual(partial.status_code, 206)
                    self.assertEqual(partial.content, payload[:4])
                    invalid = await client.post('/api/ideas', json={'title': 'Ошибка', 'audio_path': '../.env'})
                    self.assertEqual(invalid.status_code, 400)
                    unsupported = await client.post('/api/upload', content=b'data', headers={'x-audio-extension': 'html'})
                    self.assertEqual(unsupported.status_code, 400)
                    empty = await client.post('/api/upload', content=b'', headers={'x-audio-extension': 'mp3'})
                    self.assertEqual(empty.status_code, 400)
                    with patch('app.main.MAX_AUDIO_BYTES', 2):
                        oversized = await client.post('/api/upload', content=b'123', headers={'x-audio-extension': 'wav'})
                    self.assertEqual(oversized.status_code, 413)
                    self.assertEqual(len(list((Path(folder) / 'uploads').iterdir())), 1)

    async def test_missing_model_configuration(self):
        with patch('app.main.ChatModel.from_env', side_effect=LLMError('Укажи LLM_API_KEY и LLM_MODEL в .env.')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.post('/api/ask', json={'text': 'Найди рифф'})
                self.assertEqual(response.status_code, 503)
                self.assertIn('пока не подключён', response.json()['error'])
                self.assertNotIn('LLM_API_KEY', response.json()['error'])

    async def test_delete_card_preserves_other_cards_and_handles_repeated_request(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'IDEAS_DB_PATH': str(Path(folder) / 'test.sqlite3')}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                    first = (await client.post('/api/ideas', json={'title': 'Удалить'})).json()
                    other = (await client.post('/api/ideas', json={'title': 'Оставить'})).json()
                    self.assertEqual((await client.delete('/api/ideas/' + first['id'])).status_code, 200)
                    self.assertEqual((await client.delete('/api/ideas/' + first['id'])).status_code, 404)
                    remaining = (await client.get('/api/ideas')).json()['ideas']
                    self.assertEqual([card['id'] for card in remaining], [other['id']])
