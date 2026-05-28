"""CLI entry point for batch runner."""

import argparse
import sys
import uuid
from datetime import date
from pathlib import Path

from circuit_core.batch_runner.manifest import load_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="batch-runner",
        description="Pre-compute signal discovery baselines from a YAML manifest. "
        "Runs layer0 (load/clean/segment) sequentially, then parallelizes "
        "layer1 (baseline/deviations) across processes.",
    )
    parser.add_argument(
        "manifest",
        help="Path to the YAML manifest file (e.g. scenarios.yaml)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="reports",
        help="Base output directory (default: reports/)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers for layer1 (default: 4)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        metavar="NAME",
        help="Run only these scenarios (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifest and print execution plan without running",
    )
    parser.add_argument(
        "--correlate",
        action="store_true",
        help="Run cross-segment correlation after baselines (overrides manifest)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load and validate manifest
    try:
        manifest = load_manifest(args.manifest)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Filter scenarios if requested
    if args.scenarios:
        available = {s.name for s in manifest.scenarios}
        unknown = set(args.scenarios) - available
        if unknown:
            print(f"Error: unknown scenarios: {unknown}. Available: {available}", file=sys.stderr)
            return 1
        manifest.scenarios = [s for s in manifest.scenarios if s.name in args.scenarios]

    # Generate run directory
    run_id = f"{date.today().isoformat()}-{uuid.uuid4().hex[:8]}"
    run_dir = Path(args.output_dir).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Print plan
    print(f"Manifest:    {args.manifest}")
    print(f"Data:        {manifest.data_path}")
    print(f"Dataset:     {manifest.dataset_name}")
    print(f"Timestamp:   {manifest.timestamp_col}")
    print(f"Freq:        {manifest.freq or 'auto-detect'}")
    print(f"Value cols:  {manifest.value_cols or 'auto-detect'}")
    print(f"Run dir:     {run_dir}")
    print(f"Workers:     {args.workers}")
    print(f"Scenarios:   {len(manifest.scenarios)}")
    for s in manifest.scenarios:
        seg_by = s.segment_by if isinstance(s.segment_by, list) else [s.segment_by]
        print(f"  - {s.name}: segment_by={seg_by}, min_size={s.min_segment_size}")
    if manifest.clean.apply_operations:
        print(f"Clean ops:   {len(manifest.clean.apply_operations)}")
    print(f"Deviations:  lookback={manifest.deviations.lookback_window}, "
          f"sensitivity={manifest.deviations.sensitivity}")
    print()

    if args.dry_run:
        print("Dry run complete. No data was processed.")
        return 0

    # Run the pipeline
    import logging

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    from circuit_core.batch_runner.runner import run_batch

    try:
        summary = run_batch(
            manifest=manifest,
            run_dir=run_dir,
            max_workers=args.workers,
        )
    except Exception as e:
        print(f"Error: batch run failed: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # Print summary
    print(f"\nBatch complete: {run_dir}")
    print(f"  Scenarios:  {summary['scenarios_completed']}/{summary['scenarios_total']}")
    print(f"  Segments:   {summary['segments_total']}")
    print(f"  Baselines:  {summary['baselines_succeeded']}/{summary['segments_total']}")
    print(f"  Deviations: {summary['deviations_succeeded']}/{summary['segments_total']}")
    if summary.get("errors"):
        print(f"  Errors:     {len(summary['errors'])}")
        for err in summary["errors"][:5]:
            print(f"    - {err}")
    print(f"  Duration:   {summary['duration_seconds']:.1f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
