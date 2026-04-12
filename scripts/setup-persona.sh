#!/usr/bin/env bash
# scripts/setup-persona.sh
# Usage: ./scripts/setup-persona.sh <persona-name> <private-repo-url>
#
# Mounts a private persona-config repo as a submodule under personas/<persona-name>.

set -euo pipefail

PERSONA_NAME="${1:?Usage: setup-persona.sh <persona-name> <private-repo-url>}"
PRIVATE_URL="${2:?Usage: setup-persona.sh <persona-name> <private-repo-url>}"

if [ -d "personas/${PERSONA_NAME}" ]; then
    echo "Persona '${PERSONA_NAME}' already exists at personas/${PERSONA_NAME}."
    echo "To (re)initialize: git submodule update --init personas/${PERSONA_NAME}"
    exit 1
fi

echo "Mounting persona '${PERSONA_NAME}' from ${PRIVATE_URL}..."
git submodule add "${PRIVATE_URL}" "personas/${PERSONA_NAME}"
echo "Done. Edit personas/${PERSONA_NAME}/persona.yaml to configure."
