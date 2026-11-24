"""Single-owner anonymous pipe polling, without a surviving reader thread."""
import ctypes
import os
import time
from ctypes import wintypes


class WindowsPipe:
    def __init__(self, fd):
        import msvcrt
        self.fd = fd
        self.handle = msvcrt.get_osfhandle(fd)
        msvcrt.setmode(fd, os.O_BINARY)
        self.peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
        self.peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                              ctypes.POINTER(wintypes.DWORD)]
        self.peek.restype = wintypes.BOOL

    def read(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            available = wintypes.DWORD()
            if not self.peek(self.handle, None, 0, None, ctypes.byref(available), None):
                error = ctypes.get_last_error()
                if error == 109:  # ERROR_BROKEN_PIPE: writer has closed.
                    return b""
                raise ctypes.WinError(error)
            if available.value:
                return os.read(self.fd, min(65536, available.value))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(0.01, remaining))
