#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10.0.0"]
# ///
"""Flatten one PR from a Codebase Odyssey bundle into a single self-contained
HTML file safe to publish as a Claude Artifact.

The bundled viewer (`viewer/index.html`) is a normal multi-file web page in
disguise: it loads `window.STORY`/`ODYSSEY`/`DIFFS_BY_PR`/`ADRS` via sibling
`<script src="../data/*.js">` tags, references scene-art PNGs and narration
WAVs by relative path, and pulls Google Fonts + the Motion animation library
from two CDNs. A published Artifact is one file with no siblings and a CSP
that blocks every external request, so none of that survives as-is.

This script produces one flattened file per requested PR:
  - that PR's `story.json` timeline entry (world districts/meta kept intact —
    the viewer's district lookups need them) inlined as literal JSON instead
    of a script-src fetch
  - that PR's referenced ADRs, its diff file, and its manifest (hero/diff_prs
    scoped to just this PR) inlined the same way
  - hero PNGs recompressed to JPEG (resize + quality tiers, retried
    progressively tighter if the file would exceed the budget) and embedded
    as data URIs; narration WAVs embedded unmodified unless the budget still
    doesn't fit, in which case audio is dropped as a last resort
  - the two CDN tags dropped (Motion already no-ops gracefully when
    `window.Motion` is undefined; Google Fonts failing just falls back to
    the existing monospace/sans-serif stack)

Also computes and records, in `<bundle-dir>/exports/publish-manifest.json`,
whether this PR's underlying commit or narrative content changed since the
last export — the signal the publish pipeline uses to decide whether an
already-published artifact needs republishing.

Usage:
    uv run export_artifact.py --repo <path> --prs 73
    uv run export_artifact.py --bundle-dir <path>/.odyssey --prs 73,75
    uv run export_artifact.py --bundle-dir <bundle> --prs 73 --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

SCHEMA_VERSION = "1.0"
DEFAULT_MAX_BYTES = 15 * 1024 * 1024  # target under the 16 MiB artifact hard cap
# (image-width, jpeg-quality) tiers, tried in order until the file fits budget.
COMPRESSION_TIERS = [(1400, 78), (1100, 68), (900, 55)]

TITLE_TAG_RE = re.compile(r"<title>.*?</title>")

SCRIPT_BLOCK_RE = re.compile(
    r'<script src="\.\./data/story\.js"></script>.*?<script src="\.\./data/adrs\.js"></script>\n',
    re.S,
)
CDN_LINK_RES = [
    re.compile(r'<link rel="preconnect"[^>]*>\n'),
    re.compile(r'<link href="https://fonts\.googleapis[^>]*>\n'),
    re.compile(r'<script src="https://cdn\.jsdelivr\.net[^>]*></script>\n'),
]
HERO_SRC_OLD = 'return `<div class="hero-frame"><img src="../assets/${rel}" alt="${escapeHtml(alt)}" loading="lazy"></div>`;'
HERO_SRC_NEW = 'return `<div class="hero-frame"><img src="${window.ODYSSEY_ASSETS[rel] || \'\'}" alt="${escapeHtml(alt)}" loading="lazy"></div>`;'
DIALOG_IMG_OLD = "img.src = `../assets/${rel}`;"
DIALOG_IMG_NEW = "img.src = window.ODYSSEY_ASSETS[rel] || '';"
AUDIO_SRC_OLD = "narrationAudio.src = `../data/audio/${file}`;"
AUDIO_SRC_NEW = "narrationAudio.src = window.ODYSSEY_AUDIO[file] || '';"


# ---- filesystem / repo resolution (same conventions as the other scripts) ----

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


def level_num_from_filename(name: str) -> int:
    m = re.match(r"level-(\d+)\.png$", name)
    return int(m.group(1)) if m else 0


def escape_script_close(s: str) -> str:
    """Diffs of HTML files can contain a literal `</script>` — left alone it
    closes our inline <script> block early and silently breaks the page."""
    return s.replace("</script", "<\\/script")


# ---- data loading ----

def load_story(bundle_dir: Path) -> dict:
    story_path = bundle_dir / "data" / "story.json"
    if not story_path.exists():
        print(
            f"error: {story_path} not found.\n"
            "remediation: run /prodyssey:baseline (and /prodyssey:generate) against this bundle first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(story_path.read_text())


def find_pr_entry(story: dict, pr_num: int) -> dict | None:
    for entry in story.get("timeline", []):
        if entry.get("pr") == pr_num:
            return entry
    return None


def load_adrs_subset(bundle_dir: Path, adr_ids: list[str]) -> dict:
    adrs_path = bundle_dir / "data" / "adrs.json"
    if not adrs_path.exists() or not adr_ids:
        return {}
    all_adrs = json.loads(adrs_path.read_text())
    return {k: v for k, v in all_adrs.items() if k in adr_ids}


def load_diffs_js(bundle_dir: Path, pr_num: int) -> str | None:
    diffs_path = bundle_dir / "data" / f"diffs-pr{pr_num}.js"
    if not diffs_path.exists():
        return None
    return diffs_path.read_text()


def discover_hero_pngs(bundle_dir: Path, pr_num: int) -> list[Path]:
    pr_dir = bundle_dir / "assets" / f"pr-{pr_num}"
    if not pr_dir.is_dir():
        return []
    return sorted(pr_dir.glob("level-*.png"), key=lambda p: level_num_from_filename(p.name))


def discover_audio(bundle_dir: Path, pr_num: int) -> list[Path]:
    audio_dir = bundle_dir / "data" / "audio"
    if not audio_dir.is_dir():
        return []
    return sorted(audio_dir.glob(f"pr{pr_num}_*.wav"))


# ---- image compression ----

def compress_png_to_jpeg(png_path: Path, width: int, quality: int) -> bytes:
    from PIL import Image

    im = Image.open(png_path)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > width:
        new_height = round(im.height * (width / im.width))
        im = im.resize((width, new_height), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# ---- artifact assembly ----

def build_html(
    viewer_html: str,
    story_obj: dict,
    manifest_obj: dict,
    diffs_js: str | None,
    adrs_obj: dict,
    assets_map: dict[str, str],
    audio_map: dict[str, str],
    page_title: str,
) -> str:
    html = viewer_html
    for cdn_re in CDN_LINK_RES:
        html = cdn_re.sub("", html, count=1)

    # The static <title> tag, not the page's own JS (which sets document.title
    # at runtime), is what the Artifact tool reads to name a published page —
    # give every PR its own instead of shipping the viewer's generic default.
    import html as _html_mod

    html = TITLE_TAG_RE.sub(f"<title>{_html_mod.escape(page_title)}</title>", html, count=1)

    if HERO_SRC_OLD not in html or DIALOG_IMG_OLD not in html or AUDIO_SRC_OLD not in html:
        print(
            "error: viewer/index.html doesn't match the expected shape for this transform "
            "(hero image / audio-dialog image / narration-audio src assignment not found verbatim).\n"
            "remediation: the viewer was edited — update export_artifact.py's replacement strings to match.",
            file=sys.stderr,
        )
        sys.exit(1)
    html = html.replace(HERO_SRC_OLD, HERO_SRC_NEW)
    html = html.replace(DIALOG_IMG_OLD, DIALOG_IMG_NEW)
    html = html.replace(AUDIO_SRC_OLD, AUDIO_SRC_NEW)

    old_block = SCRIPT_BLOCK_RE.search(html)
    if not old_block:
        print(
            "error: viewer/index.html's data-loading <script> block not found verbatim.\n"
            "remediation: the viewer was edited — update export_artifact.py's SCRIPT_BLOCK_RE to match.",
            file=sys.stderr,
        )
        sys.exit(1)

    diffs_block = escape_script_close(diffs_js) if diffs_js else (
        "window.DIFFS_BY_PR = window.DIFFS_BY_PR || {};"
    )
    inline_data = f"""<script>
