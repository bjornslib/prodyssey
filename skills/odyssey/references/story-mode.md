---
title: "Story Mode — explain-diff authoring reference"
type: reference
status: active
last_verified: 2026-07-20
owner: bjoerns
---

# Story Mode — explain-diff authoring reference

How to write a per-PR narrative for the Odyssey bundle viewer
(`<target>/.odyssey/data/story.json`). One artifact, two readers: a PM skims
`narration` and gets the plot; a developer reads `detail`/`problem`/`solution` and
gets the mechanism.

## 1. Framework origin

The four-part structure is Geoffrey Litt's **explain-diff** framework
("Understanding is the new bottleneck"): a merged PR is explained as
**Background → Intuition → Code → Quiz**. Background gives a newcomer enough
system context to place the change; Intuition distills the change to its
essence with one concrete example; Code walks the actual diff, grouped by
intent rather than file order; Quiz checks whether the explanation actually
transferred understanding. Story mode adapts the first three parts to the
bundle's four-level schema — see §2. The quiz is not implemented (§5).

## 2. Level mapping

| Level | Schema key | Fed by |
|---|---|---|
| 1 | `landscape` | One-line hook (tagline register) + mechanical summary of size/touched dirs |
| 2 | `problem_solution` | **Background** (deep → narrow) + **Intuition** (essence, concrete toy data, before/after) — written into the `beats` array, see §2a |
| 3 | `architecture` | Design narrative: forces → decision → alternatives-with-rejections → consequences/boundaries → what it enables (drawn from the PR's ADRs) — forces/contract/boundary written into the `beats` array, see §2a |
| 4 | `file_changes` | **Code** section: grouped walkthrough, each group is "why these files belong together," grounded in `git diff --name-only` |

Level 1 is the entry a PM sees first in the timeline scrubber — keep it to a
single sentence a non-engineer can parse plus the raw size numbers. Level 2
is where most of the explain-diff prose lives: `problem` and `solution` are
precise (code identifiers in backticks), `narration` restates the same
content in plain language. Level 3 exists only when the PR carries real
architectural weight — pull `alternatives` and `forces` straight from the
PR's ADRs (`<target>/.odyssey/data/adrs.json`, records with matching
`source_pr`, extracted in the same sweep — see `decision-records-lite.md`); do
not invent options the ADR didn't record. Level 4 is the only level allowed
to name files — group them by shared intent (e.g. "DDD rename & feedback
sidecar," "Pi SDK extension"), 3-6 files per group, with a one-sentence `note`
on why the group is one unit of change.

`verify_bundle.py` requires a non-empty `narration` for level 3 on every PR,
with no exception for PRs that carry no structural decision — so "exists only
when the PR carries real architectural weight" is about the *content*, not
about whether the field gets written. For a PR with zero ADRs (`adrs: []`,
per `decision-records-lite.md` §3.3's "most PRs produce zero or one" rule),
the expected level-3 content is an honest, one- or two-sentence null-decision
statement: say plainly that the PR touches no module boundary, dependency
direction, or public interface, and name what kind of change it actually is
(docs, style, config, test-only, etc.) instead of inventing forces or
alternatives to fill the field. That statement satisfies both this
reference's "only when it carries weight" discipline and `verify_bundle.py`'s
unconditional non-empty check — it is the correct content for a decision-free
PR, not a workaround.

## 2a. The `beats` array (mandatory) — this is what the viewer's cards read

The bundle viewer does **not** read `problem`, `solution`, `forces`,
`decision`, or `consequences` for its Background / Intuition / Forces /
Contract / Boundary cards. Those fields feed other cards on the same screen
(The Problem / The Solution on level 2; the ADR sheet's own Forces/Decision
on level 3, opened by clicking an ADR badge). The beat cards themselves read
one field: `levels.<level>.beats`, present on **both** `problem_solution`
and `architecture`, an array of:

```json
{"kind": "<kind>", "text": "<prose>"}
```

`kind` routes the item to a card and picks its on-screen label — the string
must match exactly, or the item renders under the wrong heading (or is
silently dropped):

| Level | Valid `kind` values | Renders as |
|---|---|---|
| `problem_solution` | `background`, `intuition` | Background card, Intuition card |
| `architecture` | `forces`, `contract`, `boundary` | Forces card(s), Contract card, Boundary card |

Skip `beats` and the viewer shows literal placeholder text — "No background
evidence recorded.", "No architecture beats recorded for this PR." — even
when `problem`/`solution`/`forces`/`decision` are fully written. **Write
`beats` every time you write a level 2 or level 3 entry; it is a required
field in its own right, not optional decoration layered on `problem`/
`solution`/`forces`:**

- **Level 2 `beats`**: at least one `background` item (the deep→narrow
  system context from §3) and at least one `intuition` item (the concrete
  toy example from §3). This is the same content you're already putting in
  `problem`/`solution` — write it again as discrete beat entries. Multiple
  `background` items are fine (one per context layer); one strong
  `intuition` item is usually enough.
- **Level 3 `beats`**: one `forces` item per entry in the `forces` array
  (pulled from the ADR per §2), one `contract` item stating the decision(s)
  made, and one `boundary` item stating the consequences / what the decision
  enables. A PR with zero ADRs still needs a `beats` array — a single
  `boundary` item carrying the null-decision statement from §2 satisfies it.

Register: `beats` text is developer-precise (the `detail`-register rules in
§4 — code identifiers in backticks, exact numbers), matching `problem`/
`solution`/`forces`, never the PM-plain `narration` register.

## 3. Style rules (mandatory)

- Write with the clarity and flow of Martin Kleppmann: short declarative
  sentences building to a compound one, technical precision without jargon
  for its own sake, one idea per paragraph.
- **Background starts deep, narrows to the change.** Open with enough of how
  the system actually works that a newcomer isn't lost, then close in on the
  specific defect or gap this PR addresses. Ground every claim in the real
  modules touched — read the surrounding code, don't infer behavior from the
  diff alone.
- **Intuition needs one concrete toy example with real numbers and names
  from the PR** — not an abstract description. E.g. "a 60 KB validator
  report truncated at 16 KB" beats "the report could be too large." Pull the
  numbers from the actual diff, logs, or code constants.
- **Explain who runs which computation and why.** When a design shifts work
  from one side of a boundary to another (client vs. server, writer vs.
  reader), say explicitly which side now does the work and what forced that
  choice.
- **Never enumerate files as narrative.** File lists belong only in level 4
  groups. Levels 1-3 describe behavior and decisions, not paths.
- **Smooth transitions.** Each section should read as continuous prose, not
  disconnected bullet fragments stitched together.
- **Narrative arc across PRs.** When a PR's foundation is deliberately reused
  by a later PR, say so — "this PR's plumbing contract is next PR's
  foundation." Check `related_decisions` (`depends-on`) in the ADRs to find
  these threads; render them as `related_decisions`/cross-references in
  level 3, not as speculation.

## 4. Registers

- **`narration` fields** (all levels): plain language, PM-readable. No code
  identifiers, no file paths, no acronyms without a one-clause gloss.
- **`detail` / `problem` / `solution` / `beats[].text` fields** (levels 1, 2,
  3, 4): precise, developer-readable. Code identifiers in backticks
  (`` `DagOrchestrator` ``, `` `worker-done.ts` ``), exact numbers, exact
  paths where the level allows paths (4 only).
- Every level entry that has both a `narration` and a detail-register field
  must say the same thing at two altitudes — never split content between
  them (e.g. don't put a fact only in `detail` that `narration` needs to make
  sense).

## 5. Quiz (documented future extension — do not implement)

Litt's framework closes each explain-diff with a short accountability quiz:
2-3 questions that verify the reader actually understood the change, not
just skimmed it. This is a documented follow-up for the bundle viewer, not
part of story mode today. Suggested schema, for whoever picks this up:

```json
"levels": {
  "quiz": [
    {"q": "Why did the signal-file cap move from 16 KB to 128 KB instead of being removed?",
     "options": ["...", "...", "..."],
     "answer": 1}
  ]
}
```

## 6. Voice narration

`levels.<level>.voice` (string, optional, additive) is the script a TTS model
reads aloud for that level — landscape, problem_solution, and architecture
each get their own. Audio files themselves are not part of the schema; generate
them with the plugin's `scripts/generate_audio.py`, which reads the `voice`
fields straight out of `story.json`:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/generate_audio.py" --repo <target> --bundle-dir <target>/.odyssey --prs <N> --voice Charon   # requires GEMINI_API_KEY (env var or .env)
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/generate_audio.py" --repo <target> --bundle-dir <target>/.odyssey --prs <N> --dry-run          # print scripts, no API calls
```

Output lands at `<target>/.odyssey/data/audio/pr<N>_<level>.wav`
(e.g. `pr73_landscape.wav`), played by the bundle viewer the same
manifest-gated way scene art is. Default voice is `Charon` (informative &
professional — recommended for architecture/tech description). Generation is
per-PR and optional — most PRs will have none.

**TTS register rules (mandatory when writing a `voice` field):**

- Spoken prose only. No backticks, no markdown emphasis, no bullet lists —
  a TTS model reads the string verbatim, including any stray punctuation
  meant as formatting.
- Spell out symbols a voice can't pronounce cleanly: `dot-githooks` not
  `.githooks`, `bridge dot py` not `bridge.py`, "no-verify" as words, not a
  flag rendered in code font.
- Numbers as words where that's how a person would say them in conversation
  ("the eleventh of July," "under a second"); code-adjacent numbers that are
  read as tokens (ADR-0008, PR seventy-three) can stay closer to their
  written form since that's how they're actually said aloud.
- One paragraph per level is normal — voice scripts are not beat-segmented
  the way `problem_solution`/`architecture` prose is.

## 7. Worked example

There is no bundled worked example in this plugin — the parent skill's
exemplar (`narratives-pr68-pr70.md`) lived in the harness repo this was
extracted from and does not travel with the plugin. Calibrate length and tone
from the register rules above: a full four-level PR entry runs roughly the
density of two solid paragraphs per level for `problem_solution` and
`architecture`, one sentence plus numbers for `landscape`, and 3-6 grouped
file notes for `file_changes`.
