---
name: generate-pdf
description: >
  Export a markdown file to PDF using Jinja templates and WeasyPrint.
  Renders markdown through the template system and converts to PDF.
  Supports metadata like title, author, client, date via YAML frontmatter or arguments.
  Triggers: "export to pdf", "render pdf", "convert to pdf", "make pdf",
  "export document as pdf", "pdf export", "generate pdf".
---

# Export to PDF

Export markdown files to professionally styled PDF documents using Jinja2 templates and WeasyPrint.

## Usage

```
/export-to-pdf <markdown-file> [template] [options]
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `markdown-file` | Yes | - | Path to the source markdown file |
| `template` | No | `circuit-external` | Template directory name |

### Options (passed as context)

| Option | Description |
|--------|-------------|
| `--title` | Document title (overrides frontmatter) |
| `--subtitle` | Document subtitle or one-line description |
| `--author` | Author name (default: "John Carpenter, 2Lines Software") |
| `--client` | Client name (for external docs) |
| `--date` | Document date (default: today, e.g., "February 2026") |
| `--version` | Document version (default: "1.0") |
| `--classification` | Classification level (default: "Confidential") |
| `--output` | Output PDF file path (default: workspace/outputs/exports/<filename>.pdf) |

### Examples

```
/export-to-pdf clients/Circuit/proposal.md
/export-to-pdf research/technical-spike.md --title "Technical Analysis" --client "Acme Corp"
/export-to-pdf pipeline/rfp-response.md 2lines-external --output exports/proposal.pdf
```

## Output

Unlike `export-to-html` which creates a folder, `export-to-pdf` outputs a single PDF file:

```
clients/Circuit/proposal.md → workspace/outputs/exports/proposal.pdf
```

## Dependencies

Requires WeasyPrint for PDF rendering:

```bash
pip install weasyprint
```

On macOS, you may also need:
```bash
brew install pango
```

## Available Templates

| Template | Directory | Purpose |
|----------|-----------|---------|
| 2lines-external | `_templates/2lines-external/` | External documents (proposals, reports, deliverables) |

## Workflow

The PDF export follows the same workflow as HTML export, with an additional PDF rendering step:

### Step 1-5: Same as export-to-html

Parse arguments, read markdown, parse frontmatter, convert to HTML, build context.

### Step 6: Render Template to HTML String

```python
from jinja2 import Environment, FileSystemLoader

templates_dir = Path("/Users/john/Documents/Workspace/Agents/knowledge-worker-framework/workspace/_fixtures/_templates")
template_path = templates_dir / template_name

env = Environment(loader=FileSystemLoader(str(template_path)))
template = env.get_template('base.html')

html_string = template.render(**context)
```

### Step 7: Convert HTML to PDF with WeasyPrint

```python
from weasyprint import HTML, CSS

# Create HTML document with base_url for resolving relative paths (logo, css)
html_doc = HTML(string=html_string, base_url=str(template_path))

# Render to PDF
html_doc.write_pdf(output_path)
```

## Complete Render Function

```python
#!/usr/bin/env python3
"""Render markdown to PDF using templates and WeasyPrint."""

import re
from pathlib import Path
from datetime import date

import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

BASE_DIR = Path("/Users/john/Documents/Workspace/Agents/knowledge-worker-framework")
TEMPLATES_DIR = BASE_DIR / "workspace/_fixtures/_templates"


def export_to_pdf(
    markdown_file: str,
    template_name: str = "2lines-external",
    output_path: str = None,
    **options
) -> Path:
    """
    Export a markdown file to PDF.

    Args:
        markdown_file: Path to markdown file (relative to BASE_DIR or absolute)
        template_name: Template directory name
        output_path: Output PDF file path (optional)
        **options: Metadata options (title, author, client, etc.)

    Returns:
        Path to the generated PDF file
    """
    # Resolve markdown path
    md_path = Path(markdown_file)
    if not md_path.is_absolute():
        md_path = BASE_DIR / md_path

    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    # Read markdown content
    md_content = md_path.read_text()

    # Parse YAML frontmatter if present
    frontmatter = {}
    content = md_content

    if md_content.startswith('---'):
        match = re.match(r'^---\n(.*?)\n---\n', md_content, re.DOTALL)
        if match:
            try:
                import yaml
                frontmatter = yaml.safe_load(match.group(1)) or {}
            except:
                pass
            content = md_content[match.end():]

    # Convert markdown to HTML
    md = markdown.Markdown(extensions=[
        'tables',
        'fenced_code',
        'codehilite',
        'toc',
    ])
    html_content = md.convert(content)

    # Extract table of contents
    toc_html = md.toc

    # Build context (frontmatter, then options override)
    context = {
        **frontmatter,
        **{k: v for k, v in options.items() if v is not None},
        'content': html_content,
        'toc': toc_html,
    }

    # Set defaults
    if 'title' not in context:
        context['title'] = md_path.stem.replace('-', ' ').title()
    if 'date' not in context:
        context['date'] = date.today().isoformat()

    # Load and render template
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    env = Environment(loader=FileSystemLoader(str(template_path)))
    template = env.get_template('base.html')
    html_string = template.render(**context)

    # Determine output path
    if output_path:
        out_path = Path(output_path)
        if not out_path.is_absolute():
            out_path = BASE_DIR / out_path
    else:
        out_path = BASE_DIR / "workspace/outputs/exports" / (md_path.stem + '.pdf')

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to PDF using WeasyPrint
    # base_url allows WeasyPrint to resolve relative paths (logo.svg, style.css)
    html_doc = HTML(string=html_string, base_url=str(template_path) + '/')
    html_doc.write_pdf(out_path)

    return out_path
```

## Execution Steps

When the user invokes `/export-to-pdf`, execute:

1. **Parse the request** - Extract file path, template name, and options
2. **Verify dependencies** - Check that `markdown`, `jinja2`, and `weasyprint` are installed
3. **Run the export** - Use Bash to execute Python with the render logic
4. **Report results** - Show the output PDF path

## Error Handling

| Error | Response |
|-------|----------|
| File not found | Report error with suggestions for correct path |
| Template not found | List available templates |
| Missing dependencies | Show `pip install markdown jinja2 weasyprint` |
| WeasyPrint error | Show error message (often related to missing system fonts) |

## Output Format

After successful export:

```
Export Complete

Source: clients/Circuit/proposal.md
Template: 2lines-external
Output: clients/Circuit/proposal.pdf

Metadata:
  Title: Project Proposal
  Client: Circuit
  Date: 2026-02-12
  Classification: Confidential

Open PDF: open clients/Circuit/proposal.pdf
```

## Tips

- **YAML Frontmatter**: Add metadata directly in the markdown file
- **Print styles**: Templates include `@media print` and `@page` rules optimized for PDF
- **Page breaks**: Use `---` in markdown or add `<div class="page-break"></div>` for manual breaks
- **Fonts**: WeasyPrint uses system fonts; ensure required fonts are installed
- **Images**: Use absolute paths or paths relative to the template directory

## Troubleshooting

### WeasyPrint Installation Issues

**macOS:**
```bash
brew install pango libffi
pip install weasyprint
```

**Ubuntu/Debian:**
```bash
sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0
pip install weasyprint
```

### Font Issues

If fonts don't render correctly:
1. Install the required fonts system-wide
2. Or specify web-safe fallback fonts in the CSS

### Large Documents

For very large documents, WeasyPrint may be slow. Consider:
- Breaking into smaller sections
- Using `--optimize-images` flag (if supported)
