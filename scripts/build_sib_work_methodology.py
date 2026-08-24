#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = Path("/home/ubuntu/uploads/methodeSibWork")
DEFAULT_SOURCE_MD = DEFAULT_SOURCE_DIR / "Methode Projet Sib Work.md"
DEFAULT_SUMMARY_IMAGE = DEFAULT_SOURCE_DIR / "GraphSibWorkResumé.png"
ASSET_DIR = REPO_ROOT / "web" / "assets" / "methodology"
OUTPUT_HTML = REPO_ROOT / "web" / "data" / "sib-work-methodology.html"

IMAGE_ALT = {
    "1": "Schéma explicatif du modèle SIB Risques",
    "2": "Courbes de vulnérabilité utilisées dans le modèle",
    "3": "Carte de zonage des réseaux de la Guadeloupe",
}


def extract_embedded_images(markdown: str, asset_dir: Path) -> dict[str, str]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r"^\[image(\d+)\]:\s*<data:image/([^;]+);base64,([^>]+)>", re.M)
    out: dict[str, str] = {}
    for match in pattern.finditer(markdown):
        image_id, image_type, payload = match.groups()
        ext = "jpg" if image_type.lower() == "jpeg" else image_type.lower()
        filename = f"methode-sib-work-image-{image_id}.{ext}"
        target = asset_dir / filename
        target.write_bytes(base64.b64decode(payload))
        out[image_id] = f"/assets/methodology/{filename}"
    return out


def copy_summary_image(source: Path, asset_dir: Path) -> str | None:
    if not source.exists():
        return None
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / "sib-work-summary.png"
    shutil.copy2(source, target)
    return "/assets/methodology/sib-work-summary.png"


def strip_reference_definitions(markdown: str) -> str:
    return re.split(r"^\[image\d+\]:", markdown, maxsplit=1, flags=re.M)[0].rstrip()


def remove_duplicate_summary_figure(markdown: str) -> str:
    return re.sub(
        r"\n*!\[\]\[image1\][ \t]*(?:\n\s*)?\*Figure\s+2\s*:[^\n]*\*[ \t]*\n*",
        "\n\n",
        markdown,
        count=1,
    )


def renumber_figure_captions(markdown: str) -> str:
    markdown = re.sub(r"(\*Figure\s+)3(\s*:)", r"\g<1>2\2", markdown, count=1)
    markdown = re.sub(r"(\*Figure\s+)4(\s*:)", r"\g<1>3\2", markdown, count=1)
    return markdown


def prepare_markdown(markdown: str, image_paths: dict[str, str], summary_path: str | None) -> str:
    body = strip_reference_definitions(markdown)
    body = re.sub(r"^\s*\d+\)\s*(#{1,6}\s+)", r"\1", body, flags=re.M)
    body = re.sub(r"^#\s+Méthodologie\s*$", "# Méthodologie SIB Work", body, flags=re.M)
    body = remove_duplicate_summary_figure(body)
    body = renumber_figure_captions(body)

    for image_id, path in image_paths.items():
        alt = IMAGE_ALT.get(image_id, f"Figure méthodologique {image_id}")
        body = body.replace(f"![][image{image_id}]", f"![{alt}]({path})")

    body = re.sub(r"[ \t]{2,}\n(!\[)", r"\n\n\1", body)
    body = re.sub(r"(!\[[^\]]*\]\([^)]+\))[ \t]{2,}\n(\*)", r"\1\n\n\2", body)

    if summary_path:
        summary_md = (
            f"![Résumé de la chaîne de calcul SIB Work]({summary_path})\n"
            "*Figure 1 : résumé de la chaîne de calcul SIB Work*\n\n"
        )
        body = body.replace("# Méthodologie SIB Work", f"# Méthodologie SIB Work\n\n{summary_md}", 1)

    return body


def pandoc_to_html(markdown: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        source = tmpdir / "methodology.md"
        output = tmpdir / "methodology.html"
        source.write_text(markdown, encoding="utf-8")
        subprocess.run(
            [
                "pandoc",
                "--from",
                "gfm",
                "--to",
                "html",
                "--wrap=none",
                "--output",
                str(output),
                str(source),
            ],
            check=True,
        )
        return output.read_text(encoding="utf-8")


def wrap_tables(html: str) -> str:
    return re.sub(
        r"(<table>.*?</table>)",
        r'<div class="methodology-table-wrap">\n\1\n</div>',
        html,
        flags=re.S,
    )


def strip_zotero_links(html: str) -> str:
    return re.sub(
        r'<a href="https://www\.zotero\.org/google-docs/\?[^"]*">(.*?)</a>',
        r"\1",
        html,
        flags=re.S,
    )


def wrap_fragment(html: str, source_md: Path) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    html = strip_zotero_links(html)
    html = wrap_tables(html)
    return (
        '<div class="methodology-doc">\n'
        '  <div class="methodology-source-note">Document source : '
        f"{source_md.name} · généré le {generated_at}</div>\n"
        f"{html}\n"
        "</div>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SIB Work methodology web fragment from the provided Markdown document.")
    parser.add_argument("--source-md", type=Path, default=DEFAULT_SOURCE_MD)
    parser.add_argument("--summary-image", type=Path, default=DEFAULT_SUMMARY_IMAGE)
    parser.add_argument("--output-html", type=Path, default=OUTPUT_HTML)
    parser.add_argument("--asset-dir", type=Path, default=ASSET_DIR)
    args = parser.parse_args()

    markdown = args.source_md.read_text(encoding="utf-8")
    image_paths = extract_embedded_images(markdown, args.asset_dir)
    summary_path = copy_summary_image(args.summary_image, args.asset_dir)
    prepared = prepare_markdown(markdown, image_paths, summary_path)
    html = pandoc_to_html(prepared)
    args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.output_html.write_text(wrap_fragment(html, args.source_md), encoding="utf-8")
    print(f"wrote {args.output_html}")
    for image_id, path in sorted(image_paths.items(), key=lambda item: int(item[0])):
        print(f"image{image_id}: {path}")
    if summary_path:
        print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
