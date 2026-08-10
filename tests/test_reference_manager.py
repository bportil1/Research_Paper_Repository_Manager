from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from reference_manager import ReferenceManager


class ReferenceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "TopicA").mkdir()
        (self.root / "TopicA" / "one.pdf").write_bytes(b"%PDF fake")
        (self.root / "TopicA" / "two.pdf").write_bytes(b"%PDF fake2")
        self.manager = ReferenceManager(self.root)
        self.manager.sync(detect_moves=False, extract_titles=False)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_sync_and_report_round_trip(self) -> None:
        rows = self.manager.list_papers()
        self.assertEqual(2, len(rows))
        rows[0]["Title"] = "Example Paper"
        self.manager.save_papers(rows)
        self.assertEqual("Example Paper", self.manager.get_paper(rows[0]["PaperID"])["Title"])

    def test_move_archive_restore(self) -> None:
        paper_id = self.manager.list_papers()[0]["PaperID"]
        moved = self.manager.move_paper(paper_id, "TopicB")
        self.assertEqual("TopicB", moved["Topic"])
        self.assertTrue(Path(moved["Path"]).exists())

        archived = self.manager.archive_paper(paper_id)
        self.assertEqual("Deleted", archived["FileState"])
        self.assertTrue(Path(archived["Path"]).exists())

        restored = self.manager.restore_paper(paper_id)
        self.assertEqual("Present", restored["FileState"])
        self.assertTrue(Path(restored["Path"]).exists())

    def test_bibtex_and_csv_imports(self) -> None:
        rows = self.manager.list_papers()
        rows[0]["Title"] = "Example Paper"
        self.manager.save_papers(rows)

        bib = "@article{x, title={Example Paper}, author={A. Author}, year={2026}}"
        bib_result = self.manager.import_bibtex_text(bib)
        self.assertEqual(1, bib_result["entries"])

        csv_result = self.manager.import_csv(io.BytesIO(b"Title,Status\nExample Paper,Read\n"))
        self.assertEqual(1, csv_result["rows_imported"])

    def test_history_checkpoints_and_duplicates_are_available(self) -> None:
        self.assertIsInstance(self.manager.find_duplicates(), list)
        self.assertTrue(self.manager.checkpoints())
        self.assertTrue(self.manager.history())


if __name__ == "__main__":
    unittest.main()
