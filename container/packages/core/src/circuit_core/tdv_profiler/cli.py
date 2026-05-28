"""CLI for TDV Profiler - scan a data directory and generate a graph file."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import networkx as nx

from circuit_core.tdv_profiler.profiler import DataLakeScanner, ColumnRole


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tdv-profiler",
        description="Scan a data directory and classify datasets by Time-Discriminator-Value pattern. "
        "Builds a discriminator relationship graph and writes it to a file.",
    )
    parser.add_argument(
        "directory",
        help="Path to the directory containing data files (CSV, Parquet, JSON)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="tdv_graph.json",
        help="Output file path (default: tdv_graph.json). "
        "Use .graphml for GraphML format, .json for JSON.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not scan subdirectories",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print the routing summary to stdout",
    )
    parser.add_argument(
        "--profiles",
        metavar="FILE",
        help="Write dataset profiles to a separate JSON file",
    )
    return parser


def graph_to_json(scanner: DataLakeScanner) -> dict:
    """Serialize the scanner's graph and metadata to a JSON-friendly dict."""
    graph = scanner.graph.graph

    nodes = []
    for node_id, data in graph.nodes(data=True):
        entry = {"id": node_id, **data}
        nodes.append(entry)

    edges = []
    for source, target, data in graph.edges(data=True):
        entry = {"source": source, "target": target, **data}
        edges.append(entry)

    return {
        "summary": scanner.graph.get_summary(),
        "graph": {
            "nodes": nodes,
            "edges": edges,
        },
    }


def generate_data_notes(scanner: DataLakeScanner) -> str:
    """Generate a data-notes.md template pre-populated with profiler findings."""
    lines = ["# Data Notes", "", "## Description", ""]

    # Build a brief dataset inventory
    summary = scanner.graph.get_summary()
    datasets = summary.get("datasets", [])
    if datasets:
        names = ", ".join(d["id"] for d in datasets)
        total_rows = sum(d.get("rows", 0) for d in datasets)
        lines.append(
            f"This data lake contains {len(datasets)} dataset(s) "
            f"({names}) with ~{total_rows:,} total rows."
        )
    else:
        lines.append("<!-- Describe what this data represents: industry, geography, time period, etc. -->")
    lines.append("")
    lines.append("<!-- Add context about the data source, business domain, and any relevant background. -->")

    # Datasets section
    lines.extend(["", "## Datasets", ""])
    for ds in datasets:
        grain = ds.get("time_grain", "unknown")
        time_col = ds.get("time_col", "?")
        sig = ds.get("signature", "?")
        discs = ", ".join(ds.get("discriminators", [])) or "none"
        vals = ", ".join(ds.get("values", [])) or "none"
        lines.append(f"### {ds['id']}")
        lines.append(f"- **Rows**: {ds.get('rows', '?'):,}")
        lines.append(f"- **Signature**: {sig}")
        lines.append(f"- **Time column**: `{time_col}` ({grain})")
        lines.append(f"- **Discriminators**: {discs}")
        lines.append(f"- **Value columns**: {vals}")
        lines.append("")

    # Normalizations section with auto-detected hints
    lines.extend(["## Normalizations", ""])
    lines.append("<!-- Review and edit these rules. The pipeline applies them during analysis. -->")
    lines.append("")

    # Auto-detect currency hints from value column stats
    for profile in scanner.profiles.values():
        for col in profile.columns:
            if col.role != ColumnRole.VALUE or not col.value_stats:
                continue
            stats = col.value_stats
            mean = stats.get("mean")
            if mean is not None and mean > 100:
                lines.append(
                    f"- `{col.name}` in **{profile.dataset_id}**: "
                    f"mean={mean:,.2f}, range=[{stats.get('min', '?'):,.2f}, {stats.get('max', '?'):,.2f}]. "
                    f"<!-- Are these cents? If so: convert to dollars (divide by 100). -->"
                )

    # Timezone hint from time columns
    time_cols_seen = set()
    for profile in scanner.profiles.values():
        for col in profile.columns:
            if col.role == ColumnRole.TIME and col.name not in time_cols_seen:
                time_cols_seen.add(col.name)
                grain = col.time_grain or "unknown"
                rng = f"{col.time_range[0]} to {col.time_range[1]}" if col.time_range else "?"
                lines.append(
                    f"- `{col.name}` ({grain}, {rng}): "
                    f"<!-- What timezone? e.g. 'Times are UTC, convert to PDT' -->"
                )

    lines.append("")
    lines.append("- Currency: <!-- e.g. USD, EUR, GBP -->")
    lines.append("")

    return "\n".join(lines)


def profiles_to_json(scanner: DataLakeScanner) -> list[dict]:
    """Serialize all dataset profiles to JSON-friendly dicts."""
    result = []
    for profile in scanner.profiles.values():
        d = {
            "dataset_id": profile.dataset_id,
            "source_path": profile.source_path,
            "row_count": profile.row_count,
            "is_temporal": profile.is_temporal,
            "tdv_signature": profile.tdv_signature,
            "primary_time_col": profile.primary_time_col,
            "discriminators": profile.discriminators,
            "values": profile.values,
            "columns": [c.to_dict() for c in profile.columns],
        }
        result.append(d)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"Error: '{directory}' is not a directory", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_format = output_path.suffix.lower()
    if output_format not in (".json", ".graphml"):
        print(
            f"Error: unsupported output format '{output_format}'. Use .json or .graphml",
            file=sys.stderr,
        )
        return 1

    # Scan
    scanner = DataLakeScanner()
    results = scanner.scan_directory(str(directory), recursive=not args.no_recursive)

    print(
        f"\nScanned {results['scanned']} datasets: "
        f"{results['temporal']} temporal, {results['non_temporal']} non-temporal"
    )
    if results["errors"]:
        print(f"  {len(results['errors'])} errors encountered")

    # Write graph
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == ".graphml":
        nx.write_graphml(scanner.graph.graph, str(output_path))
    else:
        data = graph_to_json(scanner)
        output_path.write_text(json.dumps(data, indent=2, default=str))

    print(f"Graph written to {output_path}")

    # Auto-generate data-notes.md alongside the graph (skip if already exists)
    notes_path = output_path.parent / "data-notes.md"
    if not notes_path.exists():
        notes_content = generate_data_notes(scanner)
        notes_path.write_text(notes_content)
        print(f"Data notes template written to {notes_path}")
    else:
        print(f"Data notes already exists at {notes_path} (not overwritten)")

    # Optional: write profiles
    if args.profiles:
        profiles_path = Path(args.profiles)
        profiles_path.parent.mkdir(parents=True, exist_ok=True)
        profiles_data = profiles_to_json(scanner)
        profiles_path.write_text(json.dumps(profiles_data, indent=2, default=str))
        print(f"Profiles written to {profiles_path}")

    # Optional: print summary
    if args.summary:
        print()
        print(scanner.get_routing_summary())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
