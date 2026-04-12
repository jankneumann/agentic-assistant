#!/usr/bin/env bash
# scripts/init-persona-repo.sh
# Usage: ./scripts/init-persona-repo.sh <target-dir>
#
# Scaffolds a new private persona-config repo from personas/_template/.

set -euo pipefail

TARGET="${1:?Usage: init-persona-repo.sh <target-dir>}"

if [ -d "${TARGET}" ]; then
    echo "Directory '${TARGET}' already exists."
    exit 1
fi

cp -r personas/_template "${TARGET}"
cd "${TARGET}"
git init -q
git add .
git commit -q -m "Initial persona config from template"
echo "Done. Next steps:"
echo "  cd ${TARGET}"
echo "  git remote add origin <your-private-repo-url>"
echo "  git push -u origin main"
