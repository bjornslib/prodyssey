/**
 * extension.ts — VS Code extension entry point for the Prodyssey spike.
 *
 * Registers prodyssey.generate / prodyssey.baseline / prodyssey.view.
 * Generate/Baseline collect the two API keys via `context.secrets`, check
 * for `uv` and `python3` on PATH, then drive odysseyHost's real `query()`
 * call (see the `// LIVE RUN (local only):` comment below) inside
 * `vscode.window.withProgress`, streaming mapped progress into an
 * OutputChannel. View opens the bundled webview viewer.
 *
 * This file is bundled by esbuild into dist/extension.js and only actually
 * runs inside a VS Code Extension Development Host — nothing in this cloud
 * spike session imports or executes it outside of `tsc --noEmit`.
 */

import { execFileSync } from 'node:child_process';
import * as path from 'node:path';
import * as vscode from 'vscode';

import { buildBaselineOptions, buildGenerateOptions, runLiveGenerate, type OdysseyInvocation } from './odysseyHost';
import { openViewerPanel } from './viewerPanel';

const ANTHROPIC_KEY_SECRET = 'prodyssey.anthropicApiKey';
const GEMINI_KEY_SECRET = 'prodyssey.geminiApiKey';

let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel('Prodyssey');
  context.subscriptions.push(outputChannel);

  context.subscriptions.push(
    vscode.commands.registerCommand('prodyssey.generate', () => driveOdyssey(context, 'generate')),
    vscode.commands.registerCommand('prodyssey.baseline', () => driveOdyssey(context, 'baseline')),
    vscode.commands.registerCommand('prodyssey.view', () => runViewCommand(context)),
  );
}

export function deactivate(): void {
  // No background process to tear down: each command drives one query()
  // call to completion (or the user cancels the notification) rather than
  // keeping a session open across invocations.
}

// ---------------------------------------------------------------------------
// Secrets
// ---------------------------------------------------------------------------

async function getOrPromptSecret(
  context: vscode.ExtensionContext,
  key: string,
  prompt: string,
): Promise<string | undefined> {
  const existing = await context.secrets.get(key);
  if (existing) {
    return existing;
  }

  const entered = await vscode.window.showInputBox({
    title: prompt,
    password: true,
    ignoreFocusOut: true,
  });
  if (!entered) {
    return undefined;
  }

  await context.secrets.store(key, entered);
  return entered;
}

// ---------------------------------------------------------------------------
// Prereq detection
// ---------------------------------------------------------------------------

interface PrereqStatus {
  uv: boolean;
  python3: boolean;
}

function hasExecutable(bin: string): boolean {
  const finder = process.platform === 'win32' ? 'where' : 'which';
  try {
    execFileSync(finder, [bin], { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function checkPrereqs(): PrereqStatus {
  return { uv: hasExecutable('uv'), python3: hasExecutable('python3') };
}

// ---------------------------------------------------------------------------
// Target repo resolution
// ---------------------------------------------------------------------------

async function resolveTargetRepo(): Promise<string | undefined> {
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    return folders[0].uri.fsPath;
  }

  const picked = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    openLabel: 'Select target repo for Prodyssey',
  });
  return picked?.[0]?.fsPath;
}

// ---------------------------------------------------------------------------
// Generate / Baseline
// ---------------------------------------------------------------------------

type Mode = 'generate' | 'baseline';

async function driveOdyssey(context: vscode.ExtensionContext, mode: Mode): Promise<void> {
  const prereqs = checkPrereqs();
  if (!prereqs.uv) {
    vscode.window.showErrorMessage(
      'Prodyssey: `uv` was not found on PATH. Install it (https://docs.astral.sh/uv/getting-started/installation/) and retry.',
    );
    return;
  }
  if (!prereqs.python3) {
    vscode.window.showErrorMessage('Prodyssey: `python3` was not found on PATH. Install Python 3 and retry.');
    return;
  }

  const targetRepo = await resolveTargetRepo();
  if (!targetRepo) {
    vscode.window.showWarningMessage('Prodyssey: no target repo selected; cancelled.');
    return;
  }

  const anthropicKey = await getOrPromptSecret(
    context,
    ANTHROPIC_KEY_SECRET,
    'Enter your ANTHROPIC_API_KEY (leave blank if you use `claude login` / subscription OAuth instead)',
  );
  const geminiKey = await getOrPromptSecret(
    context,
    GEMINI_KEY_SECRET,
    'Enter your GEMINI_API_KEY (required for scene art + narration)',
  );

  if (mode === 'generate' && !geminiKey) {
    vscode.window.showErrorMessage(
      'Prodyssey: GEMINI_API_KEY is required for generate mode\'s default sweep (scene art + narration). Re-run and supply a key.',
    );
    return;
  }

  const pluginRoot = path.join(context.extensionPath, 'plugin');

  let invocation: OdysseyInvocation;
  if (mode === 'generate') {
    const prSelection =
      (await vscode.window.showInputBox({
        title: 'PR selection (e.g. --latest, --prs 12,14, --prs 10..15)',
        value: '--latest',
        ignoreFocusOut: true,
      })) ?? '--latest';
    invocation = buildGenerateOptions({ pluginRoot, targetRepo, anthropicKey, geminiKey, prSelection });
  } else {
    invocation = buildBaselineOptions({ pluginRoot, targetRepo, anthropicKey, geminiKey });
  }

  outputChannel.show(true);
  outputChannel.appendLine(`[prodyssey] ${mode} starting for ${targetRepo}`);
  outputChannel.appendLine(`[prodyssey] prompt: ${invocation.prompt}`);

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Prodyssey: ${mode}`,
      cancellable: false,
    },
    async (progress) => {
      // LIVE RUN (local only): the only reachable call site for
      // odysseyHost.runLiveGenerate (and therefore for the SDK's query(),
      // and therefore for the `claude` subprocess + real Anthropic/Gemini
      // API calls) in this entire spike. It only executes when a human
      // manually triggers this VS Code command inside a running Extension
      // Development Host on their own machine, with real keys supplied
      // above. Nothing in this cloud spike session imports vscode or runs
      // an extension host, so this line is unreachable here.
      const result = await runLiveGenerate(invocation, (text) => {
        progress.report({ message: text });
        outputChannel.appendLine(`[prodyssey] ${text}`);
      });

      if (result?.type === 'result' && result.subtype === 'success') {
        outputChannel.appendLine('[prodyssey] done.');
        vscode.window.showInformationMessage(`Prodyssey: ${mode} finished.`);
      } else {
        outputChannel.appendLine(`[prodyssey] ended without a clean success result: ${JSON.stringify(result)}`);
        vscode.window.showWarningMessage(
          `Prodyssey: ${mode} did not finish cleanly — see the "Prodyssey" output channel for details.`,
        );
      }
    },
  );
}

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

async function runViewCommand(context: vscode.ExtensionContext): Promise<void> {
  const targetRepo = await resolveTargetRepo();
  if (!targetRepo) {
    return;
  }
  const bundleDir = path.join(targetRepo, '.odyssey');
  openViewerPanel(context, bundleDir);
}
