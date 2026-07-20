#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Verify a Codebase Odyssey bundle for completeness. Read-only, no side effects.

Artifact key names (stable, used in --json output):
  baseline:
    story      - data/story.json parses and schema_version is a known value ("1.0")
    inventory  - inventory.yaml exists with >=1 context
    viewer     - viewer/index.html exists
  per PR (nested under "prs"."<N>"):
    timeline               - timeline entry for this PR exists
    narrative.<level>      - non-empty `narration` for each of the 4 levels
                              (landscape, problem_solution, architecture, file_changes)
    adr.<id>                - each id in this entry's adrs[] exists in data/adrs.json
                              (missing data/adrs.json => every adr check is "missing")
    asset.level-1/2/3       - PNG exists and is >1KB
    audio.<level>           - wav exists; only checked for levels with a non-empty
                              `voice` script in story.json
    diffs                   - data/diffs-pr{N}.js exists

Exit 0 iff every checked artifact is "ok". Never writes anything.

Usage:
    uv run verify_bundle.py --bundle-dir <bundle>
    uv run verify_bundle.py --bundle-dir <bundle> --prs 73,75 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA_VERSION_KNOWN = {"1.0"}
LEVEL_KEYS = ["landscape", "problem_solution", "architecture", "file_changes"]
MIN_ASSET_BYTES = 1024


def count_inventory_contexts(text: str) -> int:
    in_contexts = False
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "contexts:":
            in_contexts = True
            continue
        if not in_contexts:
            continue
        if stripped.startswith("- "):
            count += 1
    return count


def check_baseline(bundle_dir: Path) -> tuple[dict[str, str], dict | None]:
    results: dict[str, str] = {}

    story_path = bundle_dir / "data" / "story.json"
    story: dict | None = None
    if not story_path.exists():
        results["story"] = "missing"
    else:
        try:
            story = json.loads(story_path.read_text())
        except json.JSONDecodeError:
            results["story"] = "invalid-json"
            story = None
        else:
            version = story.get("meta", {}).get("schema_version")
            results["story"] = "ok" if version in SCHEMA_VERSION_KNOWN else f"unknown-schema-version:{version}"

    inventory_path = bundle_dir / "inventory.yaml"
    if not inventory_path.exists():
        results["inventory"] = "missing"
    else:
        count = count_inventory_contexts(inventory_path.read_text())
        results["inventory"] = "ok" if count >= 1 else "empty"

    viewer_path = bundle_dir / "viewer" / "index.html"
    results["viewer"] = "ok" if viewer_path.exists() else "missing"

    return results, story


def load_adrs(bundle_dir: Path) -> dict | None:
    adrs_path = bundle_dir / "data" / "adrs.json"
    if not adrs_path.exists():
        return None
    try:
        return json.loads(adrs_path.read_text())
    except json.JSONDecodeError:
        return None


def check_pr(bundle_dir: Path, story: dict | None, adrs: dict | None, pr_num: int) -> dict[str, str]:
    results: dict[str, str] = {}

    entry = None
    if story is not None:
        for item in story.get("timeline", []):
            if item.get("pr") == pr_num:
                entry = item
                break
    results["timeline"] = "ok" if entry is not None else "missing"

    levels = (entry or {}).get("levels", {})
    for level_key in LEVEL_KEYS:
        level = levels.get(level_key)
        narration = level.get("narration") if isinstance(level, dict) else None
        results[f"narrative.{level_key}"] = "ok" if narration else "missing"

    adr_ids = (entry or {}).get("adrs") or []
    for adr_id in adr_ids:
        if adrs is None:
            results[f"adr.{adr_id}"] = "missing"
        elif adr_id in adrs:
            results[f"adr.{adr_id}"] = "ok"
        else:
            results[f"adr.{adr_id}"] = "missing"

    for i in (1, 2, 3):
        png_path = bundle_dir / "assets" / f"pr-{pr_num}" / f"level-{i}.png"
        if not png_path.exists():
            results[f"asset.level-{i}"] = "missing"
        elif png_path.stat().st_size <= MIN_ASSET_BYTES:
            results[f"asset.level-{i}"] = "too-small"
        else:
            results[f"asset.level-{i}"] = "ok"

    for level_key in LEVEL_KEYS:
        level = levels.get(level_key)
        voice = level.get("voice") if isinstance(level, dict) else None
        if not voice:
            continue
        wav_path = bundle_dir / "data" / "audio" / f"pr{pr_num}_{level_key}.wav"
        results[f"audio.{level_key}"] = "ok" if wav_path.exists() else "missing"

    diffs_path = bundle_dir / "data" / f"diffs-pr{pr_num}.js"
    results["diffs"] = "ok" if diffs_path.exists() else "missing"

    return results


def all_ok(results: dict[str, str]) -> bool:
    return all(v == "ok" for v in results.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle-dir", required=True, help="bundle dir to verify (e.g. <repo>/.odyssey)")
    parser.add_argument("--prs", default=None, help="comma-separated PR numbers (default: all timeline PRs)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a table")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).resolve()
    if not bundle_dir.exists():
        print(
            f"error: bundle dir {bundle_dir} does not exist.\n"
            f"remediation: run extract_story.py --bundle-dir {bundle_dir} first.",
            file=sys.stderr,
        )
        sys.exit(1)

    baseline, story = check_baseline(bundle_dir)
    adrs = load_adrs(bundle_dir)

    if args.prs:
        pr_nums = sorted({int(x.strip()) for x in args.prs.split(",") if x.strip()})
    elif story is not None:
        pr_nums = sorted(item["pr"] for item in story.get("timeline", []))
    else:
        pr_nums = []

    prs_results: dict[str, dict[str, str]] = {}
    for pr_num in pr_nums:
        prs_results[str(pr_num)] = check_pr(bundle_dir, story, adrs, pr_num)

    ok = all_ok(baseline) and all(all_ok(r) for r in prs_results.values())

    if args.json:
        print(json.dumps({"baseline": baseline, "prs": prs_results}, indent=2, ensure_ascii=False))
    else:
        print("Baseline")
        print("--------")
        for key, status in baseline.items():
            print(f"  {key:<12} {status}")
        for pr_num, results in prs_results.items():
            header = f"PR #{pr_num}"
            print(f"\n{header}")
            print("-" * len(header))
            for key, status in results.items():
                print(f"  {key:<20} {status}")
        print(f"\nOverall: {'OK' if ok else 'FAIL'}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
