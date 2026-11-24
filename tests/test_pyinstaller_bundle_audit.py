import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "tools" / "audit-pyinstaller-bundle.py"
API_SPEC = Path(__file__).parents[1] / "tools" / "pyinstaller" / "scena-api.spec"
MACOS_BUNDLE_INSPECTION = Path(__file__).parents[1] / "tools" / "inspect-tauri-bundle.sh"
SPEC = importlib.util.spec_from_file_location("pyinstaller_bundle_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PyInstallerBundleAuditTests(unittest.TestCase):
    def test_rejects_unused_python_packages(self) -> None:
        names = ["server.app", "pyarrow.compute", "cv2/cv2.abi3.so", "omlx.server"]
        self.assertEqual(
            ["cv2/cv2.abi3.so", "omlx.server", "pyarrow.compute"],
            MODULE.forbidden_entries(names),
        )

    def test_rejects_development_only_python_packages(self) -> None:
        # numpy and watchfiles stay installed for tests and --reload; hf_xet serves only uploads.
        names = ["server.app", "numpy/_core/_multiarray_umath.so", "watchfiles._rust_notify", "uvicorn.main", "hf_xet/hf_xet.abi3.so"]
        self.assertEqual(
            ["hf_xet/hf_xet.abi3.so", "numpy/_core/_multiarray_umath.so", "watchfiles._rust_notify"],
            MODULE.forbidden_entries(names),
        )

    def test_rejects_gpl_and_ffmpeg_native_libraries(self) -> None:
        names = ["libavcodec.61.dylib", "libavif.16.dylib", "libx264.164.dylib"]
        self.assertEqual(
            ["libavcodec.61.dylib", "libx264.164.dylib"],
            MODULE.forbidden_entries(names),
        )

    def test_requires_sources_launched_by_the_external_tts_environment(self) -> None:
        names = [
            "_internal/server/irodori_worker.py",
            "server/irodori_acceleration_adapter.py",
            "server/irodori_acceleration_sampler.py",
            "server/irodori_mps_adapter.py",
        ]
        self.assertEqual(
            [
                "server/irodori_cuda_calibration.py",
                "server/irodori_cuda_graphs.py",
                "server/irodori_host.py",
                "server/irodori_load_adapter.py",
                "server/irodori_mps_sampler.py",
                "server/irodori_runtime_layout.py",
                "server/lora_training_compat.py",
                "server/lora_training_worker.py",
                "server/mlx_acceleration_adapter.py",
                "server/mlx_decode_compile.py",
                "server/mlx_irodori_worker.py",
                "server/scena_mlx_lora.py",
            ],
            MODULE.missing_external_worker_files(names),
        )

    def test_discovers_transitive_local_worker_imports(self) -> None:
        self.assertEqual(
            {
                "server/irodori_acceleration_adapter.py",
                "server/irodori_acceleration_sampler.py",
                "server/irodori_cuda_calibration.py",
                "server/irodori_cuda_graphs.py",
                "server/irodori_host.py",
                "server/irodori_load_adapter.py",
                "server/irodori_runtime_layout.py",
                "server/irodori_worker.py",
            },
            MODULE.external_worker_source_files(include_macos=False),
        )

    def test_api_bundle_spec_includes_every_external_worker_source(self) -> None:
        spec = API_SPEC.read_text(encoding="utf-8")
        for relative in MODULE.external_worker_source_files():
            with self.subTest(relative=relative):
                parent, name = relative.split("/", 1)
                self.assertIn(f'ROOT / "{parent}" / "{name}"', spec)

    def test_macos_adapter_and_training_helpers_are_transitively_required(self) -> None:
        required = MODULE.external_worker_source_files()
        self.assertTrue({
            "server/scena_mlx_lora.py", "server/lora_training_worker.py", "server/lora_training_compat.py",
        }.issubset(required))
        complete = [f"_internal/{name}" for name in required]
        self.assertEqual(MODULE.missing_external_worker_files(complete), [])
        for helper in ("server/scena_mlx_lora.py", "server/lora_training_compat.py"):
            with self.subTest(helper=helper):
                self.assertEqual(MODULE.missing_external_worker_files([name for name in complete if not name.endswith(helper)]), [helper])

    def test_executed_spec_collects_platform_required_source_data(self) -> None:
        prefix = API_SPEC.read_text(encoding="utf-8").split("a = Analysis(", 1)[0]
        for platform, include_macos in (("darwin", True), ("win32", False)):
            with self.subTest(platform=platform), patch("sys.platform", platform), patch.dict("os.environ", {}, clear=True):
                scope = {"SPECPATH": str(API_SPEC.parent)}
                exec(compile(prefix, str(API_SPEC), "exec"), scope)
                collected = {f"{destination}/{Path(source).name}" for source, destination in scope["datas"]}
                self.assertTrue(MODULE.external_worker_source_files(include_macos=include_macos).issubset(collected))
                if not include_macos:
                    self.assertFalse({"server/scena_mlx_lora.py", "server/lora_training_worker.py", "server/lora_training_compat.py"} & collected)

    def test_api_bundle_spec_includes_windows_llama_cpp_catalogue(self) -> None:
        spec = API_SPEC.read_text(encoding="utf-8")
        self.assertIn('ROOT / "server" / "catalogs" / "llama-cpp-runtime.json"', spec)
        self.assertIn('"server/catalogs"', spec)

    def test_api_bundle_spec_includes_cross_platform_rhubarb_catalogue(self) -> None:
        spec = API_SPEC.read_text(encoding="utf-8")
        entry = 'ROOT / "server" / "catalogs" / "rhubarb-runtime.json"'
        self.assertIn(entry, spec)
        unconditional_data = spec[spec.index("datas = [") : spec.index(entry)]
        self.assertNotIn('if sys.platform == "win32":', unconditional_data)

    def test_macos_release_inspection_requires_rhubarb_catalogue(self) -> None:
        inspection = MACOS_BUNDLE_INSPECTION.read_text(encoding="utf-8")
        self.assertIn("scena-api-runtime/_internal/server/catalogs/rhubarb-runtime.json", inspection)

    def test_macos_release_inspection_requires_mlx_worker(self) -> None:
        inspection = MACOS_BUNDLE_INSPECTION.read_text(encoding="utf-8")
        self.assertIn("scena-api-runtime/_internal/server/mlx_irodori_worker.py", inspection)
