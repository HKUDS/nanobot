#!/usr/bin/env bash
# Advisory reminder before git push.
echo "{\"systemMessage\": \"REMINDER: Run make pre-push before pushing (catches coverage + mypy cache issues that make check misses).\"}"
exit 0
