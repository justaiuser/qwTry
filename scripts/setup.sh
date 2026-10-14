#!/usr/bin/env bash
set -euo pipefail
cd /workspace/qwTry
command -v tesseract >/dev/null || { echo 'Install Tesseract OCR through the system package manager first.' >&2; exit 1; }
mkdir -p /workspace/.reconciliation/tessdata
python -m venv /workspace/.reconciliation/venv
/workspace/.reconciliation/venv/bin/pip install --no-cache-dir -r requirements.lock
model=/workspace/.reconciliation/tessdata/rus.traineddata
checksum=e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225
if ! printf '%s  %s\n' "$checksum" "$model" | sha256sum --check --status; then
    temporary=$(mktemp /workspace/.reconciliation/tessdata/rus.XXXXXX)
    trap 'rm -f "$temporary"' EXIT
    curl --fail --location --silent --show-error https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/rus.traineddata -o "$temporary"
    printf '%s  %s\n' "$checksum" "$temporary" | sha256sum --check
    mv "$temporary" "$model"
    trap - EXIT
fi
/workspace/.reconciliation/venv/bin/pip check
