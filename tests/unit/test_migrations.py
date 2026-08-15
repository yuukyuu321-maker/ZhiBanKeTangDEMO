import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "textbook-knowledge-api"))

from app.migrations import (  # noqa: E402
    MigrationStateError,
    discover_migrations,
    migration_body,
)


class MigrationTests(unittest.TestCase):
    def test_discovers_ordered_migrations_and_checksums_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "0002_second.sql").write_text("SELECT 2;\n", encoding="utf-8")
            (root / "0001_first.sql").write_text("SELECT 1;\n", encoding="utf-8")
            migrations = discover_migrations(root)
        self.assertEqual([item.version for item in migrations], ["0001", "0002"])
        self.assertNotEqual(migrations[0].sha256, migrations[1].sha256)

    def test_rejects_duplicate_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")
            (root / "0001_other.sql").write_text("SELECT 2;", encoding="utf-8")
            with self.assertRaisesRegex(MigrationStateError, "duplicate"):
                discover_migrations(root)

    def test_strips_only_outer_transaction_wrapper(self) -> None:
        self.assertEqual(
            migration_body("BEGIN;\nCREATE TABLE example (id integer);\nCOMMIT;"),
            "CREATE TABLE example (id integer);",
        )
        self.assertEqual(migration_body("SELECT 1;"), "SELECT 1;")


if __name__ == "__main__":
    unittest.main()
