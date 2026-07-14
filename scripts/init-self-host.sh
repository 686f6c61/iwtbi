#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
EXAMPLE_FILE="$ROOT_DIR/.env.example"

if [[ -e "$ENV_FILE" ]]; then
  echo "Refusing to overwrite existing $ENV_FILE" >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate local secrets." >&2
  exit 1
fi

umask 077
cp "$EXAMPLE_FILE" "$ENV_FILE"

replace_empty() {
  local name="$1"
  local value="$2"
  local escaped_value="${value//&/\\&}"
  sed -i.bak "s|^${name}=$|${name}=${escaped_value}|" "$ENV_FILE"
}

replace_empty POSTGRES_PASSWORD "$(openssl rand -hex 32)"
replace_empty INTERNAL_ANALYZE_TOKEN "$(openssl rand -hex 32)"
replace_empty EMAIL_UNSUBSCRIBE_SECRET "$(openssl rand -hex 32)"
rm -f "$ENV_FILE.bak"

echo "Created $ENV_FILE with fresh local secrets."
echo "Set your AI provider credentials and model, then run:"
echo "  docker compose up --build"
