"""Host device selection without changing synthesis precision or sampling inputs."""
import os
import sys
from pathlib import Path


def inference_device(torch):
    if sys.platform == "darwin":
        return "mps"
    if not torch.cuda.is_available():
        return "cpu"
    # cu128 PyTorch ships no Maxwell or Pascal kernels; such GPUs run on CPU.
    major, minor = torch.cuda.get_device_capability(0)
    return "cuda" if major * 10 + minor >= 70 else "cpu"


def configure_cpu_threads(torch, device, environ=os.environ):
    """Run CPU inference on the physical cores; the default of one thread per logical core is slower."""
    if device != "cpu":
        return None
    try:
        threads = int(environ.get("IRODORI_TTS_CPU_THREADS", ""))
    except ValueError:
        return None
    if threads <= 0 or threads >= torch.get_num_threads():
        return None
    torch.set_num_threads(threads)
    return threads


def configure_audio_libraries():
    """Keep the DLL directory handle alive for this worker's entire lifetime."""
    if sys.platform != "win32":
        return []
    candidates = [os.environ.get("SCENA_FFMPEG_DIR", ""), *os.environ.get("PATH", "").split(os.pathsep)]
    for value in candidates:
        directory = Path(value)
        if not value or not directory.is_absolute() or not directory.is_dir():
            continue
        if all(any(directory.glob(f"{library}-*.dll")) for library in ("avcodec", "avformat", "avutil")):
            return [os.add_dll_directory(str(directory))]
    return []
