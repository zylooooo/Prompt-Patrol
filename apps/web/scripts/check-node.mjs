// Fails fast, and legibly, when the running Node does not match .nvmrc.
//
// .npmrc's engine-strict only gates install/ci. `npm run dev|build|lint`
// are not engine-checked, so on an older Node they die inside the bundler with
// "does not provide an export named 'styleText'", which names neither Node nor
// the version. This runs as a pre-script for those commands instead.
//
// Reads .nvmrc rather than restating a version, so it follows the single source
// automatically. Deliberately plain ESM: it has to run on whatever Node the
// user actually has, including one too old for the toolchain.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function findNvmrc(startDir) {
  let dir = startDir;
  for (;;) {
    try {
      const path = join(dir, ".nvmrc");
      return { path, value: readFileSync(path, "utf8").trim() };
    } catch {
      const parent = dirname(dir);
      // dirname("/") === "/", so this is the filesystem root
      if (parent === dir) return null;
      dir = parent;
    }
  }
}

const found = findNvmrc(dirname(fileURLToPath(import.meta.url)));

// No .nvmrc means this is not a checkout — the Docker build context is
// apps/web alone, and there the version is already pinned by the base image
// tag that CI derives from .nvmrc. Skip rather than fail the image build.
if (!found) {
  console.log("check:node: no .nvmrc found, skipping (not a checkout).");
  process.exit(0);
}

const wanted = found.value.split(".")[0];
const actual = process.versions.node.split(".")[0];

if (!/^\d+$/.test(wanted)) {
  console.error(
    `.nvmrc must hold a numeric version, got "${found.value}".\n` +
      "Docker image tags cannot resolve aliases like lts/*.",
  );
  process.exit(1);
}

if (wanted !== actual) {
  console.error(
    `\nWrong Node version.\n\n` +
      `  running:  v${process.versions.node}\n` +
      `  required: v${wanted}.x  (from ${found.path})\n\n` +
      `Fix it with:\n\n` +
      `  nvm use\n\n` +
      `If that reports the version is not installed:\n\n` +
      `  nvm install ${wanted}\n\n` +
      `New shells landing on the wrong version means your default alias is\n` +
      `stale; "nvm alias default ${wanted}" changes it permanently.\n`,
  );
  process.exit(1);
}
