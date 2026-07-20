#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regenerate the mechanical parts of a Codebase Odyssey bundle's story.json.

Mechanical parts = per-PR date/size/touched and world.district file counts.
Authored narrative fields (title, tagline, depth, levels, adrs, events) are
never touched for PRs that already exist in story.json. New PRs discovered
in git get a minimal stub entry (depth "summary", empty levels) so a human
(or a later generation step) can flesh them out.

If <bundle-dir>/data/story.json does not exist yet, a seed is created: world
districts come from <bundle-dir>/inventory.yaml when present, else from a
top-level-directory heuristic over `git ls-files`.

PR discovery is a fallback chain:
  (a) merge-commit scan: `Merge pull request #N` on `git log --merges`
  (b) squash-commit scan: `(#N)` trailer on `git log --first-parent`
  (c) explicit --prs N,... resolved against (a)+(b); anything still unresolved
      is looked up via `gh pr view N --json mergeCommit,title,mergedAt` if
      `gh` is on PATH, else the run fails listing what was tried.

Usage:
    uv run extract_story.py --repo <path> --dry-run
    uv run extract_story.py --repo <path>
    uv run extract_story.py --repo <path> --prs 73,75
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

SCHEMA_VERSION = "1.0"
DEFAULT_LEVELS = ["PR Landscape", "Problem & Solution", "Architecture", "File Changes"]

EXCLUDE_PREFIXES = (".venv/", "node_modules/", ".git/")

# "Merge pull request #75 from bjornslib/claude/architecture-skill-stacks-lbobjc"
MERGE_PR_RE = re.compile(r"Merge pull request #(\d+) from \S+?/(\S+)")
# "Some squash commit title (#75)"
SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")

SIZE_RE = re.compile(
    r"(\d+) files? changed"
    r"(?:, (\d+) insertions?\(\+\))?"
    r"(?:, (\d+) deletions?\(-\))?"
)


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


def run_git(repo: Path, args: list[str]) -> str:
    return subprocess.check_output(["git", "-C", str(repo)] + args, text=True)


def get_remote_origin(repo: Path) -> str | None:
    try:
        return run_git(repo, ["remote", "get-url", "origin"]).strip()
    except subprocess.CalledProcessError:
        return None


