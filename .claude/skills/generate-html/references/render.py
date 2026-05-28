#!/usr/bin/env python3
"""
Simple document renderer for testing templates.

Usage:
    python render.py <input.md> [--template <name>] [--output <file>] [options]

Examples:
    python render.py example.md
    python render.py proposal.md --title "Project Proposal" --client "Acme Corp"
    python render.py report.md --output report.html --confidential

Note: This script is a reference implementation for the export-to-html skill.
      It expects to be run from the knowledge-base root directory.
"""

import argparse
import sys
from pathlib import Path
from datetime import date

try:
    import markdown
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    print("Required packages not installed. Run:")
    print("  pip install markdown jinja2")
    sys.exit(1)

# Base paths
BASE_DIR = Path("/Users/john/Documents/Workspace/2Lines/knowledge-base")
TEMPLATES_DIR = BASE_DIR / "_templates"


def render_document(
    input_path: Path,
    template_dir: str = "2lines-external",
    template_name: str = "base.html",
    output_path: Path = None,
    **context
) -> str:
    """Render a markdown file to HTML using specified template."""

    # Setup Jinja environment
    template_path = TEMPLATES_DIR / template_dir

    if not template_path.exists():
        raise FileNotFoundError(f"Template directory not found: {template_path}")

    env = Environment(loader=FileSystemLoader(str(template_path)))
    template = env.get_template(template_name)

    # Read and convert markdown
    md_content = input_path.read_text()

    # Configure markdown extensions
    md = markdown.Markdown(extensions=[
        'tables',
        'fenced_code',
        'codehilite',
        'toc',
        'meta',
    ])

    html_content = md.convert(md_content)

    # Extract metadata from markdown front matter if present
    if hasattr(md, 'Meta'):
        for key, value in md.Meta.items():
            if key not in context:
                context[key] = value[0] if len(value) == 1 else value

    # Set defaults
    if 'title' not in context:
        # Use first H1 or filename as title
        context['title'] = input_path.stem.replace('-', ' ').title()

    if 'date' not in context:
        context['date'] = date.today().isoformat()

    # Render template
    output = template.render(content=html_content, **context)

    # Write output
    if output_path:
        output_path.write_text(output)
        print(f"Rendered: {output_path}")

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Render markdown to HTML using 2Lines templates"
    )
    parser.add_argument("input", help="Input markdown file")
    parser.add_argument(
        "--template-dir", "-t",
        default="2lines-external",
        help="Template directory (default: 2lines-external)"
    )
    parser.add_argument(
        "--template",
        default="base.html",
        help="Template file (default: base.html)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file (default: <input>.html)"
    )
    parser.add_argument("--title", help="Document title")
    parser.add_argument("--subtitle", help="Document subtitle")
    parser.add_argument("--author", help="Author name")
    parser.add_argument("--client", help="Client name")
    parser.add_argument("--date", help="Document date")
    parser.add_argument("--version", help="Document version")
    parser.add_argument(
        "--classification",
        default="Confidential",
        help="Classification level (default: Confidential)"
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Output to stdout instead of file"
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.stdout:
        output_path = None
    elif args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix('.html')

    # Build context from args
    context = {}
    for key in ['title', 'subtitle', 'author', 'client', 'date', 'version', 'classification']:
        value = getattr(args, key)
        if value:
            context[key] = value

    # Render
    output = render_document(
        input_path,
        template_dir=args.template_dir,
        template_name=args.template,
        output_path=output_path,
        **context
    )

    if args.stdout:
        print(output)


if __name__ == "__main__":
    main()
