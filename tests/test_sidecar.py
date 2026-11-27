import scena_test_isolation
import unittest
from unittest.mock import patch

from server import sidecar


class SidecarTests(unittest.TestCase):
    def test_parent_exit_during_bundled_startup_is_quiet(self):
        environment = {"SCENA_CONTROL_ADDRESS": "127.0.0.1:1", "SCENA_DATA_ROOT": scena_test_isolation.DATA_ROOT}
        with patch("sys.argv", ["scena-api"]), patch.dict("os.environ", environment, clear=True), patch(
            "server.desktop_control.run_desktop", side_effect=ConnectionRefusedError(10061, "parent exited")
        ):
            sidecar.main()


if __name__ == "__main__":
    unittest.main()
