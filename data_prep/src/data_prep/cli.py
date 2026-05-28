"""CLI entry point for data-prep pipeline."""

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from data_prep.pipeline import PipelineConfig, PreparationPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-prep",
        description="Data preparation pipeline: profile -> normalize -> plan -> run",
    )
    subparsers = parser.add_subparsers(dest="command", help="Pipeline stage to run")

    # -- profile --
    profile_p = subparsers.add_parser("profile", help="Scan data directory with TDV profiler")
    profile_p.add_argument("data_dir", help="Path to data directory")
    profile_p.add_argument("-o", "--output-dir", default="output", help="Output directory")
    profile_p.add_argument("-v", "--verbose", action="store_true")

    # -- normalize --
    norm_p = subparsers.add_parser("normalize", help="Run entity normalization on discriminator columns")
    norm_p.add_argument("data_dir", help="Path to data directory")
    norm_p.add_argument("-o", "--output-dir", default="output", help="Output directory")
    norm_p.add_argument("--mode", choices=["rules", "llm"], default="rules",
                        help="Classification mode (default: rules)")
    norm_p.add_argument("--rules", help="Path to classification rules JSON")
    norm_p.add_argument("--threshold", type=int, default=80,
                        help="Fuzzy clustering threshold 0-100 (default: 80)")
    norm_p.add_argument("--columns", nargs="+", default=[],
                        help="Columns to normalize (overrides profiler auto-detect)")
    norm_p.add_argument("--skip-columns", nargs="+", default=[],
                        help="Discriminator columns to skip")
    norm_p.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Anthropic model for LLM mode (default: claude-sonnet-4-20250514)")
    norm_p.add_argument("-v", "--verbose", action="store_true")

    # -- plan --
    plan_p = subparsers.add_parser("plan", help="Build a DataPlan from TDV + norm graphs")
    plan_p.add_argument("data_dir", help="Path to data directory")
    plan_p.add_argument("-o", "--output-dir", default="output", help="Output directory")
    plan_p.add_argument("--datasets", nargs="+", help="Specific dataset IDs to include")
    plan_p.add_argument("-v", "--verbose", action="store_true")

    # -- run --
    run_p = subparsers.add_parser("run", help="Run full pipeline (profile + normalize + plan)")
    run_p.add_argument("data_dir", help="Path to data directory")
    run_p.add_argument("-o", "--output-dir", default="output", help="Output directory")
    run_p.add_argument("--mode", choices=["rules", "llm"], default="rules",
                       help="Classification mode (default: rules)")
    run_p.add_argument("--rules", help="Path to classification rules JSON")
    run_p.add_argument("--threshold", type=int, default=80,
                       help="Fuzzy clustering threshold 0-100 (default: 80)")
    run_p.add_argument("--columns", nargs="+", default=[],
                       help="Columns to normalize (overrides profiler auto-detect)")
    run_p.add_argument("--skip-columns", nargs="+", default=[],
                       help="Discriminator columns to skip")
    run_p.add_argument("--manifest-out", help="Write generated manifest YAML to this path")
    run_p.add_argument("--model", default="claude-sonnet-4-20250514",
                       help="Anthropic model for LLM mode (default: claude-sonnet-4-20250514)")
    run_p.add_argument("-v", "--verbose", action="store_true")

    return parser


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _make_llm_classify_fn(model: str = "claude-sonnet-4-20250514"):
    """Create an LLM classification function using the Anthropic API."""
    try:
        from anthropic import Anthropic
    except ImportError:
        print("Error: anthropic package required for --mode llm")
        print("Install with: uv pip install 'data-prep[llm]'")
        sys.exit(1)

    client = Anthropic()
    logger = logging.getLogger("data-prep.llm")

    def classify(prompt: str) -> str:
        logger.info("Calling %s for hierarchy classification...", model)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        logger.debug("LLM response: %s", text[:200])
        return text

    return classify


def _build_config(args) -> PipelineConfig:
    """Build PipelineConfig from parsed CLI args."""
    config = PipelineConfig(
        data_lake_dir=args.data_dir,
        output_dir=args.output_dir,
    )

    if hasattr(args, 'mode') and args.mode:
        config.normalization_mode = args.mode
    if hasattr(args, 'threshold') and args.threshold:
        config.fuzzy_threshold = args.threshold
    if hasattr(args, 'columns') and args.columns:
        config.normalize_columns = args.columns
    if hasattr(args, 'skip_columns') and args.skip_columns:
        config.skip_columns = args.skip_columns
    if hasattr(args, 'rules') and args.rules:
        config.rules_path = args.rules

    # Wire up LLM classify function when mode is llm
    if config.normalization_mode == "llm":
        model = getattr(args, 'model', None) or "claude-sonnet-4-20250514"
        config.llm_classify_fn = _make_llm_classify_fn(model)

    return config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    _setup_logging(getattr(args, 'verbose', False))

    config = _build_config(args)
    pipeline = PreparationPipeline(config)

    if args.command == "profile":
        result = pipeline.run_stage1_profile()
        print(f"\nProfile complete:")
        print(f"  Graph:          {result['graph_path']}")
        print(f"  Datasets:       {result['datasets']}")
        print(f"  Discriminators: {result['discriminators']}")
        print(f"  Hierarchies:    {result['hierarchies']}")

    elif args.command == "normalize":
        result = pipeline.run_stage2_normalize()
        print(f"\nNormalization complete:")
        print(f"  Columns normalized: {result['columns_normalized']}")
        for col, info in result.get('columns', {}).items():
            summary = info['summary']
            print(f"  {col}: {summary['raw_values']} raw -> {summary['canonical_entities']} canonical")

    elif args.command == "plan":
        plan = pipeline.run_stage3_plan(dataset_ids=getattr(args, 'datasets', None))
        print(plan.describe())

    elif args.command == "run":
        # Run all stages
        print("Stage 1: Profiling...")
        profile_result = pipeline.run_stage1_profile()
        print(f"  {profile_result['datasets']} datasets, "
              f"{profile_result['discriminators']} discriminators")

        print("\nStage 2: Normalizing...")
        norm_result = pipeline.run_stage2_normalize()
        print(f"  {norm_result['columns_normalized']} columns normalized")

        print("\nStage 3: Building plan...")
        plan = pipeline.run_stage3_plan()
        print(plan.describe())

        # Generate manifest
        manifest = pipeline.generate_manifest(plan)
        manifest_path = getattr(args, 'manifest_out', None)
        if manifest_path:
            with open(manifest_path, 'w') as f:
                yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)
            print(f"\nManifest written to: {manifest_path}")
        else:
            # Print to stdout
            print("\n--- Generated Manifest ---")
            print(yaml.dump(manifest, default_flow_style=False, sort_keys=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
