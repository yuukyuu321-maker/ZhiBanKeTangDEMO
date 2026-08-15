"""Checksum-verified PostgreSQL migration runner."""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
_BASE_TABLES = frozenset(
    {
        "textbook_editions",
        "textbook_sources",
        "textbook_pages",
        "textbook_evidence",
        "teaching_groups",
        "principal_teaching_scopes",
        "textbook_assignments",
        "workspace_textbook_pins",
    }
)


class MigrationStateError(RuntimeError):
    pass


class MigrationChecksumError(MigrationStateError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    filename: str
    path: Path
    sha256: str
    sql: str


@dataclass(frozen=True, slots=True)
class MigrationReport:
    applied: tuple[str, ...]
    already_applied: tuple[str, ...]
    bootstrapped: tuple[str, ...]


def _checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def discover_migrations(directory: Path) -> tuple[Migration, ...]:
    root = directory.resolve(strict=True)
    migrations: list[Migration] = []
    seen_versions: set[str] = set()
    for path in sorted(root.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            continue
        version = match.group("version")
        if version in seen_versions:
            raise MigrationStateError(f"duplicate migration version: {version}")
        seen_versions.add(version)
        content = path.read_bytes()
        migrations.append(
            Migration(
                version=version,
                filename=path.name,
                path=path,
                sha256=_checksum(content),
                sql=content.decode("utf-8-sig"),
            )
        )
    if not migrations:
        raise MigrationStateError("no migration files were found")
    return tuple(migrations)


def migration_body(sql: str) -> str:
    lines = sql.strip().splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().upper() == "BEGIN;"
        and lines[-1].strip().upper() == "COMMIT;"
    ):
        return "\n".join(lines[1:-1]).strip()
    return sql.strip()


def _ensure_ledger(connection: psycopg.Connection[dict[str, object]]) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS athena_schema_migrations (
            version text PRIMARY KEY,
            filename text NOT NULL,
            sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def _applied(connection: psycopg.Connection[dict[str, object]]) -> dict[str, dict[str, object]]:
    rows = connection.execute(
        "SELECT version, filename, sha256, applied_at FROM athena_schema_migrations"
    ).fetchall()
    return {str(row["version"]): row for row in rows}


def _base_table_state(connection: psycopg.Connection[dict[str, object]]) -> set[str]:
    rows = connection.execute(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public' AND tablename = ANY(%s)
        """,
        (sorted(_BASE_TABLES),),
    ).fetchall()
    return {str(row["tablename"]) for row in rows}


def _bootstrap_existing_base(
    connection: psycopg.Connection[dict[str, object]],
    migrations: tuple[Migration, ...],
) -> tuple[str, ...]:
    existing = _base_table_state(connection)
    if not existing:
        return ()
    if existing != _BASE_TABLES:
        raise MigrationStateError(f"partial untracked base schema: {sorted(existing)}")
    first = next((item for item in migrations if item.version == "0001"), None)
    if first is None:
        raise MigrationStateError("existing base schema requires migration 0001")
    with connection.transaction():
        connection.execute(
            """
            INSERT INTO athena_schema_migrations (version, filename, sha256)
            VALUES (%s, %s, %s)
            ON CONFLICT (version) DO NOTHING
            """,
            (first.version, first.filename, first.sha256),
        )
    return (first.version,)


def apply_migrations(database_url: str, directory: Path) -> MigrationReport:
    if not database_url.strip():
        raise ValueError("database_url must not be blank")
    migrations = discover_migrations(directory)
    applied_now: list[str] = []
    bootstrapped: tuple[str, ...] = ()

    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as connection:
        _ensure_ledger(connection)
        tracked = _applied(connection)
        if not tracked:
            bootstrapped = _bootstrap_existing_base(connection, migrations)
            tracked = _applied(connection)

        for migration in migrations:
            recorded = tracked.get(migration.version)
            if recorded is not None:
                if str(recorded["sha256"]) != migration.sha256:
                    raise MigrationChecksumError(
                        f"migration checksum changed: {migration.filename}"
                    )
                continue
            with connection.transaction():
                connection.execute(migration_body(migration.sql), prepare=False)
                connection.execute(
                    """
                    INSERT INTO athena_schema_migrations (version, filename, sha256)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.filename, migration.sha256),
                )
            applied_now.append(migration.version)

        final = _applied(connection)
    return MigrationReport(
        applied=tuple(applied_now),
        already_applied=tuple(
            item.version
            for item in migrations
            if item.version in final and item.version not in applied_now
        ),
        bootstrapped=bootstrapped,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="athena-postgres-migrate")
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--migration-dir",
        type=Path,
        default=Path("deploy/postgres/migrations"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    report = apply_migrations(arguments.database_url, arguments.migration_dir)
    print(
        {
            "applied": list(report.applied),
            "already_applied": list(report.already_applied),
            "bootstrapped": list(report.bootstrapped),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
