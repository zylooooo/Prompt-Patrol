import { chromium } from "@playwright/test";
import { down, seed, up } from "./stack.ts";

export default async function globalSetup() {
  // A stack kept by E2E_KEEP_STACK=1 already holds the seeded user, whose
  // fixed email would collide on re-seed. Start from an empty database.
  down();
  up();
  const value = seed();

  const browser = await chromium.launch();
  const context = await browser.newContext();
  await context.addCookies([
    {
      name: "__Host-session",
      value,
      // Not `url`: Chromium rejects a Secure cookie set from an http:// URL,
      // though it still sends one to http://localhost.
      domain: "localhost",
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
  await context.storageState({ path: "e2e/.auth/instructor.json" });
  await browser.close();
}
