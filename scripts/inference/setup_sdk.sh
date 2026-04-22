#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SDK_DIR="${REPO_ROOT}/vendor/software-agent-sdk"

if [ ! -d "${SDK_DIR}/.git" ]; then
    echo "Cloning OpenHands Agent SDK..."
    git clone --depth 1 https://github.com/OpenHands/software-agent-sdk.git "${SDK_DIR}"
fi

echo "Installing SDK packages into current venv..."
uv pip install -e "${SDK_DIR}/openhands-sdk"
uv pip install -e "${SDK_DIR}/openhands-tools"
uv pip install -e "${SDK_DIR}/openhands-workspace"
uv pip install -e "${SDK_DIR}/openhands-agent-server"

echo "Verifying imports..."
python -c "from openhands.sdk import Agent, Conversation, LLM; print('SDK imports OK')"
python -c "from openhands.workspace import DockerWorkspace; print('Workspace imports OK')"

echo "OpenHands SDK setup complete."
