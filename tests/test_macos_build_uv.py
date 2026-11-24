"""Mac packaging selects a pinned uv without changing the host installation."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "tools/build-tauri-sidecar.sh"
STUB = '''import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps({"role": pathlib.Path(sys.argv[0]).parent.name, "args": args,
                          "virtual_env": os.environ.get("VIRTUAL_ENV")}) + "\\n")
pinned = pathlib.Path(sys.argv[0]).parent.name == "pinned"
if args == ["--version"]:
    print(os.environ["PINNED_VERSION"] if pinned else os.environ["HOST_VERSION"])
elif not pinned:
    if os.environ.get("BOOTSTRAP_EXIT"):
        sys.exit(int(os.environ["BOOTSTRAP_EXIT"]))
    # Like real "uv run --with", the bootstrap runs inside an ephemeral environment.
    env = {**os.environ, "PATH": os.environ["PINNED_DIR"] + os.pathsep + os.environ["PATH"],
           "VIRTUAL_ENV": os.environ["CALL_LOG"] + ".ephemeral"}
    sys.exit(subprocess.run(args[args.index("bash"):], env=env).returncode)
elif "pyinstaller" in args:
    if os.environ.get("BUILD_EXIT"):
        sys.exit(int(os.environ["BUILD_EXIT"]))
    output = pathlib.Path(args[args.index("--distpath") + 1]) / "scena-api/scena-api"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("built by pinned uv")
    output.chmod(0o755)
'''


@unittest.skipUnless(os.name == "posix", "Mac packaging uses a POSIX shell")
class MacBuildUvTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo with spaces"
        (self.root / "tools").mkdir(parents=True)
        self.script = self.root / "tools/build-tauri-sidecar.sh"
        shutil.copyfile(SCRIPT, self.script)
        (self.root / "tools/build-native-extension.sh").write_text("exit 0\n")
        for role in ("host", "pinned"):
            directory = self.root / role
            directory.mkdir()
            uv = directory / "uv"
            uv.write_text(f"#!{sys.executable}\n" + STUB)
            uv.chmod(0o755)
        self.log = self.root / "calls.jsonl"
        self.env = {**os.environ, "PATH": str(self.root / "host") + os.pathsep + os.environ["PATH"],
                    "HOST_VERSION": "uv 0.12.19 (Homebrew)", "PINNED_VERSION": "uv 0.12.5 (official build)",
                    "PINNED_DIR": str(self.root / "pinned"), "CALL_LOG": str(self.log)}
        for key in ("SCENA_PINNED_BUILD_UV", "BOOTSTRAP_EXIT", "BUILD_EXIT"):
            self.env.pop(key, None)

    def run_build(self):
        return subprocess.run(["bash", str(self.script), "--"], env=self.env,
                              capture_output=True, text=True, timeout=10, check=False)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_different_host_version_bootstraps_and_bundles_pinned_uv(self):
        original = (self.root / "host/uv").read_bytes()
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        bootstrap = self.calls()[1]
        self.assertEqual(bootstrap["args"], ["run", "--no-project", "--python", "3.13.12",
                                            "--with", "uv==0.12.5", "bash", str(self.script), "--"])
        self.assertTrue(all(call["role"] == "pinned" for call in self.calls()[2:]))
        bundled = self.root / "src-tauri/resources/environment-manager/uv"
        self.assertEqual(bundled.read_bytes(), (self.root / "pinned/uv").read_bytes())
        self.assertEqual((self.root / "host/uv").read_bytes(), original)

    def test_pinned_builds_do_not_inherit_the_bootstrap_environment(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        project_runs = [call for call in self.calls() if call["role"] == "pinned" and call["args"][:2] == ["run", "--locked"]]
        self.assertTrue(project_runs)
        self.assertEqual([call["virtual_env"] for call in project_runs], [None] * len(project_runs))

    def test_exact_host_version_does_not_bootstrap(self):
        self.env["HOST_VERSION"] = "uv 0.12.5 (official build)"
        # Same pinned behavior for packaging, while recording the host invocation.
        host = self.root / "host/uv"
        host.write_text(f"#!{sys.executable}\n" + STUB.replace('elif not pinned:', 'elif not pinned and "--with" in args:'))
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("--with" in call["args"] for call in self.calls()))
        self.assertEqual((self.root / "src-tauri/resources/environment-manager/uv").read_bytes(), host.read_bytes())

    def test_similar_version_does_not_satisfy_exact_pin(self):
        self.env["HOST_VERSION"] = "uv 0.12.50"
        self.assertEqual(self.run_build().returncode, 0)
        self.assertIn("--with", self.calls()[1]["args"])

    def test_bootstrap_failure_stops_before_build_or_bundle_copy(self):
        self.env["BOOTSTRAP_EXIT"] = "23"
        self.assertEqual(self.run_build().returncode, 23)
        self.assertEqual(len(self.calls()), 2)
        self.assertFalse((self.root / "src-tauri").exists())

    def test_failed_activation_does_not_recurse_or_build(self):
        self.env["PINNED_VERSION"] = "uv 0.12.19"
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unable to activate required uv 0.12.5", result.stderr)
        self.assertEqual(len(self.calls()), 3)
        self.assertFalse((self.root / "src-tauri").exists())

    def test_packaging_failure_is_preserved_and_uv_is_not_published(self):
        self.env["BUILD_EXIT"] = "17"
        self.assertEqual(self.run_build().returncode, 17)
        self.assertFalse((self.root / "src-tauri/resources/environment-manager/uv").exists())
