import { down } from "./stack.ts";

export default function globalTeardown() {
  // E2E_KEEP_STACK=1 leaves the stack up for debugging a failed run.
  if (process.env.E2E_KEEP_STACK !== "1") down();
}
