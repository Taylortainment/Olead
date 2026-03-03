#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Install htmlhint for HTML linting
npm install -g htmlhint --prefer-offline 2>&1 || npm install -g htmlhint 2>&1
