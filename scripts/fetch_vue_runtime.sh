#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-3.5.13}"
OUTFILE="${2:-static/js/vue.global.prod.js}"

URL="https://unpkg.com/vue@${VERSION}/dist/vue.global.prod.js"
echo "Downloading Vue runtime from ${URL}"

mkdir -p "$(dirname "${OUTFILE}")"

curl -fsSL "${URL}" -o "${OUTFILE}"

if grep -Eq "Vue stub loaded|Vue stub:" "${OUTFILE}"; then
  echo "Downloaded file still looks like the stub. Aborting." >&2
  exit 1
fi

echo "OK: wrote ${OUTFILE}"
