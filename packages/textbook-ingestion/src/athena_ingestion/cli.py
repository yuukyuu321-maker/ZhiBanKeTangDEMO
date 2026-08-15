"""Local command line interface for controlled textbook imports."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from athena_domain import TextbookEdition

from .importer import ImportRequest, TextbookImporter
from .models import RenderMode
from .postgres_activation import activate_and_assign_bundle, grant_principal_teaching_scope
from .postgres_registration import register_promoted_bundle
from .promotion import promote_bundle
from .review import record_review
from .review_sampling import write_review_plan
from .search import EvidenceIndex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="athena-textbook")
    commands = parser.add_subparsers(dest="command", required=True)

    import_command = commands.add_parser("import-pdf", help="create a reviewable import bundle")
    import_command.add_argument("--pdf", required=True, type=Path)
    import_command.add_argument("--output-root", required=True, type=Path)
    import_command.add_argument("--edition-id", required=True)
    import_command.add_argument("--subject", required=True)
    import_command.add_argument("--grade", required=True)
    import_command.add_argument("--volume", required=True)
    import_command.add_argument("--publisher", required=True)
    import_command.add_argument("--edition-label", required=True)
    import_command.add_argument("--source-origin", required=True)
    import_command.add_argument("--authorization-scope", required=True)
    import_command.add_argument("--uploader", required=True)
    import_command.add_argument(
        "--render-mode", choices=[mode.value for mode in RenderMode], default="all"
    )
    import_command.add_argument("--render-dpi", type=int, default=110)

    search_command = commands.add_parser("search", help="search an existing local import bundle")
    search_command.add_argument("--bundle", required=True, type=Path)
    search_command.add_argument("--query", required=True)
    search_command.add_argument("--limit", type=int, default=10)

    review_command = commands.add_parser("review", help="record a human import review")
    review_command.add_argument("--bundle", required=True, type=Path)
    review_command.add_argument("--decision-file", required=True, type=Path)

    plan_command = commands.add_parser(
        "plan-review", help="create a deterministic, non-mutating review sample"
    )
    plan_command.add_argument("--bundle", required=True, type=Path)
    plan_command.add_argument("--output-dir", required=True, type=Path)
    plan_command.add_argument("--minimum-warning-pages", type=int, default=20)
    plan_command.add_argument("--warning-ratio", type=float, default=0.10)

    promote_command = commands.add_parser(
        "promote", help="promote an approved candidate into the canonical import root"
    )
    promote_command.add_argument("--candidate", required=True, type=Path)
    promote_command.add_argument("--import-root", required=True, type=Path)
    promote_command.add_argument("--promoted-by", required=True)
    promote_command.add_argument("--archive-root", type=Path)

    register_command = commands.add_parser(
        "register-postgres", help="register one promoted canonical bundle in PostgreSQL"
    )
    register_command.add_argument("--bundle", required=True, type=Path)
    register_command.add_argument("--import-root", required=True, type=Path)
    register_command.add_argument("--database-url", required=True)
    register_command.add_argument("--school-id", required=True)
    register_command.add_argument("--registered-by", required=True)

    activate_command = commands.add_parser(
        "activate-and-assign-postgres",
        help="activate a registered textbook and assign it to one teaching scope",
    )
    activate_command.add_argument("--bundle", required=True, type=Path)
    activate_command.add_argument("--import-root", required=True, type=Path)
    activate_command.add_argument("--database-url", required=True)
    activate_command.add_argument("--school-id", required=True)
    activate_command.add_argument("--academic-year", required=True)
    activate_command.add_argument("--grade", required=True)
    activate_command.add_argument("--subject", required=True)
    activate_command.add_argument("--campus-id")
    activate_command.add_argument("--class-id")
    activate_command.add_argument("--valid-from", required=True, type=date.fromisoformat)
    activate_command.add_argument("--valid-until", type=date.fromisoformat)
    activate_command.add_argument("--decided-by", required=True)
    activate_command.add_argument("--reason", required=True)

    grant_command = commands.add_parser(
        "grant-teaching-scope-postgres",
        help="grant a principal access to an existing active teaching scope",
    )
    grant_command.add_argument("--database-url", required=True)
    grant_command.add_argument("--school-id", required=True)
    grant_command.add_argument("--academic-year", required=True)
    grant_command.add_argument("--grade", required=True)
    grant_command.add_argument("--subject", required=True)
    grant_command.add_argument("--campus-id")
    grant_command.add_argument("--class-id")
    grant_command.add_argument("--principal-id", required=True)
    grant_command.add_argument("--granted-by", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "import-pdf":
        edition = TextbookEdition(
            edition_id=arguments.edition_id,
            subject=arguments.subject,
            grade=arguments.grade,
            volume=arguments.volume,
            publisher=arguments.publisher,
            edition_label=arguments.edition_label,
        )
        result = TextbookImporter().import_pdf(
            ImportRequest(
                pdf_path=arguments.pdf,
                output_root=arguments.output_root,
                edition=edition,
                source_origin=arguments.source_origin,
                authorization_scope=arguments.authorization_scope,
                uploader=arguments.uploader,
                render_mode=RenderMode(arguments.render_mode),
                render_dpi=arguments.render_dpi,
            )
        )
        print(
            json.dumps(
                {
                    "bundle_path": str(result.bundle_path),
                    "reused": result.reused,
                    "report": result.report,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if arguments.command == "review":
        print(
            json.dumps(
                record_review(arguments.bundle, arguments.decision_file),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if arguments.command == "plan-review":
        plan = write_review_plan(
            arguments.bundle,
            arguments.output_dir,
            minimum_warning_pages=arguments.minimum_warning_pages,
            warning_ratio=arguments.warning_ratio,
        )
        print(
            json.dumps(
                {
                    "output_directory": str(arguments.output_dir.resolve()),
                    "summary": plan["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if arguments.command == "promote":
        result = promote_bundle(
            arguments.candidate,
            arguments.import_root,
            arguments.promoted_by,
            arguments.archive_root,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0

    if arguments.command == "register-postgres":
        result = register_promoted_bundle(
            arguments.bundle,
            arguments.import_root,
            arguments.database_url,
            arguments.school_id,
            arguments.registered_by,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0

    if arguments.command == "activate-and-assign-postgres":
        result = activate_and_assign_bundle(
            arguments.bundle,
            arguments.import_root,
            arguments.database_url,
            arguments.school_id,
            arguments.academic_year,
            arguments.grade,
            arguments.subject,
            arguments.valid_from,
            arguments.decided_by,
            arguments.reason,
            valid_until=arguments.valid_until,
            campus_id=arguments.campus_id,
            class_id=arguments.class_id,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0

    if arguments.command == "grant-teaching-scope-postgres":
        result = grant_principal_teaching_scope(
            arguments.database_url,
            arguments.school_id,
            arguments.academic_year,
            arguments.grade,
            arguments.subject,
            arguments.principal_id,
            arguments.granted_by,
            campus_id=arguments.campus_id,
            class_id=arguments.class_id,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0

    index = EvidenceIndex.from_bundle(arguments.bundle)
    results = index.search(arguments.query, arguments.limit)
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    return 0