def detect_default_branch(repo: Path) -> str:
    """Detect the repo's default branch: origin/HEAD symref first, then try
    `main` and `master` directly. Exits 1 with remediation if none resolve."""
    try:
        out = run_git(repo, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
        if out.startswith("origin/"):
            out = out[len("origin/"):]
        if out:
            return out
    except subprocess.CalledProcessError:
        pass

    for candidate in ("main", "master"):
        try:
            run_git(repo, ["rev-parse", "--verify", "--quiet", candidate])
            return candidate
        except subprocess.CalledProcessError:
            continue

    print(
        "error: could not detect the default branch.\n"
        "Tried: `git symbolic-ref --short refs/remotes/origin/HEAD`, then `main`, then `master`.\n"
        "remediation: pass --dot-range <branch> explicitly.",
        file=sys.stderr,
    )
    sys.exit(1)


def discover_merge_prs(repo: Path, rev: str) -> list[dict]:
    out = run_git(repo, ["log", "--merges", "--format=%h|%ad|%s", "--date=short", rev])
    prs = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        commit_hash, commit_date, subject = line.split("|", 2)
        m = MERGE_PR_RE.search(subject)
        if not m:
            continue  # not a "Merge pull request #N" commit (e.g. plain merges)
        pr_num = int(m.group(1))
        branch = m.group(2)
        derived_title = branch.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip().title()
        prs.append(
            {
                "hash": commit_hash,
                "date": commit_date,
                "pr": pr_num,
                "derived_title": derived_title or f"PR #{pr_num}",
            }
        )
    return prs


def discover_squash_prs(repo: Path, rev: str) -> list[dict]:
    out = run_git(repo, ["log", "--first-parent", "--no-merges", "--format=%h|%ad|%s", "--date=short", rev])
    prs = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        commit_hash, commit_date, subject = line.split("|", 2)
        m = SQUASH_PR_RE.search(subject)
        if not m:
            continue
        pr_num = int(m.group(1))
        title = SQUASH_PR_RE.sub("", subject).strip()
        prs.append(
            {
                "hash": commit_hash,
                "date": commit_date,
                "pr": pr_num,
                "derived_title": title or f"PR #{pr_num}",
            }
        )
    return prs


def try_gh_pr(repo: Path, pr_num: int) -> dict | None:
    origin = get_remote_origin(repo)
    cmd = ["gh", "pr", "view", str(pr_num), "--json", "mergeCommit,title,mergedAt"]
    if origin:
        cmd += ["--repo", origin]
    try:
        out = subprocess.check_output(cmd, cwd=str(repo), text=True, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    merge_commit = (data.get("mergeCommit") or {}).get("oid")
    if not merge_commit:
        return None
    merged_at = data.get("mergedAt") or ""
    return {
        "hash": merge_commit,
        "date": merged_at[:10] if merged_at else "",
        "pr": pr_num,
        "derived_title": data.get("title") or f"PR #{pr_num}",
    }


def discover_prs(repo: Path, dot_range: str | None, prs_filter: list[int] | None) -> list[dict]:
    """Return PR commits discovered from git log (newest first by date).

    When prs_filter is None, uses the merge+squash scan over dot_range (default
    "main", trimmed to the most recent 10 when dot_range wasn't given). When
    prs_filter is given, resolves exactly those PR numbers, falling back to
    `gh pr view` for any not found by the scan.
    """
    apply_default_limit = dot_range is None
    rev = dot_range or detect_default_branch(repo)

    try:
        merges = discover_merge_prs(repo, rev)
        squashes = discover_squash_prs(repo, rev)
    except subprocess.CalledProcessError as e:
        print(
            f"error: git discovery failed for rev '{rev}': {e}\n"
            "remediation: verify the revision/range exists in this repo, or pass --dot-range explicitly.",
            file=sys.stderr,
        )
        sys.exit(1)

    combined_by_num: dict[int, dict] = {}
    for entry in squashes + merges:  # merges added last so they win on conflict
        combined_by_num[entry["pr"]] = entry

    if prs_filter is None:
        prs = sorted(combined_by_num.values(), key=lambda e: e["date"], reverse=True)
        if apply_default_limit:
            prs = prs[:10]
        return prs

    resolved = []
    missing = []
    for num in prs_filter:
        if num in combined_by_num:
            resolved.append(combined_by_num[num])
        else:
            missing.append(num)

    if missing:
        gh_path = shutil.which("gh")
        still_missing = []
        for num in missing:
            entry = try_gh_pr(repo, num) if gh_path else None
            if entry:
                resolved.append(entry)
            else:
                still_missing.append(num)
        if still_missing:
            print(
                f"error: could not resolve PR(s) {', '.join(str(n) for n in still_missing)}.\n"
                "Tried: merge-commit scan (`git log --merges`), squash-commit scan "
                "(`git log --first-parent`), and gh CLI fallback "
                f"({'available' if gh_path else 'gh not found on PATH'}).\n"
                "remediation: verify the PR number merged into this repo, or install/auth `gh`.",
                file=sys.stderr,
            )
            sys.exit(1)

    return resolved


def get_size(repo: Path, commit_hash: str) -> dict:
    out = run_git(repo, ["diff", "--stat", f"{commit_hash}^1", commit_hash])
    lines = [l for l in out.splitlines() if l.strip()]
    if not lines:
        return {"files": 0, "adds": 0, "dels": 0}
    m = SIZE_RE.search(lines[-1])
    if not m:
        return {"files": 0, "adds": 0, "dels": 0}
    return {
        "files": int(m.group(1)),
        "adds": int(m.group(2)) if m.group(2) else 0,
        "dels": int(m.group(3)) if m.group(3) else 0,
    }


def get_touched(repo: Path, commit_hash: str) -> dict:
    out = run_git(repo, ["diff", "--name-only", f"{commit_hash}^1", commit_hash])
    touched: dict[str, int] = {}
    for path in out.splitlines():
        path = path.strip()
        if not path:
            continue
        if any(path.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
            continue
        top = path.split("/", 1)[0] if "/" in path else "(root)"
        touched[top] = touched.get(top, 0) + 1
    return touched


def count_git_files(repo: Path, path: str) -> int:
    if not path:
        return 0
    out = run_git(repo, ["ls-files", "--", path])
    return len([l for l in out.splitlines() if l.strip()])


def get_district_counts(repo: Path, districts: list[dict]) -> dict:
    counts = {}
    for d in districts:
        did = d["id"]
        counts[did] = count_git_files(repo, did)
    return counts


def parse_inventory_contexts(text: str) -> list[dict]:
    """Minimal parser for the specific inventory.yaml shape:
    contexts:
      - id: foo
        label: Foo
        paths:
          - foo
        summary: "..."
    Best-effort; callers should fall back on any parse trouble.
    """
    contexts: list[dict] = []
    current: dict | None = None
    current_key: str | None = None
    in_contexts = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped == "contexts:":
            in_contexts = True
            continue
        if not in_contexts:
            continue
        if stripped.startswith("- "):
            if current is not None:
                contexts.append(current)
            current = {}
            current_key = None
            rest = stripped[2:]
            if ":" in rest:
                key, _, val = rest.partition(":")
                key = key.strip()
                val = val.strip().strip("\"'")
                if val:
                    current[key] = val
                else:
                    current[key] = []
                    current_key = key
            continue
        if current is None:
            continue
        if stripped.startswith("- ") and current_key:
            current.setdefault(current_key, [])
            current[current_key].append(stripped[2:].strip().strip("\"'"))
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip("\"'")
            if val:
                current[key] = val
                current_key = None
            else:
                current[key] = []
                current_key = key
    if current is not None:
        contexts.append(current)
    return contexts


def heuristic_districts(repo: Path) -> list[dict]:
    out = run_git(repo, ["ls-files"])
    counts: dict[str, int] = {}
    for path in out.splitlines():
        path = path.strip()
        if not path or "/" not in path:
            continue
        top = path.split("/", 1)[0]
        counts[top] = counts.get(top, 0) + 1
    districts = []
    for top, count in sorted(counts.items()):
        if count < 3:
            continue
        districts.append({"id": top, "label": top, "kind": "unknown", "files": count, "blurb": ""})
    return districts


def repo_title(repo: Path) -> str:
    remote = get_remote_origin(repo)
    if remote:
        name = remote.rstrip("/")
        if name.endswith(".git"):
            name = name[: -len(".git")]
        name = name.split("/")[-1]
        if name:
            return name
    return repo.name


def build_seed_story(repo: Path, bundle_dir: Path) -> dict:
    inventory_path = bundle_dir / "inventory.yaml"
    districts: list[dict] = []
    if inventory_path.exists():
        try:
            contexts = parse_inventory_contexts(inventory_path.read_text())
        except Exception:
            contexts = []
        for ctx in contexts:
            paths = ctx.get("paths") or []
            first_path = paths[0] if isinstance(paths, list) and paths else ctx.get("id", "")
            districts.append(
                {
                    "id": ctx.get("id", first_path),
                    "label": ctx.get("label", ctx.get("id", first_path)),
                    "kind": "unknown",
                    "files": count_git_files(repo, first_path),
                    "blurb": ctx.get("summary", ""),
                }
            )
    if not districts:
        districts = heuristic_districts(repo)

    name = repo_title(repo)
    return {
        "meta": {
            "repo": name,
            "generated": date.today().isoformat(),
            "schema_version": SCHEMA_VERSION,
            "title": f"{name} — Codebase Odyssey",
            "description": "",
            "levels": list(DEFAULT_LEVELS),
        },
        "world": {"districts": districts},
        "timeline": [],
    }


def build_new_story(repo: Path, existing: dict, dot_range: str | None, prs_filter: list[int] | None) -> dict:
    existing_by_pr = {p["pr"]: p for p in existing.get("timeline", [])}
    prs = discover_prs(repo, dot_range, prs_filter)

    new_timeline = []
    for pr_info in prs:
        pr_num = pr_info["pr"]
        size = get_size(repo, pr_info["hash"])
        touched = get_touched(repo, pr_info["hash"])

        if pr_num in existing_by_pr:
            # Preserve every authored field; refresh only the mechanical ones.
            entry = dict(existing_by_pr[pr_num])
            entry["date"] = pr_info["date"]
            entry["size"] = size
            entry["touched"] = touched
        else:
            entry = {
                "pr": pr_num,
                "date": pr_info["date"],
                "title": pr_info["derived_title"],
                "tagline": "",
                "depth": "summary",
                "size": size,
                "touched": touched,
                "levels": {},
            }
        new_timeline.append(entry)

    # PRs already in story.json but not rediscovered this run (outside dot-range
    # or --prs filter) are kept as-is rather than dropped, so repeated runs with
    # different --prs filters accumulate instead of clobbering each other.
    discovered_nums = {e["pr"] for e in new_timeline}
    for pr_num, entry in existing_by_pr.items():
        if pr_num not in discovered_nums:
            new_timeline.append(dict(entry))

    new_timeline.sort(key=lambda e: e["pr"])

    districts = existing["world"]["districts"]
    counts = get_district_counts(repo, districts)
    for d in districts:
        d["files"] = counts[d["id"]]

    new_data = dict(existing)
    new_data["world"] = dict(existing["world"])
    new_data["world"]["districts"] = districts
    new_data["timeline"] = new_timeline
    return new_data


def rewrite_manifest(bundle_dir: Path, manifest_path: Path) -> None:
    data_dir = bundle_dir / "data"
    assets_dir = bundle_dir / "assets"

    excluded_prs = []
    if manifest_path.exists():
        try:
            text = manifest_path.read_text()
            prefix = "window.ODYSSEY = "
            start = text.index(prefix) + len(prefix)
            end = text.rindex(";")
            existing = json.loads(text[start:end])
            excluded_prs = existing.get("excluded_prs", [])
        except Exception:
            excluded_prs = []

    def pr_num_from_dirname(name: str) -> int:
        m = re.match(r"pr-(\d+)$", name)
        return int(m.group(1)) if m else 0

    def level_num_from_filename(name: str) -> int:
        m = re.match(r"level-(\d+)\.png$", name)
        return int(m.group(1)) if m else 0

    hero = []
    if assets_dir.exists():
        for pr_dir in sorted(assets_dir.glob("pr-*"), key=lambda p: pr_num_from_dirname(p.name)):
            if not pr_dir.is_dir():
                continue
            for png in sorted(pr_dir.glob("level-*.png"), key=lambda p: level_num_from_filename(p.name)):
                hero.append(f"{pr_dir.name}/{png.name}")

    diff_prs = []
    if data_dir.exists():
        for diff_file in data_dir.glob("diffs-pr*.js"):
            m = re.match(r"diffs-pr(\d+)\.js", diff_file.name)
            if m:
                diff_prs.append(int(m.group(1)))
    diff_prs.sort()

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "excluded_prs": excluded_prs,
        "hero": hero,
        "diff_prs": diff_prs,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(f"window.ODYSSEY = {json.dumps(manifest, ensure_ascii=False)};\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=None, help="path to the target git repo (default: cwd)")
    parser.add_argument("--bundle-dir", default=None, help="bundle output dir (default: <repo>/.odyssey)")
    parser.add_argument(
        "--dot-range",
        default=None,
        help="git revision/range passed to `git log --merges <range>` "
        "(default: 'main', trimmed to the last 10 PR-merge commits)",
    )
    parser.add_argument(
        "--prs",
        default=None,
        help="comma-separated PR numbers to resolve explicitly (bypasses dot-range trimming)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print a unified diff of the regenerated story.json without writing files",
    )
    args = parser.parse_args()

    repo = resolve_repo(args.repo)
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else repo / ".odyssey"
    data_dir = bundle_dir / "data"
    story_json = data_dir / "story.json"
    story_js = data_dir / "story.js"
    manifest_js = data_dir / "manifest.js"

    prs_filter = None
    if args.prs:
        prs_filter = sorted({int(x.strip()) for x in args.prs.split(",") if x.strip()})

    if story_json.exists():
        existing = json.loads(story_json.read_text())
    else:
        existing = build_seed_story(repo, bundle_dir)

    existing.setdefault("meta", {})["schema_version"] = SCHEMA_VERSION

    new_data = build_new_story(repo, existing, args.dot_range, prs_filter)

    old_json = json.dumps(existing, indent=2, ensure_ascii=False)
    new_json = json.dumps(new_data, indent=2, ensure_ascii=False)

    if args.dry_run:
        diff = difflib.unified_diff(
            (old_json + "\n").splitlines(keepends=True),
            (new_json + "\n").splitlines(keepends=True),
            fromfile="story.json (current)",
            tofile="story.json (regenerated)",
        )
        diff_text = "".join(diff)
        sys.stdout.write(diff_text if diff_text else "(no changes)\n")
        return

    data_dir.mkdir(parents=True, exist_ok=True)
    story_json.write_text(new_json + "\n")
    story_js.write_text(f"window.STORY = {new_json};\n")
    print(f"Wrote {story_json}")
    print(f"Wrote {story_js}")

    rewrite_manifest(bundle_dir, manifest_js)
    print(f"Wrote {manifest_js}")


if __name__ == "__main__":
    main()
