"""Download size for one usable model, rather than all repository variants."""
import sys

from server.modules.huggingface_gguf import variants_from_info


def size_format():
    return "gguf-v3" if sys.platform == "win32" else "mlx-v1"


def model_download_size(info):
    files = getattr(info, "siblings", None) or []
    if sys.platform == "win32":
        known = {item.rfilename for item in files if isinstance(item.size, int) and item.size > 0}
        variants = variants_from_info("", info)["variants"]
        sizes = [item["downloadSizeBytes"] for item in variants if set(item["files"]) <= known]
        return min(sizes) if sizes else None
    selected = [item for item in files if item.rfilename and not item.rfilename.startswith((".git/", "onnx/"))]
    if not selected or any(not isinstance(item.size, int) or item.size < 0 for item in selected):
        return None
    return sum(item.size for item in selected) or None
