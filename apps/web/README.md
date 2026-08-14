# Prompt Patrol — web

React 19 + TypeScript + Vite frontend. See the [repo README](../../README.md) for
running the full stack; this file covers the frontend toolchain only.

## Scripts

| Script              | What it does                                                                          |
| ------------------- | ------------------------------------------------------------------------------------- |
| `npm run dev`       | Vite dev server on <http://localhost:5173>, `/api` proxied to `http://localhost:8000` |
| `npm run build`     | Typecheck, then production bundle                                                     |
| `npm run lint`      | ESLint                                                                                |
| `npm run lint:fix`  | ESLint with autofix                                                                   |
| `npm run typecheck` | `tsc -b` on its own, without building                                                 |

## Node version

Node 24 (Active LTS, security-supported until 2028-04-30). **`.nvmrc` is the
single source of truth** — every environment derives its version from that one
file rather than restating it:

| Environment | How it gets the version                                                                                              |
| ----------- | -------------------------------------------------------------------------------------------------------------------- |
| Local shell | `nvm use` reads `.nvmrc` directly                                                                                    |
| CI          | `setup-node`'s `node-version-file: .nvmrc`                                                                           |
| Docker      | CI passes `--build-arg NODE_VERSION="$(cat .nvmrc)"`; the `ARG` default is only a fallback for a bare `docker build` |

Three things still name a version independently, because none of them can read a
file: the `ARG NODE_VERSION` default in the `Dockerfile`, `engines` in
`package.json`, and `@types/node` (its major should track the runtime, so Node
APIs are typed as the version actually running). The `Check Node version
declarations agree` step in CI asserts all three still match `.nvmrc`, so drift
fails the build instead of surfacing later as an unrelated-looking error.

Keep `.nvmrc` a **numeric** version (`24`, or `24.19.0` to pin a patch). nvm also
accepts aliases like `lts/*`, but Docker image tags don't, so CI validates the
file and fails with a pointed error rather than building against an unintended
tag. A bare major is the usual choice — it picks up patch releases, including
security fixes, without another edit here.

`.nvmrc` lives at the **repo root**, not here. nvm searches _upwards_, so
`nvm use` resolves to it from this directory or anywhere else in the tree, and
one file covers every working directory — a per-app copy would be the second
declaration this arrangement exists to avoid. It only lasts for the current
shell, so if new terminals keep landing on an old version your default alias is
stale — fix it with `nvm alias default 24`, or add the `chpwd` hook from nvm's
README to switch automatically on `cd`.

Forgetting `nvm use` is not silent. `.npmrc` sets `engine-strict=true`, which
promotes the `engines` range from an `EBADENGINE` warning into a hard failure, so
`npm install`/`npm ci` stops immediately and names the version problem instead of
letting it surface later as a bundler `SyntaxError`. The `Dockerfile` copies
`.npmrc` alongside `package*.json` so the same gate applies inside the image.

`engines` is `>=24`. Node 20 is excluded even though ESLint and Vite still accept
`^20.19.0`: that line went EOL 2026-04-30, and anything below 20.12 breaks
outright, since both ESLint 10 and Vite 8's bundler import `util.styleText`,
which older 20.x releases don't export. On Node 20.11 `npm run build` dies with a
`SyntaxError` from rolldown, and `npm run lint` crashes in the output formatter
instead of reporting errors.

Node 25 was rejected despite being newer: odd-numbered lines are never LTS, and
25 went EOL on 2026-06-01 with 23 CVEs (5 High) fixed on the supported lines
afterwards that it will never receive.

## Linting

ESLint flat config in `eslint.config.js`, with `typescript-eslint`'s
**type-checked** preset. The rules run against the real typechecker via
`projectService`, so they catch things an AST-only linter can't — unawaited
promises, `async` handlers passed where a `void` return is expected, unnecessary
conditions on non-nullable values.

Three config groups:

- `src/**/*.{ts,tsx}` — type-aware, browser globals, plus `react-hooks` and
  `react-refresh` (the latter keeps Vite's HMR boundaries valid).
- `vite.config.ts` — type-aware, Node globals; covered by `tsconfig.node.json`.
- `**/*.config.js` — plain JS, not type-aware. These aren't in any tsconfig, and
  pulling them in via `allowDefaultProject` isn't worth it for static config.

`tsconfig.app.json` and `tsconfig.node.json` both set `"strict": true`. Several
type-aware rules (`no-unnecessary-condition` in particular) are much weaker
without `strictNullChecks`, so keep it on.

This replaced Oxlint, which was faster but had no type-aware rules wired up.
Don't run both — one linter, one config.
