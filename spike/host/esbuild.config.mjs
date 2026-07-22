#!/usr/bin/env node
/**
 * esbuild.config.mjs — bundles src/extension.ts -> dist/extension.js.
 *
 * `vscode` is external (VS Code injects its own module at runtime).
 * Everything else, including @anthropic-ai/claude-agent-sdk (an ESM
 * package), gets bundled into a single CommonJS file so `main` in
 * package.json can `require()` it directly with no separate node_modules
 * needed inside the .vsix (aside from the SDK's own optional native-binary
 * packages, which are NOT bundled by esbuild — see FINDINGS.md 2a/5).
 */

import * as esbuild from 'esbuild';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');

/** @type {import('esbuild').BuildOptions} */
const options = {
  entryPoints: [path.join(__dirname, 'src', 'extension.ts')],
  outfile: path.join(__dirname, 'dist', 'extension.js'),
  bundle: true,
  platform: 'node',
  target: 'node18',
  format: 'cjs',
  sourcemap: true,
  external: ['vscode'],
  logLevel: 'info',
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log('[esbuild] watching for changes...');
} else {
  await esbuild.build(options);
}
