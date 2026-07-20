#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai>=1.0.0",
#     "python-dotenv>=1.0.0",
# ]
# ///
"""
Generate audio files for story timeline merge descriptions using Gemini 3.1 Flash TTS.

Usage:
    uv run generate_audio.py --repo <path> --pr 73 --voice Charon
    uv run generate_audio.py --repo <path> --prs 73,75
    uv run generate_audio.py --list-voices
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"

# Standard prebuilt voices for Gemini models
SUPPORTED_VOICES = {
    "Charon": "Informative & professional (recommended for architecture/tech description)",
    "Aoede": "Breezy & clear",
    "Kore": "Firm & direct",
    "Puck": "Upbeat & energetic",
    "Fenrir": "Deep & strong",
    "Zephyr": "Light & warm",
}


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


def get_api_key(provided_key: str | None) -> str | None:
    """Get Gemini API key from argument first, then environment."""
    if provided_key:
        return provided_key
    return os.environ.get("GEMINI_API_KEY")


def list_voices():
    """Print the list of supported prebuilt voices and exit."""
    print("Supported Prebuilt Voices:")
    print("==========================")
    for name, desc in SUPPORTED_VOICES.items():
        print(f"  - {name:10} : {desc}")
    print("\nNote: You can pass any other prebuilt voice name supported by Google GenAI.")


def get_pr_story(story_path: Path, pr_num: int) -> dict:
    """Load story.json and extract the timeline item matching the PR number."""
    if not story_path.exists():
        print(
            f"Error: Story file not found at {story_path.resolve()}\n"
            "remediation: run extract_story.py first to create a story.json seed.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with open(story_path, "r", encoding="utf-8") as f:
            story_data = json.load(f)
    except Exception as e:
        print(f"Error parsing JSON from {story_path}: {e}", file=sys.stderr)
        sys.exit(1)

    timeline = story_data.get("timeline", [])
    for item in timeline:
        if item.get("pr") == pr_num:
            return item

    # If not found, list available PRs that have narration/voice
    available_prs = []
    for item in timeline:
        pr_val = item.get("pr")
        levels = item.get("levels", {})
        has_voice = any("voice" in content for content in levels.values() if isinstance(content, dict))
        if pr_val is not None:
            available_prs.append(f"{pr_val}{' (narrated)' if has_voice else ''}")

    print(f"Error: PR #{pr_num} not found in timeline.", file=sys.stderr)
    print(f"Available PRs: {', '.join(available_prs)}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Generate TTS audio files for PR stories in story.json using Gemini 3.1 Flash TTS."
    )
    parser.add_argument("--repo", default=None, help="path to the target git repo (default: cwd)")
    parser.add_argument("--bundle-dir", default=None, help="bundle output dir (default: <repo>/.odyssey)")
    parser.add_argument("--pr", type=int, default=None, help="single pull request number to generate audio for")
    parser.add_argument("--prs", default=None, help="comma-separated PR numbers to loop over")
    parser.add_argument(
        "--voice", "-v",
        default="Charon",
        help="Prebuilt voice name to use (default: Charon). Use --list-voices to view options."
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Gemini TTS model name (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--story-file",
        type=Path,
        default=None,
        help="Path to story.json file (default: <bundle-dir>/data/story.json)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=None,
        help="Directory to save generated audio (default: <bundle-dir>/data/audio)"
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List supported prebuilt voices and exit"
    )
    parser.add_argument(
        "--api-key", "-k",
        help="Gemini API key override (bypasses GEMINI_API_KEY env var)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print narration scripts without making API calls"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate .wav files that already exist"
    )

    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        sys.exit(0)

    repo = resolve_repo(args.repo)
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else repo / ".odyssey"
    story_path = args.story_file or (bundle_dir / "data" / "story.json")
    output_dir = args.output_dir or (bundle_dir / "data" / "audio")

    pr_nums: list[int] = []
    if args.prs:
        pr_nums.extend(int(x.strip()) for x in args.prs.split(",") if x.strip())
    if args.pr is not None:
        pr_nums.append(args.pr)
    if not pr_nums:
        print(
            "error: no PR specified.\nremediation: pass --pr N or --prs N,M,...",
            file=sys.stderr,
        )
        sys.exit(1)
    pr_nums = sorted(set(pr_nums))

    # Load .env from the target repo root (not cwd) so GEMINI_API_KEY resolves
    # the same way regardless of where this script is invoked from.
    from dotenv import load_dotenv
    load_dotenv(repo / ".env")

    entries = []  # (pr_num, level, text, output_file)
    for pr_num in pr_nums:
        pr_entry = get_pr_story(story_path, pr_num)
        levels = pr_entry.get("levels", {})
        narrations = {
            name: content["voice"]
            for name, content in levels.items()
            if isinstance(content, dict) and "voice" in content
        }
        if not narrations:
            print(f"Warning: No 'voice' narration script found for PR #{pr_num}.", file=sys.stderr)
            continue

        print(f"Found {len(narrations)} narration segment(s) for PR #{pr_num}:")
        for name in narrations:
            print(f"  - {name}")

        for level, text in narrations.items():
            output_file = output_dir / f"pr{pr_num}_{level}.wav"
            entries.append((pr_num, level, text, output_file))

    if args.dry_run:
        print("\n--- Dry Run: Narration Scripts ---")
        for pr_num, level, text, output_file in entries:
            print(f"\n[PR #{pr_num} / {level}] -> {output_file}")
            print(text)
        sys.exit(0)

    if not entries:
        sys.exit(0)

    # Resolve API Key
    api_key = get_api_key(args.api_key)
    if not api_key:
        print("Error: No API key provided.", file=sys.stderr)
        print("Please set GEMINI_API_KEY in your shell environment or .env file, or pass --api-key.", file=sys.stderr)
        sys.exit(1)

    # Import google-genai after API key check to keep it fast if exiting early
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Error: google-genai SDK not installed.", file=sys.stderr)
        print("Please run the script using 'uv run generate_audio.py' to automatically load dependencies.", file=sys.stderr)
        sys.exit(1)

    # Initialize client
    client = genai.Client(api_key=api_key)

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Audio synthesis configuration
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=args.voice
                )
            )
        )
    )

    print(f"\nInitializing TTS generation using model '{args.model}' and voice '{args.voice}'...")

    for pr_num, level, text, output_file in entries:
        if output_file.exists() and not args.force:
            print(f"\nSkip (exists) -> {output_file}")
            continue

        print(f"\nGenerating audio for PR #{pr_num} level '{level}' ({len(text)} characters)...")
        print(f"Script: \"{text[:100]}...\"")

        try:
            response = client.models.generate_content(
                model=args.model,
                contents=text,
                config=config
            )

            # Extract audio bytes
            audio_bytes = None
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    audio_bytes = part.inline_data.data
                    break

            if audio_bytes:
                # Save as a valid WAV file with headers (Gemini TTS returns raw 16-bit 24kHz mono PCM)
                import wave
                try:
                    with wave.open(str(output_file), "wb") as wav_file:
                        wav_file.setnchannels(1)  # Mono
                        wav_file.setsampwidth(2)  # 16-bit = 2 bytes
                        wav_file.setframerate(24000)  # 24kHz sample rate
                        wav_file.writeframes(audio_bytes)
                    print(f"Success -> Saved audio to {output_file.resolve()}")
                except Exception as wave_err:
                    print(f"Error writing WAV file: {wave_err}", file=sys.stderr)
                    # Fallback to saving raw bytes
                    with open(output_file, "wb") as f:
                        f.write(audio_bytes)
                    print(f"Fallback -> Saved raw audio bytes to {output_file.resolve()}")

            else:
                print(f"Error: No audio data returned for PR #{pr_num} level '{level}'", file=sys.stderr)

        except Exception as e:
            print(f"Failed to generate audio for PR #{pr_num} level '{level}': {e}", file=sys.stderr)

    print("\nAudio generation complete!")


if __name__ == "__main__":
    main()
