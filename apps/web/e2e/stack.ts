import { execSync } from "node:child_process";

// Run from apps/web, so the compose file is a sibling app's.
const COMPOSE = "docker compose -f ../e2e/docker-compose.yml";

export function up() {
  // CI pre-builds the images with bake, so only local runs build here.
  const build = process.env.CI ? "" : " --build";
  execSync(`${COMPOSE} up -d --wait${build}`, {
    stdio: "inherit",
    timeout: 10 * 60 * 1000,
  });
}

export function seed(): string {
  const out = execSync(`${COMPOSE} exec -T api python -m scripts.e2e_seed`, {
    encoding: "utf8",
  });
  // The token is the last line; anything logged before it is noise.
  const lines = out.split(/\r?\n/).filter((line) => line.trim());
  return lines[lines.length - 1].trim();
}

export function down() {
  execSync(`${COMPOSE} down -v`, { stdio: "inherit" });
}
