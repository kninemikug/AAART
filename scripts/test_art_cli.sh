#!/bin/bash
# scripts/test_art_cli.sh
set -e

CLI_PATH="${ART_CLI_PATH:-./build/rtgui/ART-cli}"
RAW_FILE="${ART_RAW_FILE:-data/fivek_sample/sample1.nef}"
PROFILE="${1:-data/test_profile.arp}"
OUT_DIR="${2:-data/fivek_sample}"

echo "Running ART-cli on $RAW_FILE..."

if [ "$#" -gt 2 ] || [ ! -x "$CLI_PATH" ] || [ ! -f "$RAW_FILE" ] || [ ! -f "$PROFILE" ]; then
    echo "Usage: test_art_cli.sh [profile.arp [output-directory]]; CLI, RAW and profile must exist." >&2
    exit 1
fi

if [ "$#" -gt 0 ]; then
    T19_PYTHON="${T19_PYTHON:-./venv/bin/python3}"
    env PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" "$T19_PYTHON" -c \
        'from pathlib import Path; import sys; from artagent.arp.generator import parse_profile; parse_profile(Path(sys.argv[1]).read_text(encoding="utf-8"))' "$PROFILE"
fi

command -v djpeg >/dev/null
mkdir -p "$OUT_DIR"
if [ "$RAW_FILE" -ef "${OUT_DIR}/sample1.jpg" ]; then
    echo "Output would overwrite the input image." >&2
    exit 1
fi
WORK_DIR="$(mktemp -d "${OUT_DIR%/}/.t19-render.XXXXXX")"
trap 'rm -f -- "$WORK_DIR/sample1.jpg"; rmdir -- "$WORK_DIR"' EXIT
RAW_SIGNATURE="$(cksum < "$RAW_FILE")"

"$CLI_PATH" -a -Y -j92 -o "$WORK_DIR/sample1.jpg" -p "$PROFILE" -c "$RAW_FILE"

if [ ! -s "$WORK_DIR/sample1.jpg" ] || [ "$RAW_SIGNATURE" != "$(cksum < "$RAW_FILE")" ]; then
    echo "FAILED: New output is missing/empty or the RAW changed." >&2
    exit 1
fi
djpeg -strict -outfile /dev/null "$WORK_DIR/sample1.jpg"
mv -f -- "$WORK_DIR/sample1.jpg" "${OUT_DIR}/sample1.jpg"
echo "SUCCESS: Fresh JPEG generated and decoded: ${OUT_DIR}/sample1.jpg"
