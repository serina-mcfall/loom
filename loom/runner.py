"""Running commands, and pretending to, so everything above can be tested."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Result:
    argv: tuple[str, ...]
    cwd: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runner(Protocol):
    def run(self, argv: Sequence[str], cwd: str, timeout: int = 20) -> Result: ...


class SubprocessRunner:
    """The real thing. Never raises for a failing command — failure is data."""

    def run(self, argv: Sequence[str], cwd: str, timeout: int = 20) -> Result:
        argv = tuple(argv)
        try:
            p = subprocess.run(
                argv, cwd=cwd, capture_output=True, text=True, timeout=timeout
            )
            return Result(argv, cwd, p.returncode, p.stdout, p.stderr)
        except FileNotFoundError:
            return Result(argv, cwd, 127, "", f"{argv[0]}: command not found")
        except subprocess.TimeoutExpired:
            return Result(argv, cwd, 124, "", f"{argv[0]}: timed out after {timeout}s")


def key_for(argv: Sequence[str]) -> str:
    return " ".join(argv)


class ReplayRunner:
    """Serves recorded output. Raises on anything unrecorded, on purpose."""

    def __init__(self, recordings: dict[str, dict]) -> None:
        self._recordings = recordings
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str], cwd: str, timeout: int = 20) -> Result:
        argv = tuple(argv)
        self.calls.append(argv)
        rec = self._recordings[key_for(argv)]
        return Result(
            argv, cwd, rec["returncode"], rec.get("stdout", ""), rec.get("stderr", "")
        )


@dataclass
class RecordingRunner:
    """Wraps a real runner and remembers everything, for building fixtures."""

    inner: Runner
    recordings: dict[str, dict] = field(default_factory=dict)

    def run(self, argv: Sequence[str], cwd: str, timeout: int = 20) -> Result:
        r = self.inner.run(argv, cwd, timeout)
        self.recordings[key_for(argv)] = {
            "returncode": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
        return r
