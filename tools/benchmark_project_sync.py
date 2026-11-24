from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from server.modules import project_container


SIZES = (100, 1_000, 5_000)
ITERATIONS = 16


def tree(root: Path, count: int) -> None:
    (root / "media" / "takes").mkdir(parents=True)
    (root / "project.json").write_text('{"revision":0}\n', encoding="utf-8")
    for index in range(count):
        (root / "media" / "takes" / f"take-{index}.wav").write_bytes(b"RIFF-fixed-fixture")


def p95(values: list[float]) -> float:
    return sorted(values)[int((len(values) - 1) * 0.95)]


def update_project(root: Path, revision: int) -> None:
    (root / "project.json").write_text(json.dumps({"revision": revision}) + "\n", encoding="utf-8")


def run(count: int) -> tuple[float, float]:
    with tempfile.TemporaryDirectory(prefix="scena-sync-benchmark-") as raw:
        base = Path(raw)
        full_root, fast_root = base / "full", base / "fast"
        full_root.mkdir()
        fast_root.mkdir()
        tree(full_root, count)
        tree(fast_root, count)
        full_container, fast_container = base / "full.scena", base / "fast.scena"
        project_container.sync_container(full_container, full_root)
        project_container.sync_container(fast_container, fast_root)
        full_samples: list[float] = []
        fast_samples: list[float] = []
        for revision in range(1, ITERATIONS + 1):
            update_project(full_root, revision)
            update_project(fast_root, revision)
            order = ("fast", "full") if revision % 2 else ("full", "fast")
            for kind in order:
                started = time.perf_counter()
                if kind == "full":
                    project_container.sync_container(full_container, full_root)
                    full_samples.append((time.perf_counter() - started) * 1_000)
                else:
                    project_container.sync_project_entry(fast_container, fast_root)
                    fast_samples.append((time.perf_counter() - started) * 1_000)
        return p95(full_samples), p95(fast_samples)


def main() -> None:
    print("take-files\tfull-sync-p95-ms\tproject-only-p95-ms\timprovement\tfull-scan-files\tfast-target-files")
    for count in SIZES:
        full, fast = run(count)
        print(f"{count}\t{full:.2f}\t{fast:.2f}\t{(1 - fast / full) * 100:.1f}%\t{count + 1}\t1")


if __name__ == "__main__":
    main()
