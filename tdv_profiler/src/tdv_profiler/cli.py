"""CLI for TDV Profiler - scan a data directory and generate a graph file."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import networkx as nx

from tdv_profiler.profiler import DataLakeScanner, ColumnRole


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
