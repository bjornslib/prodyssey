#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Render `<bundle-dir>/exports/publish-manifest.json` into a small,
self-contained `exports/index.html` — a landing page listing every PR
artifact published for this bundle so far (not just PRs touched in the
current run), each linking out to its Claude Artifact URL.

Unlike `export_artifact.py`'s per-PR output, this page carries no images or
audio — just text and links — so it's cheap enough to rebuild unconditionally
on every `/prodyssey:publish` invocation. Its own small template, not a
slice of the ~2000-line bundle viewer.

Usage:
    uv run export_index.py --repo <path>
    uv run export_index.py --bundle-dir <path>/.odyssey
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path


def resolve_repo(repo_arg: str | None) -> Path:
    target = repo_arg or "."
    try:
        out = subprocess.check_output(
            ["git", "-C", target, "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(
            f"error: '{target}' is not inside a git repository.\n"
            "remediation: run from inside a git checkout, or pass --repo <path-to-git-repo>",
            file=sys.stderr,
        )
        sys.exit(1)
    return Path(out)


STATUS_BADGE = {
    "merged": ("Merged", "#8250df", "#8250df"),
    "open": ("Open", "#2f8f9d", "#2f8f9d"),
}


def render_card(pr_num: str, entry: dict) -> str:
    title = html.escape(entry.get("title") or f"PR #{pr_num}")
    tagline = html.escape(entry.get("tagline") or "")
    date = html.escape(entry.get("date") or "")
    status = entry.get("status", "merged")
    label, color, border = STATUS_BADGE.get(status, STATUS_BADGE["merged"])
    url = entry.get("artifact_url")

    badge = f'<span class="badge" style="color:{color};border-color:{border}">{label}</span>'
    meta_bits = " · ".join(b for b in (f"PR #{pr_num}", date) if b)

    if url:
        link = f'<a class="card-link" href="{html.escape(url)}" target="_blank" rel="noopener">View story →</a>'
        card_class = "card"
    else:
        link = '<span class="card-link disabled">Not yet published</span>'
        card_class = "card card-pending"

    return f"""<div class="{card_class}">
  <div class="card-top">
    <span class="meta">{meta_bits}</span>
    {badge}
  </div>
  <h2>{title}</h2>
  <p class="tagline">{tagline}</p>
  {link}
</div>"""


def render_index(manifest: dict) -> str:
    repo = html.escape(manifest.get("repo") or "")
    prs = manifest.get("prs", {})
    ordered = sorted(prs.items(), key=lambda kv: int(kv[0]), reverse=True)
    cards = "\n".join(render_card(num, entry) for num, entry in ordered) or (
        '<p class="empty">No PR artifacts published yet.</p>'
    )
    updated_note = ""
    idx = manifest.get("index") or {}
    if idx.get("published_at"):
        updated_note = f'<p class="updated">Last updated {html.escape(idx["published_at"])}</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{repo} — Codebase Odyssey Index</title>
<style>
  :root{{
    --accent:#2f8f9d; --ink: oklch(0.24 0.02 250); --ink-dim: oklch(0.5 0.02 250);
    --line: rgba(30,40,55,0.12); --paper:#f6f4ef;
  }}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;background:var(--paper);}}
  body{{
    font-family:ui-monospace,'JetBrains Mono',Menlo,Consolas,monospace;
    color:var(--ink); padding:40px 24px 80px; max-width:760px; margin:0 auto;
  }}
  header{{margin-bottom:32px;}}
  header .eyebrow{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-dim);}}
  header h1{{font-size:22px;margin:6px 0 0;}}
  .updated{{font-size:11px;color:var(--ink-dim);margin:4px 0 0;}}
  .card{{
    border:1px solid var(--line);border-radius:10px;background:#fff;
    padding:18px 20px;margin-bottom:14px;
  }}
  .card-pending{{opacity:.6;}}
  .card-top{{display:flex;align-items:center;justify-content:space-between;gap:12px;}}
  .meta{{font-size:11px;color:var(--ink-dim);letter-spacing:.02em;}}
  .badge{{
    font-size:10px;letter-spacing:.06em;text-transform:uppercase;border:1px solid;
    border-radius:10px;padding:2px 8px;
  }}
  h2{{font-size:15px;margin:10px 0 4px;font-family:-apple-system,'Segoe UI',sans-serif;}}
  .tagline{{font-size:13px;line-height:1.5;color:var(--ink-dim);margin:0 0 10px;font-style:italic;}}
  .card-link{{font-size:12px;color:var(--accent);text-decoration:none;}}
  .card-link:hover{{text-decoration:underline;}}
  .card-link.disabled{{color:var(--ink-dim);}}
  .empty{{color:var(--ink-dim);font-size:13px;}}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Codebase Odyssey</div>
  <h1>{repo}</h1>
  {updated_note}
</header>
{cards}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=None, help="path to the target git repo (default: cwd)")
    parser.add_argument("--bundle-dir", default=None, help="bundle dir to read (default: <repo>/.odyssey)")
    args = parser.parse_args()

    repo = resolve_repo(args.repo)
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else repo / ".odyssey"
    out_dir = bundle_dir / "exports"
    manifest_path = out_dir / "publish-manifest.json"

    if not manifest_path.exists():
        print(
            f"error: {manifest_path} not found.\n"
            "remediation: run export_artifact.py for at least one PR first.",
            file=sys.stderr,
        )
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    out_path = out_dir / "index.html"
    out_path.write_text(render_index(manifest))
    print(f"Wrote {out_path} ({len(manifest.get('prs', {}))} PR(s))")


if __name__ == "__main__":
    main()
