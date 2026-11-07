"""Exercise render failure detection and stale-output isolation with a fake CLI."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/test_art_cli.sh"
PROFILE = "[Version]\nVersion=1045\n\n[Exposure]\nEnabled=true\nCompensation=0.3\n"


@pytest.fixture
def render_environment(tmp_path):
    profile = tmp_path / "generated.arp"
    profile.write_text(PROFILE)
    raw = tmp_path / "source.nef"
    raw.write_bytes(b"RAW must be preserved")
    reference = tmp_path / "reference.jpg"
    with reference.open("wb") as output:
        subprocess.run(["cjpeg"], input=b"P6\n2 1\n255\n\xff\x00\x00\x00\xff\x00", stdout=output, check=True)
    executable = tmp_path / "fake-cli"
    executable.write_text("#!/bin/bash\nset -e\nwhile [[ $# -gt 0 ]]; do\n"
                          "if [[ $1 == -o ]]; then dest=$2; shift; fi\nshift\ndone\n"
                          'case "$RENDER_MODE" in\n'
                          'success) cp "$REFERENCE_JPEG" "$dest" ;;\n'
                          'empty) : > "$dest" ;;\n'
                          'corrupt) echo broken > "$dest" ;;\n'
                          'failed) exit 7 ;;\n'
                          'missing) exit 0 ;;\nesac\n')
    executable.chmod(0o755)
    output_dir = tmp_path / "output with spaces"
    output_dir.mkdir()
    stale = output_dir / "sample1.jpg"
    stale.write_bytes(b"old output")
    environment = dict(os.environ, ART_CLI_PATH=str(executable), ART_RAW_FILE=str(raw),
                       T19_PYTHON=sys.executable, REFERENCE_JPEG=str(reference))
    return profile, raw, output_dir, environment


@pytest.mark.parametrize("mode", ["missing", "empty", "corrupt", "failed"])
def test_render_failure_cannot_reuse_stale_jpeg(render_environment, mode):
    profile, raw, output_dir, environment = render_environment
    before = raw.read_bytes()
    process = subprocess.run(["bash", str(SCRIPT), str(profile), str(output_dir)], cwd=ROOT,
                             env=dict(environment, RENDER_MODE=mode), capture_output=True)
    assert process.returncode != 0
    assert (output_dir / "sample1.jpg").read_bytes() == b"old output"
    assert raw.read_bytes() == before


def test_render_success_requires_decodable_fresh_jpeg(render_environment):
    profile, raw, output_dir, environment = render_environment
    process = subprocess.run(["bash", str(SCRIPT), str(profile), str(output_dir)], cwd=ROOT,
                             env=dict(environment, RENDER_MODE="success"), capture_output=True)
    assert process.returncode == 0, process.stderr
    assert (output_dir / "sample1.jpg").read_bytes() == Path(environment["REFERENCE_JPEG"]).read_bytes()
    assert raw.read_bytes() == b"RAW must be preserved"


def test_render_version_conflict_stops_before_cli(render_environment):
    profile, raw, output_dir, environment = render_environment
    profile.write_text(PROFILE.replace("1045", "1044"))
    process = subprocess.run(["bash", str(SCRIPT), str(profile), str(output_dir)], cwd=ROOT,
                             env=dict(environment, RENDER_MODE="success"), capture_output=True)
    assert process.returncode != 0
    assert (output_dir / "sample1.jpg").read_bytes() == b"old output"
