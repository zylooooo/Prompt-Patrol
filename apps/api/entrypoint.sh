#!/bin/sh
# Bring the schema up to date, then serve.
#
# Nothing applied migrations before this: a container pointed at a fresh
# database came up, answered its health check, and failed every real request.
# A half-working API is worse than one that refuses to start, so `set -e` means
# a failed migration takes the container down where compose and the logs show
# it, rather than leaving it serving 500s.
#
# One API container is assumed. Two starting at once would both try to migrate,
# and the loser exits and is restarted - by which point the schema is already at
# head, so the retry is a no-op and it starts clean. That self-heals, but if
# this ever runs more than one replica, move the migration to its own one-shot
# step instead of racing on boot.
set -e

echo "Applying database migrations..."
alembic upgrade head

# exec so uvicorn becomes PID 1 and receives stop signals directly. Without it
# the shell holds PID 1, swallows SIGTERM, and every shutdown waits out
# Docker's ten-second timeout before being killed.
exec python main.py
