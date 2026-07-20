#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Extract per-PR unified diffs into <bundle-dir>/data/diffs-pr{N}.js.

For each requested PR, resolves its merge/squash commit (same discovery chain
as extract_story.py — merge-commit scan, squash-commit scan, gh CLI fallback;
duplicated here so this script is standalone-runnable with no cross-imports),
then computes the diff:
  - merge commit: `git diff <parent1>..<parent2>`
  - squash commit: `git diff <sha>^..<sha>`

The diff is split per file (on `diff --git a/... b/...` boundaries), each
file's diff capped at 4000 lines with a truncation marker, and written as a
namespaced JS file: `window.DIFFS_BY_PR[N] = {"<path>": "<diff text>", ...}`.

Usage:
    uv run extract_diffs.py --repo <path> --prs 73,75
    uv run extract_diffs.py --repo <path> --prs 73 --force
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = "1.0"
MAX_LINES_PER_FILE = 4000
TRUNCATION_MARKER = "\n… [truncated by prodyssey: diff exceeds 4000 lines]"

MERGE_PR_RE = re.compile(r"Merge pull request #(\d+) from \S+?/(\S+)")
SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


# ---- PR resolution (duplicated from extract_story.py — no cross-imports) ----

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


def commit_kind(repo: Path, sha: str) -> str:
    out = run_git(repo, ["rev-list", "--parents", "-n", "1", sha]).strip()
    parts = out.split()
    return "merge" if len(parts) >= 3 else "squash"


def discover_merge_prs(repo: Path, rev: str) -> list[dict]:
    out = run_git(repo, ["log", "--merges", "--format=%h|%s", rev])
    prs = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        commit_hash, subject = line.split("|", 1)
        m = MERGE_PR_RE.search(subject)
        if not m:
            continue
        prs.append({"hash": commit_hash, "pr": int(m.group(1)), "kind": "merge"})
    return prs


def discover_squash_prs(repo: Path, rev: str) -> list[dict]:
    out = run_git(repo, ["log", "--first-parent", "--no-merges", "--format=%h|%s", rev])
    prs = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        commit_hash, subject = line.split("|", 1)
        m = SQUASH_PR_RE.search(subject)
        if not m:
            continue
        prs.append({"hash": commit_hash, "pr": int(m.group(1)), "kind": "squash"})
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
    return {"hash": merge_commit, "pr": pr_num, "kind": commit_kind(repo, merge_commit)}


def resolve_prs(repo: Path, pr_nums: list[int], dot_range: str | None) -> dict[int, dict]:
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
    combined: dict[int, dict] = {}
    for entry in squashes + merges:  # merges added last so they win on conflict
        combined[entry["pr"]] = entry

    resolved: dict[int, dict] = {}
    missing = []
    for num in pr_nums:
        if num in combined:
            resolved[num] = combined[num]
        else:
            missing.append(num)

    if missing:
        gh_path = shutil.which("gh")
        still_missing = []
        for num in missing:
            entry = try_gh_pr(repo, num) if gh_path else None
            if entry:
                resolved[num] = entry
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


# ---- diff extraction ----

def get_diff_text(repo: Path, entry: dict) -> str:
    sha = entry["hash"]
    if entry["kind"] == "merge":
        parts = run_git(repo, ["rev-list", "--parents", "-n", "1", sha]).strip().split()
        parent1, parent2 = parts[1], parts[2]
        return run_git(repo, ["diff", f"{parent1}..{parent2}"])
    return run_git(repo, ["diff", f"{sha}^..{sha}"])


def split_diff_by_file(diff_text: str) -> dict[str, str]:
    files: dict[str, list[str]] = {}
    current_path: str | None = None
    current_lines: list[str] = []
    for line in diff_text.splitlines():
        m = DIFF_GIT_RE.match(line)
        if m:
            if current_path is not None:
                files[current_path] = current_lines
            current_path = m.group(2)  # "b/" side (post-change path)
            current_lines = [line]
        elif current_path is not None:
            current_lines.append(line)
    if current_path is not None:
        files[current_path] = current_lines

    result = {}
    for path, file_lines in files.items():
        if len(file_lines) > MAX_LINES_PER_FILE:
            text = "\n".join(file_lines[:MAX_LINES_PER_FILE]) + TRUNCATION_MARKER
        else:
            text = "\n".join(file_lines)
        result[path] = text
    return result


def write_diffs_file(data_dir: Path, pr_num: int, files: dict[str, str]) -> Path:
    out_path = data_dir / f"diffs-pr{pr_num}.js"
    body = json.dumps(files, ensure_ascii=False, indent=2)
    content = (
        "window.DIFFS_BY_PR = window.DIFFS_BY_PR || {};\n"
        f"window.DIFFS_BY_PR[{pr_num}] = {body};\n"
    )
    out_path.write_text(content)
    return out_path


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
    parser.add_argument("--prs", required=True, help="comma-separated PR numbers, e.g. 73,75")
    parser.add_argument(
        "--dot-range",
        default=None,
        help="git revision to scan for PR merge/squash commits (default: repo's detected default branch)",
    )
    parser.add_argument("--force", action="store_true", help="overwrite diffs-pr{N}.js files that already exist")
    args = parser.parse_args()

    repo = resolve_repo(args.repo)
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else repo / ".odyssey"
    data_dir = bundle_dir / "data"
    manifest_js = data_dir / "manifest.js"

    pr_nums = sorted({int(x.strip()) for x in args.prs.split(",") if x.strip()})
    if not pr_nums:
        print("error: --prs must list at least one PR number.\nremediation: pass --prs N[,M,...]", file=sys.stderr)
        sys.exit(1)

    resolved = resolve_prs(repo, pr_nums, args.dot_range)

    data_dir.mkdir(parents=True, exist_ok=True)
    for pr_num in pr_nums:
        out_path = data_dir / f"diffs-pr{pr_num}.js"
        if out_path.exists() and not args.force:
            print(f"PR #{pr_num}: skip (exists) -> {out_path}")
            continue
        entry = resolved[pr_num]
        diff_text = get_diff_text(repo, entry)
        files = split_diff_by_file(diff_text)
        write_diffs_file(data_dir, pr_num, files)
        print(f"PR #{pr_num}: wrote {len(files)} file(s) -> {out_path}")

    rewrite_manifest(bundle_dir, manifest_js)
    print(f"Wrote {manifest_js}")


if __name__ == "__main__":
    main()