window.STORY = {escape_script_close(json.dumps(story_obj, ensure_ascii=False))};
window.ODYSSEY = {json.dumps(manifest_obj, ensure_ascii=False)};
{diffs_block}
window.ADRS = {escape_script_close(json.dumps(adrs_obj, ensure_ascii=False))};
window.ODYSSEY_ASSETS = {json.dumps(assets_map, ensure_ascii=False)};
window.ODYSSEY_AUDIO = {json.dumps(audio_map, ensure_ascii=False)};
</script>
"""
    html = html.replace(old_block.group(0), inline_data)
    html = html.replace(
        "window.DIFFS = window.DIFFS || {};\nwindow.ADRS = window.ADRS || {};\n", ""
    )
    return html


def render_for_pr(
    viewer_html: str,
    story: dict,
    bundle_dir: Path,
    pr_num: int,
    entry: dict,
    image_width: int,
    jpeg_quality: int,
    include_audio: bool,
) -> tuple[str, int, list[str]]:
    """Returns (html, total_bytes, notes)."""
    story_obj = {
        "meta": story.get("meta", {}),
        "world": story.get("world", {}),
        "timeline": [entry],
    }
    adr_ids = entry.get("adrs") or []
    adrs_obj = load_adrs_subset(bundle_dir, adr_ids)
    diffs_js = load_diffs_js(bundle_dir, pr_num)

    hero_pngs = discover_hero_pngs(bundle_dir, pr_num)
    assets_map: dict[str, str] = {}
    hero_rel: list[str] = []
    for png in hero_pngs:
        rel = f"pr-{pr_num}/{png.name}"
        jpeg_bytes = compress_png_to_jpeg(png, image_width, jpeg_quality)
        assets_map[rel] = "data:image/jpeg;base64," + _b64(jpeg_bytes)
        hero_rel.append(rel)

    audio_map: dict[str, str] = {}
    notes: list[str] = []
    if include_audio:
        for wav in discover_audio(bundle_dir, pr_num):
            audio_map[wav.name] = "data:audio/wav;base64," + _b64(wav.read_bytes())
    else:
        notes.append("audio dropped to fit budget")

    diff_prs = [pr_num] if diffs_js else []
    manifest_obj = {
        "schema_version": SCHEMA_VERSION,
        "excluded_prs": [],
        "hero": hero_rel,
        "diff_prs": diff_prs,
    }

    repo_name = story.get("meta", {}).get("repo", "")
    page_title = f"{repo_name} — PR #{pr_num}: {entry.get('title', '')}".strip(" —")
    html = build_html(viewer_html, story_obj, manifest_obj, diffs_js, adrs_obj, assets_map, audio_map, page_title)
    return html, len(html.encode()), notes


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode()


def compute_source_hash(entry: dict, adrs_obj: dict, diffs_js: str | None) -> str:
    payload = json.dumps(
        {"entry": entry, "adrs": adrs_obj, "diffs": diffs_js},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---- publish-manifest.json ----

def load_publish_manifest(path: Path, repo_name: str) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"schema_version": "1.0", "repo": repo_name, "prs": {}, "index": {}}


def save_publish_manifest(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=None, help="path to the target git repo (default: cwd)")
    parser.add_argument("--bundle-dir", default=None, help="bundle dir to read (default: <repo>/.odyssey)")
    parser.add_argument("--prs", required=True, help="comma-separated PR numbers, e.g. 73,75")
    parser.add_argument("--out-dir", default=None, help="export output dir (default: <bundle-dir>/exports)")
    parser.add_argument("--image-width", type=int, default=None, help="override the first compression tier's width")
    parser.add_argument("--jpeg-quality", type=int, default=None, help="override the first compression tier's quality")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="target byte budget (default ~15 MiB)")
    parser.add_argument("--no-audio", action="store_true", help="never embed narration audio")
    parser.add_argument("--force", action="store_true", help="rebuild even if the export already exists")
    args = parser.parse_args()

    repo = resolve_repo(args.repo)
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else repo / ".odyssey"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else bundle_dir / "exports"
    viewer_path = bundle_dir / "viewer" / "index.html"

    if not viewer_path.exists():
        print(
            f"error: {viewer_path} not found.\n"
            "remediation: run /prodyssey:baseline against this bundle first.",
            file=sys.stderr,
        )
        sys.exit(1)
    viewer_html = viewer_path.read_text()

    pr_nums = sorted({int(x.strip()) for x in args.prs.split(",") if x.strip()})
    if not pr_nums:
        print("error: --prs must list at least one PR number.\nremediation: pass --prs N[,M,...]", file=sys.stderr)
        sys.exit(1)

    story = load_story(bundle_dir)
    repo_name = story.get("meta", {}).get("repo", repo.name)
    manifest_path = out_dir / "publish-manifest.json"
    publish_manifest = load_publish_manifest(manifest_path, repo_name)

    tiers = list(COMPRESSION_TIERS)
    if args.image_width or args.jpeg_quality:
        w = args.image_width or COMPRESSION_TIERS[0][0]
        q = args.jpeg_quality or COMPRESSION_TIERS[0][1]
        tiers = [(w, q)] + COMPRESSION_TIERS[1:]

    out_dir.mkdir(parents=True, exist_ok=True)

    for pr_num in pr_nums:
        entry = find_pr_entry(story, pr_num)
        if entry is None:
            print(
                f"error: PR #{pr_num} not found in {bundle_dir}/data/story.json.\n"
                f"remediation: run /prodyssey:generate --prs {pr_num} first.",
                file=sys.stderr,
            )
            sys.exit(1)

        out_path = out_dir / f"pr-{pr_num}.html"
        prior = publish_manifest["prs"].get(str(pr_num), {})

        adr_ids = entry.get("adrs") or []
        adrs_obj = load_adrs_subset(bundle_dir, adr_ids)
        diffs_js = load_diffs_js(bundle_dir, pr_num)
        source_hash = compute_source_hash(entry, adrs_obj, diffs_js)
        commit = entry.get("commit")

        unchanged = (
            out_path.exists()
            and prior.get("source_hash") == source_hash
            and prior.get("commit") == commit
        )
        if unchanged and not args.force:
            print(f"PR #{pr_num}: unchanged since last export (commit={commit}, hash={source_hash}) -> {out_path}")
            continue

        include_audio = not args.no_audio
        html = total_bytes = notes = None
        for width, quality in tiers:
            html, total_bytes, notes = render_for_pr(
                viewer_html, story, bundle_dir, pr_num, entry, width, quality, include_audio
            )
            if total_bytes <= args.max_bytes:
                break
        if total_bytes > args.max_bytes and include_audio:
            width, quality = tiers[-1]
            html, total_bytes, notes = render_for_pr(
                viewer_html, story, bundle_dir, pr_num, entry, width, quality, include_audio=False
            )
        if total_bytes > args.max_bytes:
            print(
                f"WARNING: PR #{pr_num} export is {total_bytes / 1024 / 1024:.2f} MiB, "
                f"over the {args.max_bytes / 1024 / 1024:.1f} MiB target even at the tightest "
                "compression tier with audio dropped. Writing it anyway — it may be rejected "
                "at publish time (16 MiB hard cap).",
                file=sys.stderr,
            )

        out_path.write_text(html)

        if not prior:
            change_note = "first export"
        else:
            changed_bits = []
            if prior.get("commit") != commit:
                changed_bits.append("commit")
            if prior.get("source_hash") != source_hash:
                changed_bits.append("content")
            change_note = ", ".join(changed_bits) if changed_bits else "unchanged (forced)"

        publish_manifest["prs"][str(pr_num)] = {
            **prior,
            "title": entry.get("title", ""),
            "tagline": entry.get("tagline", ""),
            "date": entry.get("date", ""),
            "status": entry.get("status", "merged"),
            "commit": commit,
            "source_hash": source_hash,
            "export_file": str(out_path.relative_to(bundle_dir)),
            "export_bytes": total_bytes,
            "exported_at": now_iso(),
        }
        save_publish_manifest(manifest_path, publish_manifest)

        note_str = f" ({'; '.join(notes)})" if notes else ""
        print(
            f"PR #{pr_num}: wrote {out_path} — {total_bytes / 1024 / 1024:.2f} MiB, "
            f"changed: {change_note}{note_str}"
        )


if __name__ == "__main__":
    main()
