#!/usr/bin/env node
/**
 * copy-plugin.mjs — "bundled inside the .vsix" step.
 *
 * Copies the repo-root Claude plugin (.claude-plugin/, skills/, scripts/,
 * viewer/) into spike/host/plugin/ so the extension can ship a single,
 * self-contained copy of the plugin inside dist/ / the packaged .vsix,
 * rather than depending on the plugin being separately installed.
 *
 * One source of truth (the repo root), copied at build time. Re-run this
 * any time the repo-root plugin content changes and you want the bundled
 * copy refreshed.
 */

import { cp, rm, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// spike/host/scripts -> spike/host -> spike -> repo root
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
// spike/host/scripts -> spike/host
const HOST_ROOT = path.resolve(__dirname, '..');
const DEST_ROOT = path.join(HOST_ROOT, 'plugin');

const ITEMS = ['.claude-plugin', 'skills', 'scripts', 'viewer'];

async function main() {
  console.log(`[copy-plugin] source: ${REPO_ROOT}`);
  console.log(`[copy-plugin] dest:   ${DEST_ROOT}`);

  for (const item of ITEMS) {
    const src = path.join(REPO_ROOT, item);
    if (!existsSync(src)) {
      throw new Error(`[copy-plugin] expected plugin path missing: ${src}`);
    }
  }

  await rm(DEST_ROOT, { recursive: true, force: true });
  await mkdir(DEST_ROOT, { recursive: true });

  for (const item of ITEMS) {
    const src = path.join(REPO_ROOT, item);
    const dest = path.join(DEST_ROOT, item);
    await cp(src, dest, { recursive: true });
    console.log(`[copy-plugin] copied ${item}/`);
  }

  console.log('[copy-plugin] done.');
}

main().catch((err) => {
  console.error('[copy-plugin] FAILED:', err);
  process.exitCode = 1;
});
