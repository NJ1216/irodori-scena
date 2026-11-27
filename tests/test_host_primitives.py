"""Small host checks runnable without the API environment or an inference model."""
import scena_test_isolation  # noqa: F401
import os
import subprocess
import sys
import tempfile
import unittest

from server.file_lock import lock_exclusive, unlock


class HostPrimitiveTests(unittest.TestCase):
    def test_synthesis_lock_rejects_another_process_and_releases(self):
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            name = temporary.name
        try:
            with open(name, "a+") as owner:
                lock_exclusive(owner)
                code = ("from server.file_lock import lock_exclusive; import sys; "
                        "f=open(sys.argv[1], 'a+'); lock_exclusive(f)")
                held = subprocess.run([sys.executable, "-c", code, name], capture_output=True)
                self.assertNotEqual(held.returncode, 0)
                self.assertIn(b"BlockingIOError", held.stderr)
                unlock(owner)
                released = subprocess.run([sys.executable, "-c", code, name], capture_output=True)
                self.assertEqual(released.returncode, 0, released.stderr.decode())
        finally:
            os.unlink(name)

    @unittest.skipUnless(os.name == "nt", "Windows anonymous pipe API")
    def test_windows_pipe_timeout_data_and_eof(self):
        from server.windows_pipe import WindowsPipe
        read_fd, write_fd = os.pipe()
        try:
            reader = WindowsPipe(read_fd)
            self.assertIsNone(reader.read(0))
            os.write(write_fd, "台詞\n".encode())
            self.assertEqual(reader.read(0.1), "台詞\n".encode())
            self.assertIsNone(reader.read(0))
            os.close(write_fd)
            write_fd = None
            self.assertEqual(reader.read(0.1), b"")
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    @unittest.skipUnless(os.name == "nt", "Windows anonymous pipe API")
    def test_windows_timed_out_reader_cannot_consume_next_response(self):
        from server.windows_pipe import WindowsPipe
        read_fd, write_fd = os.pipe()
        try:
            self.assertIsNone(WindowsPipe(read_fd).read(0))
            os.write(write_fd, b"next\n")
            self.assertEqual(WindowsPipe(read_fd).read(0.1), b"next\n")
        finally:
            os.close(read_fd)
            os.close(write_fd)
