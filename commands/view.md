---
title: "Odyssey: View Bundle"
status: active
type: command
last_verified: 2026-07-20
---

# Odyssey: View Bundle

Serves the bundled viewer in the background and prints the URL to open — the
session keeps going while the server runs.

Invoke the `odyssey` skill in view mode, forwarding any arguments the user
supplied after `/prodyssey:view` (`--repo <path>`, `--store local|central`,
`--port <N>`, `--stop`, `--list`):

```
Skill("odyssey", args="view $ARGUMENTS")
```

View mode discovers ALL known bundles for this hub — the hub's own
self-analysis bundle at `<target>/.odyssey/` (if present) plus every
centrally-stored foreign-repo bundle under `<hub>/.prodyssey/` — then picks
which one to serve:

- `--repo <path>` selects that repo's bundle directly, no prompt. If that
  repo was baselined/generated with a non-default `--store` mode, pass the
  same `--store` here too — otherwise the resolved location won't match
  where the bundle actually is, and the skill will tell you to run
  `/prodyssey:baseline` rather than finding a stale-looking bundle.
- No `--repo` and exactly one bundle is known → it's auto-selected.
- No `--repo` and multiple bundles are known → the skill lists them and asks
  which one to view.
- `--list` just prints the discovered bundles without starting or switching
  anything.

Switching which bundle is being viewed never restarts the server or changes
the port — it repoints an internal symlink, so just refresh the browser tab
after switching.

View mode needs neither `uv` nor `GEMINI_API_KEY` — it only serves static
files already written by `/prodyssey:baseline` / `/prodyssey:generate`. If no
bundle exists yet, the skill will tell you to run `/prodyssey:baseline` first
rather than starting a server against nothing.

## Examples

```
/prodyssey:view
/prodyssey:view --list
/prodyssey:view --repo ~/code/other-project
/prodyssey:view --port 9000
/prodyssey:view --stop
```
