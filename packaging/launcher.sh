#!/usr/bin/env bash
set -euo pipefail

XINGUAN_BIN_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
XINGUAN_APP_DIR="$(CDPATH= cd -- "$XINGUAN_BIN_DIR/../share/xinguan" && pwd)"

export GSK_RENDERER="${GSK_RENDERER:-cairo}"
export PYTHONDONTWRITEBYTECODE=1

# Use the system Python that owns the packaged GTK bindings, not a venv.
if ! /usr/bin/python3 "$XINGUAN_APP_DIR/check_runtime.py"; then
    exit 1
fi
if [[ "${1:-}" == "--check" ]]; then
    exit 0
fi
exec /usr/bin/python3 "$XINGUAN_APP_DIR/app.py" "$@"
