# Prompt Patrol — web

React 19 + TypeScript + Vite frontend. See the [repo README](../../README.md) for
running the full stack; this file covers the frontend toolchain only.

## Scripts

| Script              | What it does                                          |
| ------------------- | ----------------------------------------------------- |
| `npm run dev`       | Vite dev server on <http://localhost:5173>, `/api` proxied to `http://localhost:8000` |
| `npm run build`     | Typecheck, then production bundle                      |
| `npm run lint`      | ESLint                                                 |
| `npm run lint:fix`  | ESLint with autofix                                    |
| `npm run typecheck` | `tsc -b` on its own, without building                  |

## Node version

Node `^20.19.0 || ^22.13.0 || >=24` (see `engines` in `package.json`, and
`.nvmrc` for the version this project is developed against — `nvm use` picks it
up). Both ESLint 10 and Vite 8's bundler call `util.styleText`, which older 20.x
releases don't have: on Node 20.11 `npm run lint` crashes in the output
formatter instead of reporting errors, and `npm run build` fails outright. CI
runs Node 25.

`nvm use` only lasts for the current shell. If new terminals keep landing on an
old version, your default alias is stale — fix it with `nvm alias default 22`.

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
