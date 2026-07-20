#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai>=1.0.0",
#     "pillow>=10.0.0",
#     "python-dotenv>=1.0.0",
# ]
# ///
"""Generate Nano Banana Pro (Gemini image model) prompts for a Codebase Odyssey bundle.

Reads <bundle>/data/story.json and, for every requested PR in the timeline and
every one of the 4 story levels (PR Landscape / Problem & Solution /
Architecture / File Changes), composes an image-generation prompt describing
that scene. Prompts are written to <bundle>/data/prompts.json.

For levels 1-3 (landscape, problem_solution, architecture), the prompt is
data-driven: that PR's own timeline entry (unmodified) is serialized as JSON
and handed to the model with a level-specific "visually describe this PR"
instruction, letting Nano Banana Pro do the creative synthesis instead of a
fixed hand-composed scene. Level 4 (file_changes) keeps its existing
hand-composed diff-screen/file-tree template.

    uv run generate_prompts.py --repo <path>                  # write prompts.json only
    uv run generate_prompts.py --repo <path> --generate        # also call Gemini and render PNGs
    uv run generate_prompts.py --repo <path> --generate --force
    uv run generate_prompts.py --repo <path> --prs 73,75 --generate

--generate requires GEMINI_API_KEY in the environment (or a .env file in the
--repo root). This script never calls the API unless --generate is passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCHEMA_VERSION = "1.0"
DEFAULT_MODEL = "gemini-3-pro-image-preview"

SHARED_STYLE = (
    "Cinematic 16:9 dark sci-fi HUD interface, deep space navy background (#050a14), "
    "glowing cyan holographic UI frames and wireframes, subtle starfield, neon accent "
    "lighting, high detail digital illustration, no photographic realism, consistent "
    "visual language across a series. Text labels rendered as clean holographic HUD "
    "typography."
)

LEVEL_KEYS = ["landscape", "problem_solution", "architecture", "file_changes"]

# Level-specific "visually describe this PR" framing for the data-driven builder
# (levels 1-3). Each is distinct so the 3 renders per PR don't converge on the
# same image.
VISUAL_DESCRIBE_INSTRUCTIONS = {
    "landscape": (
        "You are given the JSON data for one pull request from a codebase's evolution "
        "timeline. Visually describe a wide establishing view of this PR's place in the "
        "codebase's evolution — its scale, which parts of the codebase (districts) it "
        "touched, and its one-line hook. This is the first, broadest look at the PR."
    ),
    "problem_solution": (
        "You are given the JSON data for one pull request from a codebase's evolution "
        "timeline. Visually describe the concrete problem this PR faced and the fix it "
        "shipped, grounded in the PR's own problem/solution narrative."
    ),
    "architecture": (
        "You are given the JSON data for one pull request from a codebase's evolution "
        "timeline. Visually describe the underlying design decision behind this PR — the "
        "forces at play, any rejected alternatives, and the boundaries it drew — grounded "
        "in the PR's `adrs` field if present."
    ),
}

STYLE_CONSISTENCY_NOTE = (
    "Style hint (not a scene script): dark, holographic sci-fi HUD visual language — deep "
    "space navy background, glowing cyan wireframes, neon accents, clean holographic "
    "typography for any text — so this reads as one entry in a consistent series. Compose "
    "the actual scene freely from the PR data above; do not default to a generic galaxy, "
    "projector, or city unless the data itself suggests it."
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


def load_story(story_json: Path) -> dict:
    if not story_json.exists():
        print(
            f"error: {story_json} not found\n"
            "remediation: run extract_story.py first to create a story.json seed.",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(story_json.read_text())


def truncate_words(text: str, limit: int = 20) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]) + "..."


def district_label(districts_by_id: dict, district_id: str) -> str:
    d = districts_by_id.get(district_id)
    return d["label"] if d else district_id


def auto_summary(pr: dict, districts_by_id: dict) -> str:
    files = pr.get("size", {}).get("files", 0)
    touched = pr.get("touched", {})
    labels = [district_label(districts_by_id, d) for d in touched.keys()]
    districts_text = ", ".join(labels) if labels else "the codebase"
    return f"{files} files changed across {districts_text}"


def build_visual_describe_prompt(pr: dict, level_key: str, level_name: str) -> str:
    """Data-driven prompt for levels 1-3: feed the PR's own story data and ask
    the model to visually describe the PR, instead of hand-composing a scene."""
    instruction = VISUAL_DESCRIBE_INSTRUCTIONS[level_key]
    pr_json = json.dumps(pr, indent=2, ensure_ascii=False)
    return (
        f"{instruction}\n\n"
        f"PR data (level: {level_name}):\n{pr_json}\n\n"
        f"{STYLE_CONSISTENCY_NOTE}"
    )


def build_level4(pr: dict, districts_by_id: dict) -> str:
    """File Changes: large diff screen plus a file-tree panel."""
    fc = pr.get("levels", {}).get("file_changes", {})
    narration = fc.get("narration") or auto_summary(pr, districts_by_id)
    groups = fc.get("groups")
    if groups:
        tree_items = [g["title"] for g in groups]
    else:
        touched = pr.get("touched", {})
        ranked = sorted(touched.items(), key=lambda kv: kv[1], reverse=True)
        tree_items = [f"{district_label(districts_by_id, did)} ({count})" for did, count in ranked]
    tree_text = "; ".join(tree_items) if tree_items else "no files listed"
    scene = (
        f'A large floating holographic code-diff screen dominates the center of the scene, '
        f'densely filled with rows of green (+) and red (-) diff blocks scrolling into the '
        f'distance. To the left, a slim vertical file-tree panel lists: {tree_text}. Below '
        f'the diff screen, a holographic caption reads: "{narration}"'
    )
    return scene


def build_prompts(story: dict, prs_filter: list[int] | None) -> list[dict]:
    districts_by_id = {d["id"]: d for d in story["world"]["districts"]}
    level_names = story["meta"]["levels"]
    timeline = story["timeline"]
    if prs_filter is not None:
        wanted = set(prs_filter)
        timeline = [pr for pr in timeline if pr["pr"] in wanted]
    prompts = []
    for pr in timeline:
        for i, level_key in enumerate(LEVEL_KEYS, start=1):
            level_name = level_names[i - 1]
            if level_key == "file_changes":
                prompt = f"{SHARED_STYLE} {build_level4(pr, districts_by_id)}"
            else:
                prompt = build_visual_describe_prompt(pr, level_key, level_name)
            prompts.append(
                {
                    "pr": pr["pr"],
                    "level": i,
                    "level_name": level_name,
                    "output_path": f"assets/pr-{pr['pr']}/level-{i}.png",
                    "prompt": prompt,
                    "aspect_ratio": "16:9",
                }
            )
    return prompts


def call_gemini(prompt: str, model: str, client) -> tuple[bytes, str | None]:
    """Call Gemini generate_content via the google-genai SDK and return
    (image_bytes, text_description). text_description is the model's own
    accompanying text part, if any (None for the file_changes/level-4 path,
    which doesn't call this function).
    """
    from google.genai import types
    from PIL import Image as PILImage
    from io import BytesIO

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(image_size="2K"),
        ),
    )

    image_bytes = None
    text_description = None
    for part in response.parts:
        if part.text is not None:
            text_description = part.text
        elif part.inline_data is not None:
            image_data = part.inline_data.data
            if isinstance(image_data, str):
                import base64
                image_data = base64.b64decode(image_data)

            image = PILImage.open(BytesIO(image_data))
            buf = BytesIO()
            if image.mode == "RGBA":
                rgb_image = PILImage.new("RGB", image.size, (255, 255, 255))
                rgb_image.paste(image, mask=image.split()[3])
                rgb_image.save(buf, "PNG")
            elif image.mode == "RGB":
                image.save(buf, "PNG")
            else:
                image.convert("RGB").save(buf, "PNG")
            image_bytes = buf.getvalue()

    if image_bytes is None:
        raise RuntimeError("no inline image data in Gemini response")
    return image_bytes, text_description


def run_generate(
    prompts: list[dict],
    assets_root: Path,
    descriptions_json: Path,
    model: str,
    force: bool,
    repo: Path,
) -> None:
    from dotenv import load_dotenv
    load_dotenv(repo / ".env")  # loads GEMINI_API_KEY from the target repo's .env, if present

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "GEMINI_API_KEY is not set.\n\n"
            "Get an API key from https://aistudio.google.com/apikey and run:\n"
            "  export GEMINI_API_KEY=your-key-here\n"
            "  uv run generate_prompts.py --repo <path> --generate\n",
            file=sys.stderr,
        )
        sys.exit(1)

    from google import genai
    client = genai.Client(api_key=api_key)

    descriptions: dict[str, str] = {}
    if descriptions_json.exists():
        descriptions = json.loads(descriptions_json.read_text())

    total = len(prompts)
    for idx, entry in enumerate(prompts, start=1):
        out_path = assets_root / entry["output_path"]
        label = f'[{idx}/{total}] PR #{entry["pr"]} / {entry["level_name"]}'
        if out_path.exists() and not force:
            print(f"{label}: skip (exists) -> {out_path}")
            continue
        print(f"{label}: generating -> {out_path}")
        try:
            image_bytes, text_description = call_gemini(entry["prompt"], model, client)
        except Exception as e:  # noqa: BLE001 - surface any generation failure and keep going
            print(f"{label}: FAILED: {e}", file=sys.stderr)
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(image_bytes)
        print(f"{label}: wrote {len(image_bytes)} bytes")

        if text_description:
            print(f"{label}: model description: {text_description}")
            descriptions[f'{entry["pr"]}-{entry["level"]}'] = text_description
            descriptions_json.write_text(json.dumps(descriptions, indent=2, ensure_ascii=False) + "\n")

        if idx < total:
            time.sleep(1)  # be polite to the API


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
    parser.add_argument("--prs", default=None, help="comma-separated PR numbers (default: all timeline PRs)")
    parser.add_argument("--generate", action="store_true", help="call Gemini and render PNGs for each prompt")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model id (default: {DEFAULT_MODEL})")
    parser.add_argument("--force", action="store_true", help="re-render PNGs that already exist")
    args = parser.parse_args()

    repo = resolve_repo(args.repo)
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else repo / ".odyssey"
    data_dir = bundle_dir / "data"
    story_json = data_dir / "story.json"
    prompts_json = data_dir / "prompts.json"
    descriptions_json = data_dir / "descriptions.json"
    manifest_js = data_dir / "manifest.js"

    prs_filter = None
    if args.prs:
        prs_filter = sorted({int(x.strip()) for x in args.prs.split(",") if x.strip()})

    story = load_story(story_json)
    prompts = build_prompts(story, prs_filter)

    data_dir.mkdir(parents=True, exist_ok=True)
    prompts_json.write_text(json.dumps(prompts, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {prompts_json} ({len(prompts)} prompts)")

    if args.generate:
        run_generate(prompts, bundle_dir, descriptions_json, args.model, args.force, repo)
        rewrite_manifest(bundle_dir, manifest_js)
        print(f"Wrote {manifest_js}")


if __name__ == "__main__":
    main()
