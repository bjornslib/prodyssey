/**
 * odysseyHost.ts — SDK/extension-host half of the Prodyssey VS Code spike.
 *
 * This module builds the `query()` invocation for driving the bundled
 * `odyssey` Claude Code skill against a target repo, and maps the resulting
 * SDK message stream to human-readable progress strings. It performs NO live
 * SDK call on its own — see the `// LIVE RUN (local only):` marker below for
 * the one function that would actually spawn the `claude` subprocess, which
 * this file never invokes.
 *
 * All option shapes below were verified against the REAL installed types in
 * node_modules/@anthropic-ai/claude-agent-sdk/sdk.d.ts (v0.3.218), not
 * guessed. See ../FINDINGS.md section 2b for the ground-truth citations and
 * any deltas from the task's original assumptions.
 */

import * as path from 'node:path';
import {
  query,
  type CanUseTool,
  type Options,
  type PermissionResult,
  type SDKMessage,
} from '@anthropic-ai/claude-agent-sdk';

// ---------------------------------------------------------------------------
// Sanctioned surface
// ---------------------------------------------------------------------------

/**
 * Bash command prefixes that canUseTool auto-approves. A command is approved
 * only if it IS one of these prefixes or starts with `${prefix} ` — a plain
 * substring match (e.g. "gitxyz" or "cp -rf /") would be wrong, so we always
 * check on a word boundary.
 */
const SANCTIONED_BASH_PREFIXES = [
  'uv run',
  'git',
  'python3 -m http.server',
  'mkdir',
  'cp',
  'ln',
] as const;

/**
 * Tools canUseTool is willing to reason about at all. Everything else is
 * denied outright. This list intentionally mirrors `allowedTools` below —
 * see FINDINGS.md for why this is narrower than what the real odyssey skill
 * needs end-to-end (it also directly edits story.json/adrs.json via
 * Write/Edit during narrative authoring, which this sanctioned surface does
 * NOT include; a full build-out would extend both lists with the same
 * cwd-containment discipline used for Read/Grep/Glob here).
 */
