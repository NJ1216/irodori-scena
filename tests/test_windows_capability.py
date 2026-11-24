import unittest
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import local_llm_runtime


class WindowsCapabilityTests(unittest.TestCase):
    def test_local_endpoint_override_is_supported_on_windows(self):
        with patch("server.platform_support.sys.platform", "win32"), patch.dict(
            "os.environ", {"SCENA_LOCAL_LLM_ENDPOINT": "http://127.0.0.1:1234"}
        ), patch.object(local_llm_runtime, "_runtime_health", return_value=True) as health:
            status = local_llm_runtime.start_local_llm()
            self.assertIn("running", status)
            health.assert_called_once()

    def test_windows_capability_selects_llama_cpp(self):
        with patch.object(local_llm_runtime.platform, "system", return_value="Windows"), patch(
            "server.modules.llama_cpp_runtime.nvidia_available", return_value=False
        ):
            capability = local_llm_runtime.local_llm_capabilities()
        self.assertEqual((capability["engine"], capability["backend"]), ("llama.cpp", "cpu"))
