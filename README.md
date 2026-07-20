# Prodyssey — Codebase Odyssey Generator

Turn any merged pull request into a four-level narrated story — **PR Landscape →
Problem & Solution → Architecture → File Changes** — with generated scene art,
voice narration, and extracted architecture decision records. Runs entirely in
your own Claude Code session against your own checkout: your repo never leaves
your machine, your API keys pay for exactly what you generate.

---

## Install

The plugin lives in its own repository (`bjornslib/prodyssey`) with a
one-plugin marketplace, so installation is two commands in any Claude Code
session:

```
/plugin marketplace add bjornslib/prodyssey
/plugin install prodyssey@prodyssey
```

Restart the session (or `/plugin` → enable) and the `/prodyssey:*` commands are
available in every project.

### Prerequisites

| Requirement | Why | Checked when |
|---|---|---|
| `GEMINI_API_KEY` (env or `.env` in the target repo) | Scene art (Gemini image gen) + TTS narration | **Hard gate on every invocation** — the skill refuses to start any generation and prints a remediation message if absent (AC G2) |
| A git checkout of the target repo | All analysis is local: `git log`, grep, file reads | On invocation |
| `python3` ≥ 3.10 with `uv` | Bundled scripts run via [PEP 723](https://peps.python.org/pep-0723/) inline metadata — `uv run` resolves `google-genai`, `pillow`, `python-dotenv` per script, no venv setup | First script call |

No GitHub token, no server, no database. If you can open the repo in Claude
Code, you can generate its story.

---

## Usage

### One command, full sweep

```
/prodyssey:generate --prs 73,75
```

For each PR: story narrative (4 levels + voice scripts) → ADR retro-extraction
→ `story.json` merge → scene-art prompts + Gemini images (levels 1–3) → TTS
narration. If no baseline exists yet, **`baseline` runs automatically first**
(AC G3) — you never have to know it's a separate step.

```
/prodyssey:generate --latest        # the most recent merged PR
/prodyssey:generate --prs 12..18   # a range
```

### Baseline (explicit)

```
/prodyssey:baseline
```

Derives the repo's **architecture baseline** into `.odyssey/`:

1. **Stack detection** — matches the repo against bundled stack cards
   (`nextjs`, `react-typescript`, `python-fastapi`, `generic` fallback).
2. **District map** — heuristic clustering (top-level dirs weighted by file
   count/size, commit-frequency heat from `git log`, import-edge merge pass),
   Claude names the districts. Degrades honestly: monorepos cluster at package
   manifests (≤12 districts), <20 files → single district, docs-only repos →
   file-type buckets flagged `map_quality: low`.
3. **Context inventory** — per district: `{name, root_paths, purpose}`,
   verified against real import edges (grep both directions — trivial locally),
   flagged `provenance: inferred`. This is what ADR extraction's `maps_to`
   anchors to when the repo has no architecture docs of its own.

Re-run any time; it refreshes in place. `generate` warns when the baseline is
more than 200 commits behind `HEAD`.

### Resumability

Every artifact is checked before it is produced (AC G6). Kill the sweep
mid-run, re-invoke, and completed narratives/images/audio are skipped —
`--force` regenerates.

---

## Output: the bundle

Everything lands in `.odyssey/` in the target repo — a **portable, versioned
bundle** any Odyssey viewer renders:

```
<target>/.odyssey/
  data/{story.json, story.js, adrs.json, adrs.js, manifest.js, diffs-pr{N}.js…, audio/pr{N}_{level}.wav}
  assets/pr-{N}/level-{1..3}.png
  inventory.yaml
  viewer/index.html
```

Commit it, and a share link is just the raw GitHub URL; or import it into the
viewer directly (upload / local path). `schema_version` gates compatibility
(AC G5).

---

## Plugin structure

```
prodyssey/
├── .claude-plugin/
│   ├── plugin.json           # manifest: name "prodyssey", version, keywords
│   └── marketplace.json      # one-plugin marketplace: name "prodyssey", plugins: [{source: "."}]
├── commands/
│   ├── baseline.md           # thin: invokes the skill with args="baseline"
│   └── generate.md           # thin: invokes the skill with args="generate --prs ..."
├── skills/
│   └── odyssey/
│       ├── SKILL.md          # orchestration: prereq gate → baseline → per-PR sweep → bundle verify
│       ├── references/       # extracted from architecture-review-design-maintenance (see below)
│       │   ├── story-mode.md
│       │   ├── decision-records-lite.md
│       │   ├── baseline-derivation.md      # describe-lite: district + inventory procedure
│       │   ├── adr-template.md
│       │   └── stacks/{README,nextjs,react-typescript,python-fastapi,generic}.md
│       └── scripts/
│           ├── extract_story.py            # generalized: any repo path, writes .odyssey/story.json
│           ├── generate_prompts.py         # nanobanana scene-art prompts
│           ├── generate_audio.py           # TTS narration (Gemini voices)
│           ├── extract_diffs.py            # per-PR diff extraction into the bundle
│           └── verify_bundle.py            # schema_version + completeness check (drives resumability)
├── viewer/
│   └── index.html            # portable bundle viewer
└── README.md                 # this file
```

Key manifest fields (`plugin.json`):

```json
{
  "name": "prodyssey",
  "version": "0.1.0"
}
```

No agents, no hooks, no MCP servers, no output styles — deliberately: the
plugin must work in anyone's session without touching their permission or
hook surface. `skills/` and `commands/` are auto-discovered from their
default directory locations, so the manifest doesn't need to declare them
explicitly.

---

## Extraction manifest — what we took from `architecture-review-design-maintenance`

The parent skill is a six-mode governance instrument for a repo you maintain.
Prodyssey needs three of its capabilities, in read-only "lite" form, against
repos with zero architecture docs. The split — both source and target paths
below refer to the `cobuilder-harness` repo this plugin was extracted from:

### Extracted (adapted)

| Source (cobuilder-harness) | Becomes | Adaptation |
|---|---|---|
| `references/story-mode.md` | `references/story-mode.md` | Framework, four-level mapping, register/style rules verbatim. Output target rewired: `.odyssey/story.json` instead of `docs/prototypes/.../story.json`; "gather ADRs with matching `source_pr`" falls back to same-sweep extracted ADRs |
| `references/decision-records.md` | `references/decision-records-lite.md` | Record shape (context/forces/decision/consequences + `delivers` + `maps_to`) kept. **Dropped**: state machine, transition rules, viewpoint regeneration, ADR numbering governance — those govern a maintained doc set, not a generated bundle. `maps_to` targets `inventory.yaml`, records carry `provenance: inferred` |
| `references/architecture-documentation.md` | `references/baseline-derivation.md` | Describe-mode's verification discipline (enumerate modules, grep import edges both directions, never assert an unverified boundary) kept as the inventory procedure. **Dropped**: 8-section canvas, `boundary.yaml` authoring, INVENTORY.md bookkeeping — replaced by the single flat `inventory.yaml` |
| `references/stacks/*` (4 cards + README) | `references/stacks/*` | Verbatim — detection precedence and ADR-topic checklists drive stack detection and extraction prompts |
| `references/templates/adr-template.md` | `references/adr-template.md` | Trimmed frontmatter (no state machine fields) |
| `docs/prototypes/codebase-evolution/data/extract_story.py` | `scripts/extract_story.py` | Generalized: parameterized repo path, PR selection by number (via merge-commit lookup), writes to `.odyssey/`, never overwrites authored/generated narrative fields |
| `docs/prototypes/codebase-evolution/nanobanana/generate_prompts.py` | `scripts/generate_prompts.py` | Reads district/world data from the bundle instead of hand-authored `story.json` fields |
| `utils/generate_audio.py` | `scripts/generate_audio.py` | Unchanged flow (voice scripts → Gemini TTS); output path → `.odyssey/data/audio/` |

### Left behind (deliberately)

| Not extracted | Why |
|---|---|
| **review / maintenance modes** + `saas-checklist.md`, `harness-security.md`, report templates, `compute_scores.py` | Maintainer-facing audit instrument; out of Prodyssey's scope (consensus 7/7) |
| **corpus/** (~170 principle YAMLs) + **books/** (14 vendored volumes) | Audit-depth grounding; story generation needs the style rules and record shapes, not the review corpus. Keeps the plugin download small |
| **decisions-mode governance** (state machine, viewpoints, ADR numbering) | Governs a living doc set in a repo you own; Prodyssey generates immutable bundle records |
| **describe-mode full canvas** | The flat inventory is the `maps_to` anchor; the canvas is documentation-program overhead a foreign repo can't sustain |
| `sync-books.sh`, `sync-corpus.sh`, `html_to_pdf.py` | Corpus maintenance tooling for the parent skill |

Net: the plugin ships **~15 files of prose + 5 scripts** instead of the parent
skill's ~200 — everything judgment-shaped travels as prompts, everything
mechanical travels as scripts, and nothing that presumes you *maintain* the
target repo travels at all.

---

## Viewing the result

- **Bundled viewer**: `python3 -m http.server` in `.odyssey/viewer/`, point it
  at the bundle (`?bundle=<path-or-url>`).
- **Production app** (future): sign in → *Import bundle* → upload `.odyssey/`
  or paste the raw GitHub URL of a committed bundle. Review workflow (approve /
  request changes / per-level comments) works on imported stories.

## Cost

You pay your own way: narrative + ADR extraction on your Claude Code
subscription; images + TTS on your `GEMINI_API_KEY`. Typical PR: 3 images +
3 narration clips ≈ single-digit cents to low single-digit dollars depending
on Gemini tier. The prereq gate exists so you never discover a missing key
three stages into a sweep.
