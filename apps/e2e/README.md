# Prompt Patrol — e2e stack

The throwaway stack the Playwright smoke suite runs against: Postgres on `tmpfs`, LocalStack, the API, the worker, the frontend, and `detector-stub.py` in place of the real detector.

Don't start it by hand — `cd apps/web && npm run test:e2e` builds, seeds, runs and tears it down in one command.

What it stubs, why, and how to keep it running after a failure are covered in the [frontend README](../web/README.md#end-to-end-tests).
