#!/usr/bin/env bash
set -euo pipefail   # exit on error, unset vars are errors, trace pipes

# ───── Load conda functions so “conda activate” works ─────
source "$(conda info --base)/etc/profile.d/conda.sh"
#   or: eval "$(conda shell.bash hook)"

# ───── Create / activate env idempotently ─────
ENV_PATH="./env"
if [ ! -d "$ENV_PATH" ]; then
  conda create -y --prefix "$ENV_PATH" python=3.11
fi
conda activate "$ENV_PATH"

# ───── Python deps ─────
pip install --no-cache-dir -r requirements.txt

# ───── Home-brew Postgres (installs only if missing) ─────
if ! brew list postgresql &>/dev/null; then
  brew install postgresql
fi
