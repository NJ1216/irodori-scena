from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO

from tools.screen_torch_compile_mps import (
    _clone,
    _dynamo_counts,
    main,
    parse_shapes,
    parser,
    run_child,
    screening_passed,
)


class TorchCompileScreeningTests(unittest.TestCase):
    def test_shapes_are_strictly_positive(self) -> None:
        self.assertEqual(parse_shapes(["1x128x64", "2x32"]), [(1, 128, 64), (2, 32)])
        for invalid in ("", "1x0", "1xno"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_shapes([invalid])

    def test_cli_requires_known_and_unknown_shapes(self) -> None:
        common = [
            "--output",
            "out.json",
            "--max-compile-seconds",
            "1",
            "--max-recompiles",
            "0",
            "--max-unique-graphs",
            "1",
        ]
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser().parse_args([*common, "--known-shape", "1x2"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser().parse_args([*common, "--unknown-shape", "1x3"])

    def test_input_trees_are_recursively_cloned(self) -> None:
        class Tensor:
            def detach(self):
                return self

            def clone(self):
                return Tensor()

        class Torch:
            pass

        Torch.Tensor = Tensor
        original = Tensor()
        cloned = _clone(Torch, ({"tensor": original}, [original]))
        self.assertIsNot(cloned[0]["tensor"], original)
        self.assertIsNot(cloned[1][0], original)

    def test_known_and_unknown_shape_sets_must_be_disjoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be disjoint"):
            main(
                [
                    "--known-shape",
                    "1x2",
                    "--unknown-shape",
                    "1x2",
                    "--output",
                    "unused.json",
                    "--max-compile-seconds",
                    "1",
                    "--max-recompiles",
                    "0",
                    "--max-unique-graphs",
                    "1",
                ]
            )

    def test_missing_recompile_counter_is_never_inferred(self) -> None:
        class Dynamo:
            class utils:
                counters = {"stats": {"unique_graphs": 3}}

        class Torch:
            _dynamo = Dynamo()

        self.assertEqual(_dynamo_counts(Torch), (3, None))

    def test_child_captures_crash_timeout_and_json(self) -> None:
        complete = run_child([sys.executable, "-c", 'print("{\\"ok\\":true}")'], 2)
        self.assertEqual(complete["result"], {"ok": True})
        crashed = run_child([sys.executable, "-c", "raise SystemExit(7)"], 2)
        self.assertEqual((crashed["status"], crashed["exitCode"]), ("crashed", 7))
        timeout = run_child([sys.executable, "-c", "import time; time.sleep(2)"], 0.01)
        self.assertEqual(timeout["status"], "timeout")

    def test_gate_requires_mps_exact_shapes_and_compile_counters(self) -> None:
        rows = [{"eagerSeconds": 0.1, "compiledSeconds": 0.2}]
        result = {
            "status": "completed",
            "limits": {"maxCompileSeconds": 2.0, "maxUniqueGraphs": 2, "maxRecompiles": 1},
            "result": {
                "device": "mps",
                "allExact": True,
                "knownShapesCompleted": True,
                "unknownShapesCompleted": True,
                "compileSeconds": 1.0,
                "uniqueGraphs": 1,
                "recompiles": 0,
                "rows": rows,
            },
        }
        self.assertTrue(screening_passed(result))
        for field in ("allExact", "knownShapesCompleted", "unknownShapesCompleted"):
            rejected = {"status": "completed", "result": dict(result["result"], **{field: False})}
            rejected["limits"] = result["limits"]
            self.assertFalse(screening_passed(rejected))
        unavailable = {**result, "result": {**result["result"], "uniqueGraphs": None}}
        self.assertFalse(screening_passed(unavailable))
        too_slow = {**result, "result": {**result["result"], "compileSeconds": 3.0}}
        self.assertFalse(screening_passed(too_slow))
        self.assertFalse(screening_passed({"status": "timeout"}))


if __name__ == "__main__":
    unittest.main()