const SANCTIONED_TOOLS = ['Read', 'Grep', 'Glob', 'Bash'] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Resolves `candidate` against `root` (absolute candidates pass through, per node:path semantics) and reports whether the result stays inside root. */
function isWithinRoot(candidate: string, root: string): boolean {
  const resolvedRoot = path.resolve(root);
  const resolvedCandidate = path.resolve(root, candidate);
  const rel = path.relative(resolvedRoot, resolvedCandidate);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/** Pulls the filesystem path a Read/Grep/Glob call would touch, if any. Read uses `file_path`; Grep/Glob use an optional `path`. */
function extractPathCandidate(
  toolName: 'Read' | 'Grep' | 'Glob',
  input: Record<string, unknown>,
): string | undefined {
  if (toolName === 'Read') {
    return typeof input.file_path === 'string' ? input.file_path : undefined;
  }
  return typeof input.path === 'string' ? input.path : undefined;
}

function isSanctionedBashCommand(command: string): boolean {
  const trimmed = command.trim();
  return SANCTIONED_BASH_PREFIXES.some(
    (prefix) => trimmed === prefix || trimmed.startsWith(`${prefix} `),
  );
}

/**
 * Builds the `canUseTool` callback for a given target-repo cwd. Approves:
 *   - Read/Grep/Glob whose target path (if any) resolves inside `cwd`.
 *   - Bash whose command starts with one of SANCTIONED_BASH_PREFIXES.
 * Denies everything else, including any tool call outside SANCTIONED_TOOLS
 * (defense in depth — `allowedTools`/`tools` should already keep the model
 * from offering other tools, but canUseTool fails closed regardless).
 */
export function buildCanUseTool(cwd: string): CanUseTool {
  const root = path.resolve(cwd);

  return async (toolName, rawInput, _options): Promise<PermissionResult> => {
    const input = isRecord(rawInput) ? rawInput : {};

    if (!(SANCTIONED_TOOLS as readonly string[]).includes(toolName)) {
      return {
        behavior: 'deny',
        message: `Tool "${toolName}" is outside Prodyssey's sanctioned surface (${SANCTIONED_TOOLS.join(', ')}).`,
      };
    }

    if (toolName === 'Read' || toolName === 'Grep' || toolName === 'Glob') {
      const candidate = extractPathCandidate(toolName, input);
      if (candidate === undefined || isWithinRoot(candidate, root)) {
        return { behavior: 'allow' };
      }
      return {
        behavior: 'deny',
        message: `${toolName} target "${candidate}" resolves outside the sanctioned repo root (${root}).`,
      };
    }

    // toolName === 'Bash'
    const command = typeof input.command === 'string' ? input.command : undefined;
    if (command !== undefined && isSanctionedBashCommand(command)) {
      return { behavior: 'allow' };
    }
    return {
      behavior: 'deny',
      message: `Bash command "${command ?? '<non-string command>'}" is not on the sanctioned prefix list (${SANCTIONED_BASH_PREFIXES.join(', ')}).`,
    };
  };
}

// ---------------------------------------------------------------------------
// Options builder
// ---------------------------------------------------------------------------

export interface BuildGenerateOptionsInput {
  /** Absolute path to the bundled plugin directory copied into the .vsix (spike/host/plugin/ at dev time). */
  pluginRoot: string;
  /** Absolute path to the repo being analyzed (becomes the session cwd). */
  targetRepo: string;
  /** ANTHROPIC_API_KEY value, if the user supplied one (subscription OAuth users may omit this — see FINDINGS.md 2c). */
  anthropicKey?: string;
  /** GEMINI_API_KEY value for scene art + narration; required by the skill's own prereq gate. */
  geminiKey?: string;
  /** Forwarded verbatim into the generate prompt, e.g. "--latest" or "--prs 12,14". */
  prSelection: string;
}

export interface OdysseyInvocation {
  prompt: string;
  options: Options;
}

function buildEnv(anthropicKey: string | undefined, geminiKey: string | undefined): NonNullable<Options['env']> {
  // Options.env REPLACES the subprocess environment entirely (does not merge
  // with process.env) — see sdk.d.ts around the `env` option's doc comment.
  // We therefore spread process.env ourselves so PATH/HOME/etc. survive.
  const env: NonNullable<Options['env']> = { ...process.env };
  if (anthropicKey) env.ANTHROPIC_API_KEY = anthropicKey;
  if (geminiKey) env.GEMINI_API_KEY = geminiKey;
  return env;
}

function buildBaseOptions(
  pluginRoot: string,
  targetRepo: string,
  anthropicKey: string | undefined,
  geminiKey: string | undefined,
): Options {
  const cwd = path.resolve(targetRepo);
  return {
    // SdkPluginConfig requires `type: 'local'` — a bare `{ path }` does NOT
    // type-check against the real sdk.d.ts. See FINDINGS.md 2b delta #1.
    plugins: [{ type: 'local', path: path.resolve(pluginRoot) }],
    skills: ['odyssey'],
    allowedTools: [...SANCTIONED_TOOLS],
    cwd,
    env: buildEnv(anthropicKey, geminiKey),
    canUseTool: buildCanUseTool(cwd),
    // Isolation mode: don't let the extension host's own ~/.claude or
    // project .claude/settings.json leak into the target repo's session.
    settingSources: [],
    permissionMode: 'default',
  };
}

/**
 * Builds the exact `{ prompt, options }` pair for `query()` in Generate mode.
 */
export function buildGenerateOptions(input: BuildGenerateOptionsInput): OdysseyInvocation {
  return {
    prompt: `Run the odyssey skill in generate mode: generate ${input.prSelection}`,
    options: buildBaseOptions(input.pluginRoot, input.targetRepo, input.anthropicKey, input.geminiKey),
  };
}

export interface BuildBaselineOptionsInput {
  pluginRoot: string;
  targetRepo: string;
  anthropicKey?: string;
  geminiKey?: string;
}

/**
 * Baseline mode's own prompt/options pair, symmetric with buildGenerateOptions.
 * Baseline doesn't call Gemini per SKILL.md ("Only after all three checks
 * pass does mode dispatch begin" — the GEMINI_API_KEY gate is specific to
 * Generate's default sweep), but we still thread it through so a caller that
 * has the key can pass it without the two code paths diverging in shape.
 */
export function buildBaselineOptions(input: BuildBaselineOptionsInput): OdysseyInvocation {
  return {
    prompt: 'Run the odyssey skill in baseline mode: baseline this repo',
    options: buildBaseOptions(input.pluginRoot, input.targetRepo, input.anthropicKey, input.geminiKey),
  };
}

// ---------------------------------------------------------------------------
// Progress mapping
// ---------------------------------------------------------------------------

/** Human-readable description of a tool_use content block, or null if it doesn't map to a user-facing progress step. */
function describeToolUse(name: string, rawInput: unknown): string | null {
  const input = isRecord(rawInput) ? rawInput : {};
  const command = typeof input.command === 'string' ? input.command : '';
  const filePath =
    typeof input.file_path === 'string'
      ? input.file_path
      : typeof input.path === 'string'
        ? input.path
        : '';

  if (name === 'Bash') {
    if (command.includes('extract_diffs.py')) return 'extracting PR diffs';
    if (command.includes('extract_story.py')) return 'deriving story seed and baseline';
    if (command.includes('generate_prompts.py')) return 'generating scene art';
    if (command.includes('generate_audio.py')) return 'generating voice narration';
    if (command.includes('verify_bundle.py')) return 'verifying the odyssey bundle';
    if (command.includes('http.server')) return 'starting the local viewer server';
    if (command.startsWith('git')) return 'inspecting repo history';
    if (command.startsWith('mkdir') || command.startsWith('cp') || command.startsWith('ln')) {
      return 'assembling bundle files';
    }
    return 'running a shell command';
  }
  if (name === 'Read') return `reading ${filePath || 'a file'}`;
  if (name === 'Grep') return 'searching the codebase';
  if (name === 'Glob') return 'listing files';
  if (name === 'Skill') return 'invoking the odyssey skill';
  if (name === 'Write' || name === 'Edit') {
    if (filePath.includes('story.json') || filePath.includes('story.js')) return 'authoring narrative';
    if (filePath.includes('inventory.yaml')) return 'mapping repo architecture';
    if (filePath.includes('adrs')) return 'extracting architecture decision records';
    return `writing ${filePath || 'bundle output'}`;
  }
  return null;
}

/**
 * Maps one SDKMessage to zero or more human progress strings. A single
 * assistant message can contain several tool_use blocks, hence the array
 * return.
 */
export function mapMessageToProgress(message: SDKMessage): string[] {
  switch (message.type) {
    case 'system':
      return message.subtype === 'init' ? ['starting odyssey session'] : [];
    case 'assistant': {
      const out: string[] = [];
      for (const block of message.message.content) {
        if (block.type === 'tool_use') {
          const described = describeToolUse(block.name, block.input);
          if (described) out.push(described);
        }
      }
      return out;
    }
    case 'tool_progress':
      return message.heartbeat ? [] : [`still working (${message.tool_name})`];
    case 'result':
      return message.subtype === 'success'
        ? [`done in ${(message.duration_ms / 1000).toFixed(1)}s`]
        : [`failed: ${message.subtype}`];
    default:
      return [];
  }
}

// ---------------------------------------------------------------------------
// Consumer
// ---------------------------------------------------------------------------

export type ProgressSink = (text: string) => void;

/**
 * Async consumer contract: given an already-built invocation, iterate the
 * SDK's async generator and forward mapped progress strings to `onProgress`.
 * Resolves to the final SDKResultMessage (or undefined if the stream ended
 * without one, which should not happen in practice).
 *
 * This function is exported so extension.ts can call it, but nothing in THIS
 * module (or anywhere else in the spike) invokes it — see runLiveGenerate
 * below, which is the only place `query()` is actually reachable, and it is
 * never called either. No network/subprocess activity happens by importing
 * or type-checking this file.
 */
export async function consumeOdysseyStream(
  stream: AsyncIterable<SDKMessage>,
  onProgress: ProgressSink,
): Promise<SDKMessage | undefined> {
  let last: SDKMessage | undefined;
  for await (const message of stream) {
    last = message;
    for (const text of mapMessageToProgress(message)) {
      onProgress(text);
    }
  }
  return last;
}

/**
 * The one place `query()` is actually called. NOT invoked anywhere in this
 * spike (grep the repo — there is no call site). extension.ts's real F5 run
 * would call this; here it only needs to type-check against the real SDK
 * types installed in node_modules.
 */
export async function runLiveGenerate(
  invocation: OdysseyInvocation,
  onProgress: ProgressSink,
): Promise<SDKMessage | undefined> {
  // LIVE RUN (local only): this is the only line in the spike that would
  // spawn the `claude` subprocess and make a real Anthropic/Gemini API call.
  // Left un-invoked deliberately — see FINDINGS.md and RUNBOOK.md.
  for await (const message of query({ prompt: invocation.prompt, options: invocation.options })) {
    for (const text of mapMessageToProgress(message)) {
      onProgress(text);
    }
    if (message.type === 'result') {
      return message;
    }
  }
  return undefined;
}
