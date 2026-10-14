from __future__ import annotations

import argparse
import json
from pathlib import Path

from .extractor import extract
from .models import ROOT, digest, read, schemas, workspace_path, write
from .project import export_preview, project, validate_projection
from .rf2 import import_rf2, RF2
from .vocabulary import expand_vocabulary, freeze_vocabulary, validate_vocabulary


def parser():
    root = argparse.ArgumentParser(prog="ontoward-snomed")
    commands = root.add_subparsers(dest="command", required=True)

    command = commands.add_parser("import", help="Import a local International RF2 Snapshot release")
    command.add_argument("--rf2", type=Path, required=True)
    command.add_argument("--release-date", required=True)
    command.add_argument("--language-refset", action="append", required=True)
    command.add_argument("--database", type=Path, required=True)

    command = commands.add_parser("expand-vocabulary", help="Create mapping and expansion packets")
    command.add_argument("--database", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--previous", type=Path)

    command = commands.add_parser("freeze-vocabulary", help="Freeze a fully reviewed vocabulary registry")
    command.add_argument("--database", type=Path, required=True)
    command.add_argument("--candidates", type=Path, required=True)
    command.add_argument("--review", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)

    command = commands.add_parser("project", help="Generate deterministic disease-target packets")
    command.add_argument("--database", type=Path, required=True)
    command.add_argument("--registry", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)

    command = commands.add_parser("extract", help="Prepare dry-run batches or explicitly run NOVA calls")
    command.add_argument("--database", type=Path, required=True)
    command.add_argument("--stage", choices=("vocabulary", "projection"), required=True)
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--output-dir", type=Path, required=True)
    command.add_argument("--registry", type=Path, help="Frozen vocabulary required for projection")
    command.add_argument("--live", action="store_true", help="Send real calls; dry-run is the default")
    command.add_argument("--max-calls", type=int)
    command.add_argument("--daily-remaining", type=int)
    command.add_argument("--ledger", type=Path, default=ROOT / "data/preparation/snomed/call-ledger.sqlite")

    command = commands.add_parser("validate", help="Validate the complete model response for one stage")
    command.add_argument("--database", type=Path, required=True)
    command.add_argument("--stage", choices=("vocabulary", "projection"), required=True)
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--response", type=Path, required=True)
    command.add_argument("--registry", type=Path, help="Frozen registry required for projection")
    command.add_argument("--output", type=Path, required=True)

    command = commands.add_parser("export-preview", help="Write isolated preview Turtle and provenance")
    command.add_argument("--database", type=Path, required=True)
    command.add_argument("--registry", type=Path, required=True)
    command.add_argument("--validated", type=Path, required=True)
    command.add_argument("--output-dir", type=Path, required=True)

    commands.add_parser("verify", help="Run the synthetic RF2 offline acceptance flow")
    return root


def open_rf2(path):
    return RF2(workspace_path(path))


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "verify":
        from .verify import run
        print(json.dumps(run(), indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "import":
        metadata = import_rf2(args.rf2, args.database, args.release_date, args.language_refset)
        database = workspace_path(args.database)
        output = database.parent / "release-manifest.json"
        write(output, metadata)
        for name, schema in schemas().items():
            write(database.parent / "schemas" / f"{name}.json", schema)
        print(json.dumps({"database": str(database.relative_to(ROOT)), "manifest": str(output.relative_to(ROOT)),
                          "dataset_id": metadata["dataset_id"], "files": len(metadata["files"])}, indent=2))
        return 0
    if args.command == "extract":
        rf2 = open_rf2(args.database)
        try:
            registry = read(args.registry) if args.registry else None
            report = extract(rf2, args.stage, read(args.input), args.output_dir, live=args.live,
                             max_calls=args.max_calls, daily_remaining=args.daily_remaining, ledger_path=args.ledger,
                             registry=registry)
        finally:
            rf2.close()
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "expand-vocabulary":
        rf2 = open_rf2(args.database)
        try:
            previous = read(args.previous) if args.previous else None
            result = expand_vocabulary(rf2, previous=previous)
        finally:
            rf2.close()
        write(args.output, result)
        print(json.dumps({"output": str(workspace_path(args.output).relative_to(ROOT)),
                          "packets": len(result["packets"]), "entries": len(result["entries"]),
                          "sha256": result["sha256"]}, indent=2))
        return 0
    if args.command == "freeze-vocabulary":
        rf2 = open_rf2(args.database)
        try:
            result = freeze_vocabulary(rf2, read(args.candidates), read(args.review))
        finally:
            rf2.close()
        write(args.output, result)
        print(json.dumps({"output": str(workspace_path(args.output).relative_to(ROOT)),
                          "entries": len(result["entries"]), "sha256": result["sha256"]}, indent=2))
        return 0
    if args.command == "project":
        rf2 = open_rf2(args.database)
        try:
            result = project(rf2, read(args.registry))
        finally:
            rf2.close()
        write(args.output, result)
        print(json.dumps({"output": str(workspace_path(args.output).relative_to(ROOT)),
                          "packets": len(result["packets"]), "sha256": result["sha256"]}, indent=2))
        return 0
    if args.command == "validate":
        rf2 = open_rf2(args.database)
        try:
            envelope, raw = read(args.input), read(args.response)
            if args.stage == "vocabulary":
                result = validate_vocabulary(rf2, envelope, raw)
            else:
                if not args.registry:
                    raise ValueError("--registry is required for projection validation")
                result = validate_projection(rf2, read(args.registry), envelope, raw)
        finally:
            rf2.close()
        write(args.output, result)
        print(json.dumps({"output": str(workspace_path(args.output).relative_to(ROOT)),
                          "decisions": len(result.get("entries", result.get("profiles", []))),
                          "sha256": result["sha256"]}, indent=2))
        return 0
    if args.command == "export-preview":
        rf2 = open_rf2(args.database)
        try:
            report = export_preview(rf2, read(args.registry), read(args.validated), args.output_dir)
        finally:
            rf2.close()
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    raise ValueError("Unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
