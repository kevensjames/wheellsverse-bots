"""Real disposable-container sandbox — proves the envelope end-to-end.

Skipped when Docker or the base image is unavailable, so it never breaks CI in a
constrained environment; runs for real where Docker + the cached image exist.
"""
import subprocess

import pytest

from app.services.swe_runtime.config import SandboxPolicy
from app.services.swe_runtime.sandbox import DockerSandbox, docker_available

IMAGE = "python:3.11-slim"

pytestmark = pytest.mark.skipif(not docker_available(), reason="docker not available")


def _image_present() -> bool:
    return subprocess.run(["docker", "image", "inspect", IMAGE],
                          capture_output=True).returncode == 0


needs_image = pytest.mark.skipif(not _image_present(), reason=f"{IMAGE} not cached")


@pytest.fixture()
def source(tmp_path):
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a - b  # bug\n")
    return str(tmp_path)


@needs_image
def test_edits_disposable_copy_and_captures_artifacts(source):
    res = DockerSandbox().run(
        source_dir=source,
        command="sed -i 's/a - b/a + b/' lib.py && echo done > RESULT.txt",
        policy=SandboxPolicy(),
    )
    assert res.exit_code == 0 and not res.timed_out and res.error is None
    assert "a + b" in res.artifacts["lib.py"]           # patch produced on the copy
    assert res.artifacts["RESULT.txt"].strip() == "done"


@needs_image
def test_network_is_cut(source):
    res = DockerSandbox().run(
        source_dir=source,
        command=("python -c \"import urllib.request; "
                 "urllib.request.urlopen('http://example.com', timeout=5)\" "
                 "&& echo LEAK || echo cut"),
        policy=SandboxPolicy(),
    )
    assert "LEAK" not in res.stdout
    assert "cut" in res.stdout


@needs_image
def test_wall_clock_timeout_kills(source):
    p = SandboxPolicy()
    p.timeout_seconds = 2
    res = DockerSandbox().run(source_dir=source, command="sleep 30", policy=p)
    assert res.timed_out is True and res.exit_code == 124


@needs_image
def test_host_source_is_not_mutated(source, tmp_path):
    # The agent edits the disposable copy; the HOST source is never touched.
    DockerSandbox().run(source_dir=source, command="echo hacked > lib.py",
                        policy=SandboxPolicy())
    assert "return a - b" in (tmp_path / "lib.py").read_text()  # host unchanged


@needs_image
def test_symlink_to_host_file_is_not_followed(source):
    # A container-planted symlink to a HOST path (docker cp preserves symlinks)
    # must NOT be dereferenced by the artifact collector — else host file content
    # would escape the sandbox. /etc/passwd exists on the host; the collector
    # must skip the symlink, never read it.
    res = DockerSandbox().run(
        source_dir=source,
        command="ln -s /etc/passwd /work/leak && echo ok > RESULT.txt",
        policy=SandboxPolicy(),
    )
    assert "leak" not in res.artifacts                       # symlink skipped
    assert "root:" not in "".join(res.artifacts.values())    # no host content leaked
    assert res.artifacts["RESULT.txt"].strip() == "ok"       # real files still captured


@needs_image
def test_symlink_to_device_does_not_hang(source):
    # `ln -s /dev/zero` would cause an unbounded read (size reports 0, evading the
    # cap) if followed — the collector must skip it and finish promptly.
    p = SandboxPolicy()
    p.timeout_seconds = 30
    res = DockerSandbox().run(
        source_dir=source,
        command="ln -s /dev/zero /work/z && echo ok > RESULT.txt",
        policy=p,
    )
    assert "z" not in res.artifacts                           # device symlink skipped
    assert res.artifacts["RESULT.txt"].strip() == "ok"
