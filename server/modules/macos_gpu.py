"""Lightweight Apple GPU utilization through IOKit and CoreFoundation."""
from __future__ import annotations

import ctypes
import ctypes.util
from functools import cache


K_CF_STRING_ENCODING_UTF8 = 0x08000100
K_CF_NUMBER_DOUBLE_TYPE = 13


@cache
def _framework(name: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name)
    if not path:
        raise OSError(f"{name} framework is unavailable")
    return ctypes.CDLL(path)


def gpu_utilization() -> float | None:
    iokit = _framework("IOKit")
    core = _framework("CoreFoundation")
    iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]
    iokit.IOServiceMatching.restype = ctypes.c_void_p
    iokit.IOServiceGetMatchingServices.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    iokit.IOServiceGetMatchingServices.restype = ctypes.c_int
    iokit.IOIteratorNext.argtypes = [ctypes.c_uint]
    iokit.IOIteratorNext.restype = ctypes.c_uint
    iokit.IOObjectRelease.argtypes = [ctypes.c_uint]
    iokit.IOObjectRelease.restype = ctypes.c_int
    iokit.IORegistryEntryCreateCFProperty.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    iokit.IORegistryEntryCreateCFProperty.restype = ctypes.c_void_p
    core.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
    core.CFStringCreateWithCString.restype = ctypes.c_void_p
    core.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    core.CFDictionaryGetValue.restype = ctypes.c_void_p
    core.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    core.CFNumberGetValue.restype = ctypes.c_bool
    core.CFRelease.argtypes = [ctypes.c_void_p]

    matching = iokit.IOServiceMatching(b"AGXAccelerator")
    iterator = ctypes.c_uint()
    if not matching or iokit.IOServiceGetMatchingServices(0, matching, ctypes.byref(iterator)) != 0:
        return None
    statistics_key = core.CFStringCreateWithCString(None, b"PerformanceStatistics", K_CF_STRING_ENCODING_UTF8)
    utilization_key = core.CFStringCreateWithCString(None, b"Device Utilization %", K_CF_STRING_ENCODING_UTF8)
    samples = []
    try:
        while entry := iokit.IOIteratorNext(iterator):
            try:
                statistics = iokit.IORegistryEntryCreateCFProperty(entry, statistics_key, None, 0)
                if not statistics:
                    continue
                try:
                    number = core.CFDictionaryGetValue(statistics, utilization_key)
                    value = ctypes.c_double()
                    if number and core.CFNumberGetValue(number, K_CF_NUMBER_DOUBLE_TYPE, ctypes.byref(value)):
                        samples.append(min(100.0, max(0.0, value.value)))
                finally:
                    core.CFRelease(statistics)
            finally:
                iokit.IOObjectRelease(entry)
    finally:
        iokit.IOObjectRelease(iterator)
        core.CFRelease(statistics_key)
        core.CFRelease(utilization_key)
    return max(samples) if samples else None
