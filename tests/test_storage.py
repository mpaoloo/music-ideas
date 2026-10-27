import tempfile
import unittest
from pathlib import Path

from mcp_server.storage import IdeaStorage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data" / "ideas.sqlite3"
        self.storage = IdeaStorage(self.path)

    def test_card_survives_reopening_database(self):
        idea = self.storage.create_idea(
            " Рифф для куплета ", "Попробовать перегруз",
            instrument="Гитара", mood="Мрачное", bpm=95,
            tags=[" рок ", "", "рок"], audio_path="uploads/riff.mp3",
        )
        reopened = IdeaStorage(self.path)
        saved = reopened.get_idea(idea.id)
        self.assertEqual(saved, idea)
        self.assertEqual(saved.title, "Рифф для куплета")
        self.assertEqual(saved.tags, ["рок"])
        self.assertIsNone(reopened.get_idea("missing"))

    def test_combined_filters_and_unknown_bpm(self):
        match = self.storage.create_idea(
            "Куплет", instrument="Гитара", mood="Мрачное", bpm=95, tags=["Рок"]
        )
        self.storage.create_idea("Быстрый", instrument="Гитара", mood="Мрачное", bpm=150)
        self.storage.create_idea("Без темпа", instrument="Гитара", mood="Мрачное")
        self.storage.create_idea("Синтезатор", instrument="Синтезатор", bpm=95)
        found = self.storage.search_ideas(
            "РОК", instrument="гитара", mood="мрачное", bpm_min=95, bpm_max=110
        )
        self.assertEqual([idea.id for idea in found], [match.id])
        self.assertEqual(len(self.storage.search_ideas()), 4)
        self.assertEqual(self.storage.search_ideas("несуществующая идея"), [])
        self.assertEqual(self.storage.search_ideas("' OR 1=1 --"), [])

    def test_invalid_input_does_not_create_cards(self):
        with self.assertRaises(ValueError):
            self.storage.create_idea("  ")
        for bpm in (0, -10, True, 95.5):
            with self.subTest(bpm=bpm), self.assertRaises(ValueError):
                self.storage.create_idea("Рифф", bpm=bpm)
        with self.assertRaises(ValueError):
            self.storage.search_ideas(bpm_min=120, bpm_max=90)
        self.assertEqual(self.storage.search_ideas(), [])


if __name__ == "__main__":
    unittest.main()
