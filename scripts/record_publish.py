#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Record a published Claude Artifact URL into
`<bundle-dir>/exports/publish-manifest.json`.

Split out from `export_artifact.py`/`export_index.py` because it runs at a
different time than either: only *after* Claude has actually called the
Artifact tool and gotten a URL back. No script can know that URL in advance,
so this is the one piece of the publish pipeline that's invoked from
`SKILL.md`'s orchestration rather than chained after another script.

Usage:
    uv run record_publish.py --bundle-dir <bundle> --target pr-73 --url https://claude.ai/code/artifact/...
    uv run record_publish.py --bundle-dir <bundle> --target index --url https://claude.ai/code/artifact/...
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle-dir", required=True, help="bundle dir whose exports/publish-manifest.json to update")
    parser.add_argument("--target", required=True, help='"pr-<N>" or "index"')
    parser.add_argument("--url", required=True, help="the URL the Artifact tool returned")
    args = parser.parse_args()

    manifest_path = Path(args.bundle_dir).resolve() / "exports" / "publish-manifest.json"
    if not manifest_path.exists():
        print(
            f"error: {manifest_path} not found.\n"
            "remediation: run export_artifact.py for this PR first.",
            file=sys.stderr,
        )
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())

    if args.target == "index":
        manifest.setdefault("index", {})
        manifest["index"]["artifact_url"] = args.url
        manifest["index"]["published_at"] = now_iso()
    else:
        m = re.match(r"pr-(\d+)$", args.target)
        if not m:
            print('error: --target must be "index" or "pr-<N>".', file=sys.stderr)
            sys.exit(1)
        pr_num = m.group(1)
        if pr_num not in manifest.get("prs", {}):
            print(
                f"error: PR #{pr_num} has no export entry in {manifest_path}.\n"
                "remediation: run export_artifact.py for this PR first.",
                file=sys.stderr,
            )
            sys.exit(1)
        manifest["prs"][pr_num]["artifact_url"] = args.url
        manifest["prs"][pr_num]["published_at"] = now_iso()

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Recorded {args.target} -> {args.url}")


if __name__ == "__main__":
    main()
