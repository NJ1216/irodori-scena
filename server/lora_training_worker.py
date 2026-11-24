"""Owned offline process: encode frozen PCM input, then execute pinned trainer."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

from lora_training_compat import compatible_trainer


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def publish(**value):
    print("SCENA_PROGRESS " + json.dumps(value), flush=True)


def watch_owner(pid: int):
    while True:
        time.sleep(1)
        if os.getppid() != pid:
            os._exit(130)


def encode_cpu_pcm(codec, audio, sample_rate: int):
    import torch
    # Upstream codec resamples and normalizes on the input device, then moves
    # the processed waveform to its own MPS device. audiotools uses FP64 meters.
    tensor = torch.from_numpy(audio.mean(axis=1)).reshape(1, -1)
    with torch.inference_mode():
        return codec.encode_waveform(tensor, sample_rate=sample_rate)[0].cpu()


def prepare_latents(directory: Path, request: dict):
    import gc
    import soundfile as sf
    import torch
    from irodori_tts.codec import DACVAECodec
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is unavailable; CPU fallback is not supported")
    codec = DACVAECodec.load(repo_id=request["runtime"]["codec"], device="mps", dtype=torch.float32)
    manifest = []
    for index, row in enumerate(request["rows"]):
        wav = directory / row["wav"]
        if file_hash(wav) != row["wavHash"]:
            raise ValueError("Frozen training WAV changed")
        audio, rate = sf.read(str(wav), dtype="float32", always_2d=True)
        latent = encode_cpu_pcm(codec, audio, rate)
        path = directory / f"latent-{index}.pt"
        torch.save(latent, path)
        manifest.append({"latent_path": path.name, "num_frames": latent.shape[0],
                         "text": row["text"], "caption": row["caption"], "speaker_id": row["speaker_id"]})
        publish(stage="preparing", prepared=index + 1, inputCount=len(request["rows"]))
    (directory / "manifest.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest))
    del codec
    gc.collect()
    torch.mps.empty_cache()


def configure(directory: Path, request: dict):
    import yaml
    from safetensors import safe_open
    runtime, settings = request["runtime"], request["settings"]
    config = yaml.safe_load((Path(runtime["enginePath"]) / "configs/train_v4_small_lora.yaml").read_text())
    with safe_open(runtime["checkpoint"], framework="pt") as checkpoint:
        architecture = json.loads(checkpoint.metadata()["config_json"])
    ignored = {"max_text_len", "max_caption_len", "fixed_target_latent_steps", "ref_max_seconds"}
    config["model"].update({key: value for key, value in architecture.items() if key not in ignored})
    if request.get("sourceAdapter"):
        adapter = json.loads((directory / "source-adapter/adapter_config.json").read_text())
        config["train"].update(lora_r=adapter["r"], lora_alpha=adapter["lora_alpha"],
                               lora_dropout=adapter.get("lora_dropout", 0),
                               lora_target_modules=adapter["target_modules"],
                               lora_modules_to_save=adapter["modules_to_save"])
    steps = settings["maxSteps"]
    config["train"].update(precision="fp32", batch_size=settings["batchSize"], gradient_accumulation_steps=1,
        num_workers=0, compile_model=False, max_steps=steps, warmup_steps=0, stable_steps=steps,
        lr_scheduler="none", learning_rate=settings["learningRate"], log_every=1, save_every=steps,
        valid_every=steps, valid_ratio=0.34 if len(request["rows"]) >= 3 else 0,
        ref_min_seconds=1.0, ref_max_seconds=settings["maxSeconds"],
        max_latent_steps=max(json.loads(line)["num_frames"] for line in (directory / "manifest.jsonl").read_text().splitlines()), dataloader_cuda_prefetch=False,
        allow_tf32=False, wandb_enabled=False, seed=17)
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    return path


def continuation_path(directory: Path, request: dict) -> str | None:
    adapter = request.get("sourceAdapter")
    if not adapter:
        return None
    path = directory / "source-adapter"
    for name, key in (("adapter_config.json", "configHash"), ("adapter_model.safetensors", "weightsHash")):
        candidate = path / name
        if candidate.is_symlink() or file_hash(candidate) != adapter[key]:
            raise ValueError("Frozen source adapter changed")
    return str(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--owner-pid", required=True, type=int)
    args = parser.parse_args()
    threading.Thread(target=watch_owner, args=(args.owner_pid,), daemon=True).start()
    directory = Path(args.job_dir)
    request = json.loads((directory / "request.json").read_text())
    runtime = request["runtime"]
    sys.path.insert(0, runtime["enginePath"])
    if file_hash(Path(runtime["checkpoint"])) != runtime["baseModelHash"]:
        raise ValueError("Base checkpoint changed")
    trainer_path = Path(runtime["enginePath"]) / "train.py"
    adapter_path = continuation_path(directory, request)
    source = compatible_trainer(trainer_path.read_bytes(), adapter_path)
    publish(stage="preparing", prepared=0, inputCount=len(request["rows"]))
    prepare_latents(directory, request)
    config = configure(directory, request)
    sys.argv = [str(trainer_path), "--config", str(config), "--manifest", str(directory / "manifest.jsonl"),
                "--output-dir", str(directory / "training"), "--device", "mps",
                "--init-checkpoint", runtime["checkpoint"], "--no-progress"]
    exec(compile(source, str(trainer_path), "exec"), {"__name__": "__main__", "__file__": str(trainer_path)})


if __name__ == "__main__":
    main()
