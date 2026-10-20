#!/usr/bin/env bash
# Run 芯观 directly from a source checkout.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"

export GSK_RENDERER="${GSK_RENDERER:-cairo}"
export PYTHONDONTWRITEBYTECODE=1

exec /usr/bin/python3 "$ROOT/src/app.py" "$@"
