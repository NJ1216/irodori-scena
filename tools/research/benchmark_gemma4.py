#!/usr/bin/env python3
"""Fair 8K/16K Gemma 4 comparison; prompts and outputs are never persisted."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

TARGET_REPO = "mlx-community/gemma-4-31b-it-nvfp4"
TARGET_REVISION = "a0a935b105621b98907915fa12f05348bb9c3c24"
DFLASH_REPO = "z-lab/gemma-4-31B-it-DFlash"
DFLASH_REVISION = "eabd648301ce28583cc14757912e5e0f84e152e1"
MTP_REPO = "google/gemma-4-31B-it-assistant"
MTP_REVISION = "627c5ec1458b9086b841a91e0512fd31fd2fbbf1"
DEFAULT_CONTEXTS = (8192, 16384)
PROVIDERS = ("omlx", "omlx-dflash", "omlx-mtp", "ollama")


@dataclass
class Measurement:
    provider: str
    context_tokens: int
    iteration: int
    warmup: bool
    success: bool
    error: str | None
    fallback: bool
    started_at: str
    run_ordinal: int
    ttft_seconds: float | None
    total_seconds: float
    prompt_tokens: int | None
    cached_prompt_tokens: int | None
    completion_tokens: int | None
    prompt_tps: float | None
    generation_tps: float | None
    output_sha256: str | None
    nonempty: bool
    thermal_before: str | None
    thermal_after: str | None
    low_power_mode: bool | None
    line_count: int
    protocol_valid: bool


def fixed_prompt(token_target: int, variant: int, suite_id: str = "default",
                 tokenizer: Any | None = None) -> str:
    """Return equal-length Japanese script fixtures without a shared leading prefix."""
    nonce = hashlib.sha256(f"{suite_id}:{token_target}:{variant}".encode()).hexdigest()[:16]
    header = (f"測定識別子{nonce}。以下の資料を基に、日本語音声ドラマの台詞だけを80行書いてください。"
              "形式は一行ごとに A|台詞 または B|台詞。説明・JSON・Markdownは禁止。\n資料:\n")
    unit = "夕暮れの駅で二人は再会し、昔の約束と明日の選択について静かに話し合った。"
    body = header + unit * token_target
    if tokenizer is None:
        return body[:token_target * 3 // 2]
    # The bundled Gemma 4 chat template adds 13 tokens around a user message.
    prompt_ids = tokenizer.encode(body, add_special_tokens=False)[:token_target - 13]
    prompt = tokenizer.decode(prompt_ids, skip_special_tokens=True)
    if len(tokenizer.encode(prompt, add_special_tokens=False)) != token_target - 13:
        raise RuntimeError("tokenizer round-trip changed the fixed prompt length")
    return prompt


def _headers(api_key: str, accept: str | None = None) -> dict[str, str]:
    result = {"Content-Type": "application/json"}
    if accept:
        result["Accept"] = accept
    if api_key:
        result["Authorization"] = f"Bearer {api_key}"
    return result


def _openai_stream(base_url: str, model: str, prompt: str, api_key: str, max_tokens: int,
                   timeout: int) -> tuple[str, dict[str, Any], float, float]:
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0, "seed": 42, "max_tokens": max_tokens, "think": False, "stream": True,
                       "stream_options": {"include_usage": True}}).encode()
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body,
                                     headers=_headers(api_key, "text/event-stream"))
    started, first = time.perf_counter(), None
    chunks: list[str] = []
    usage: dict[str, Any] = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if line == "data: [DONE]":
                break
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:].strip())
            usage.update(payload.get("usage") or {})
            content = (payload.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
            if content:
                first = first or time.perf_counter()
                chunks.append(content)
    ended = time.perf_counter()
    return "".join(chunks), usage, (first - started if first else ended - started), ended - started


def _ollama_stream(base_url: str, model: str, prompt: str, max_tokens: int,
                   timeout: int) -> tuple[str, dict[str, Any], float, float]:
    root = base_url.rstrip("/").removesuffix("/v1")
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "think": False, "stream": True,
                       "options": {"temperature": 0, "seed": 42, "num_predict": max_tokens}}).encode()
    request = urllib.request.Request(root + "/api/chat", data=body, headers=_headers(""))
    started, first = time.perf_counter(), None
    chunks: list[str] = []
    usage: dict[str, Any] = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            payload = json.loads(raw)
            content = (payload.get("message") or {}).get("content") or ""
            if content:
                first = first or time.perf_counter()
                chunks.append(content)
            if payload.get("done"):
                usage = {"prompt_tokens": payload.get("prompt_eval_count"),
                         "completion_tokens": payload.get("eval_count"),
                         "prompt_eval_duration": payload.get("prompt_eval_duration"),
                         "eval_duration": payload.get("eval_duration")}
    ended = time.perf_counter()
    return "".join(chunks), usage, (first - started if first else ended - started), ended - started


def _thermal(probe: Path | None) -> dict[str, Any]:
    if probe is None:
        return {}
    try:
        return json.loads(subprocess.check_output([str(probe)], text=True, timeout=5))
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return {}


def _build_thermal_probe(output: Path) -> Path | None:
    if platform.system() != "Darwin":
        return None
    probe = output / "thermal-state"
    cache = output / "swift-module-cache"
    cache.mkdir(exist_ok=True)
    env = {**os.environ, "CLANG_MODULE_CACHE_PATH": str(cache), "SWIFT_MODULECACHE_PATH": str(cache)}
    try:
        subprocess.run(["swiftc", "tools/macos-thermal-state.swift", "-o", str(probe)], check=True,
                       capture_output=True, text=True, timeout=60, env=env)
        return probe
    except (OSError, subprocess.SubprocessError):
        return None


def _cached_tokens(usage: dict[str, Any]) -> int | None:
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    value = details.get("cached_tokens") if isinstance(details, dict) else None
    return value if isinstance(value, int) else None


def _script_protocol(text: str) -> tuple[int, bool]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines), bool(lines) and all(line.startswith(("A|", "B|")) for line in lines)


def measure(provider: str, args: argparse.Namespace, context: int, iteration: int,
            warmup: bool, run_ordinal: int, probe: Path | None) -> Measurement:
    before = _thermal(probe)
    started_at = datetime.now(UTC).isoformat()
    try:
        # Providers receive token-equivalent fixtures with distinct nonces so
        # one oMLX mode cannot inherit another mode's persistent prefix cache.
        prompt = fixed_prompt(context, iteration, f"{args.prompt_suite_id}:{provider}", args.tokenizer)
        if provider == "ollama":
            output, usage, ttft, total = _ollama_stream(args.ollama_url, args.ollama_model, prompt,
                                                        args.max_output_tokens, args.timeout)
        else:
            output, usage, ttft, total = _openai_stream(args.omlx_url, args.omlx_model, prompt, args.omlx_key,
                                                        args.max_output_tokens, args.timeout)
        prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        prompt_duration, eval_duration = usage.get("prompt_eval_duration"), usage.get("eval_duration")
        if provider == "ollama":
            prompt_tps = prompt_tokens / (prompt_duration / 1e9) if isinstance(prompt_tokens, int) and prompt_duration else None
            generation_tps = completion_tokens / (eval_duration / 1e9) if isinstance(completion_tokens, int) and eval_duration else None
        else:
            prompt_tps = usage.get("prompt_tokens_per_second")
            generation_tps = usage.get("generation_tokens_per_second")
            if not isinstance(generation_tps, (int, float)) and isinstance(completion_tokens, int):
                generation_tps = completion_tokens / max(total - ttft, 1e-9)
        after = _thermal(probe)
        line_count, protocol_valid = _script_protocol(output)
        return Measurement(provider, context, iteration, warmup, bool(output.strip()), None, False, started_at,
                           run_ordinal, ttft, total, prompt_tokens, _cached_tokens(usage), completion_tokens,
                           prompt_tps, generation_tps, hashlib.sha256(output.encode()).hexdigest() if output else None,
                           bool(output.strip()), before.get("state"), after.get("state"), after.get("lowPowerMode"),
                           line_count, protocol_valid)
    except Exception as error:
        after = _thermal(probe)
        return Measurement(provider, context, iteration, warmup, False, f"{type(error).__name__}: {error}"[:500],
                           False, started_at, run_ordinal, None, 0, None, None, None, None, None, None, False,
                           before.get("state"), after.get("state"), after.get("lowPowerMode"), 0, False)


def _private_request(args: argparse.Namespace, path: str, body: dict[str, Any] | None = None,
                     method: str | None = None) -> dict[str, Any]:
    root = args.omlx_url.rstrip("/").removesuffix("/v1")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(root + path, data=data, headers=_headers(args.omlx_key),
                                     method=method or ("PUT" if body is not None else "GET"))
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def unload_omlx(args: argparse.Namespace) -> None:
    encoded = urllib.parse.quote(args.omlx_model, safe="")
    try:
        _private_request(args, f"/v1/models/{encoded}/unload", {}, "POST")
    except HTTPError as error:
        if error.code not in (400, 404):
            raise


def unload_ollama(args: argparse.Namespace) -> None:
    root = args.ollama_url.rstrip("/").removesuffix("/v1")
    with urllib.request.urlopen(root + "/api/ps", timeout=10) as response:
        running = json.loads(response.read().decode()).get("models") or []
    if not any(args.ollama_model in (item.get("name"), item.get("model")) for item in running):
        return
    body = json.dumps({"model": args.ollama_model, "keep_alive": 0}).encode()
    request = urllib.request.Request(root + "/api/generate", data=body, headers=_headers(""))
    with urllib.request.urlopen(request, timeout=120) as response:
        response.read()


def prepare_provider(provider: str, args: argparse.Namespace) -> None:
    """Start each runtime mode without another 31B engine resident in memory."""
    unload_omlx(args)
    unload_ollama(args)
    if provider != "ollama":
        configure_omlx(provider, args)


def configure_omlx(provider: str, args: argparse.Namespace) -> None:
    encoded = urllib.parse.quote(args.omlx_model, safe="")
    _private_request(args, f"/api/scena/models/{encoded}/settings", {
        "max_context_window": max(args.contexts), "ttl_seconds": 3600, "enable_thinking": False,
        "trust_remote_code": False, "dflash_enabled": provider == "omlx-dflash",
        "dflash_draft_model": args.dflash_draft if provider == "omlx-dflash" else None,
        "mtp_enabled": False, "vlm_mtp_enabled": provider == "omlx-mtp",
        "vlm_mtp_draft_model": args.mtp_draft if provider == "omlx-mtp" else None,
    })


def verify_engine(provider: str, args: argparse.Namespace) -> bool:
    if provider == "ollama":
        return True
    encoded = urllib.parse.quote(args.omlx_model, safe="")
    status = _private_request(args, f"/api/scena/models/{encoded}/engine")
    if provider == "omlx-dflash":
        return status.get("engine") == "DFlashEngine" and status.get("draftModel") == args.dflash_draft
    if provider == "omlx-mtp":
        return status.get("mtpActive") is True and status.get("mtpDraftModel") == args.mtp_draft
    return not status.get("dflashEnabled") and not status.get("vlmMtpEnabled")


def percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction + .999) - 1))] if ordered else None


def summarize(rows: list[Measurement]) -> list[dict[str, Any]]:
    result = []
    for provider in sorted({row.provider for row in rows}):
        for context in sorted({row.context_tokens for row in rows}):
            group = [row for row in rows if row.provider == provider and row.context_tokens == context and not row.warmup]
            good = [row for row in group if row.success and not row.fallback]
            tps = [row.generation_tps for row in good if row.generation_tps is not None]
            drift = tps[-1] / tps[0] if len(tps) >= 2 and tps[0] else None
            result.append({"provider": provider, "contextTokens": context, "runs": len(group),
                           "successes": len(good), "failures": len(group) - len(good),
                           "medianTotalSeconds": statistics.median([row.total_seconds for row in good]) if good else None,
                           "p95TotalSeconds": percentile((row.total_seconds for row in good), .95),
                           "medianGenerationTps": statistics.median(tps) if tps else None,
                           "lastToFirstGenerationTpsRatio": drift,
                           "thermalPressureSeen": sorted({state for row in group for state in
                                                          (row.thermal_before, row.thermal_after) if state})})
    return result


def _version(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _sysctl(name: str) -> str | None:
    return _version(["sysctl", "-n", name]) if platform.system() == "Darwin" else None


def _model_metadata(model_dir: Path) -> dict[str, Any]:
    config_path = model_dir / "config.json"
    try:
        raw = config_path.read_bytes()
        config = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    quantization = config.get("quantization") or config.get("quantization_config")
    return {"modelType": config.get("model_type"), "quantization": quantization,
            "configSha256": hashlib.sha256(raw).hexdigest()}


def manifest(args: argparse.Namespace) -> dict[str, Any]:
    target_dir = Path("scena-data/local-llm/models") / args.omlx_model
    return {"createdAt": datetime.now(UTC).isoformat(),
            "hardware": {"architecture": platform.machine(), "chip": _sysctl("machdep.cpu.brand_string"),
                         "unifiedMemoryBytes": _sysctl("hw.memsize")}, "macOS": platform.mac_ver()[0],
            "target": {"repo": TARGET_REPO, "revision": TARGET_REVISION, **_model_metadata(target_dir)},
            "dflash": {"repo": DFLASH_REPO, "revision": DFLASH_REVISION},
            "mtp": {"repo": MTP_REPO, "revision": MTP_REVISION},
            "versions": {"python": platform.python_version(), "ollama": _version(["ollama", "--version"]),
                         "omlx": _version([str(Path(".venv/bin/python")), "-c", "import importlib.metadata;print(importlib.metadata.version('omlx'))"]),
                         "mlx": _version([str(Path(".venv/bin/python")), "-c", "import importlib.metadata;print(importlib.metadata.version('mlx'))"])},
            "conditions": {"temperature": 0, "seed": 42, "maxOutputTokens": args.max_output_tokens,
                           "contexts": args.contexts, "repetitions": args.repetitions,
                           "cooldownSeconds": args.cooldown_seconds, "uniquePromptPerIteration": True,
                           "promptSuiteId": args.prompt_suite_id}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", nargs="+", choices=PROVIDERS, default=list(PROVIDERS))
    parser.add_argument("--contexts", nargs="+", type=int, choices=DEFAULT_CONTEXTS, default=list(DEFAULT_CONTEXTS))
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--cooldown-seconds", type=float, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--omlx-url", default="http://127.0.0.1:8791/v1")
    parser.add_argument("--omlx-model", default="mlx-community--gemma-4-31b-it-nvfp4")
    parser.add_argument("--omlx-key", default="")
    parser.add_argument("--omlx-settings", type=Path,
                        help="Read the local benchmark API key from an oMLX settings.json without logging it")
    parser.add_argument("--dflash-draft", default="")
    parser.add_argument("--mtp-draft", default="")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--ollama-model", default="gemma4:31b-mlx")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--prompt-suite-id", default="")
    args = parser.parse_args()
    args.prompt_suite_id = args.prompt_suite_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    if args.omlx_settings:
        settings = json.loads(args.omlx_settings.read_text(encoding="utf-8"))
        args.omlx_key = str((settings.get("auth") or {}).get("api_key") or "")
    from transformers import AutoTokenizer
    args.tokenizer = AutoTokenizer.from_pretrained(
        Path("scena-data/local-llm/models") / args.omlx_model, local_files_only=True
    )
    output = args.output or Path("artifacts/llm-benchmarks") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=False)
    (output / "environment.json").write_text(json.dumps(manifest(args), ensure_ascii=False, indent=2) + "\n")
    probe = _build_thermal_probe(output)
    rows: list[Measurement] = []
    ordinal = 0
    with (output / "measurements.jsonl").open("w", encoding="utf-8") as raw:
        for provider_index, provider in enumerate(args.providers):
            prepare_provider(provider, args)
            if provider_index and args.cooldown_seconds:
                time.sleep(args.cooldown_seconds)
            for context in args.contexts:
                for iteration in range(args.repetitions + 1):
                    ordinal += 1
                    row = measure(provider, args, context, iteration, iteration == 0, ordinal, probe)
                    if iteration == 0 and row.success and not verify_engine(provider, args):
                        row.success, row.fallback, row.error = False, True, "speculative engine fallback detected"
                    rows.append(row)
                    raw.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
                    raw.flush()
                    if iteration and args.cooldown_seconds:
                        time.sleep(args.cooldown_seconds)
        unload_omlx(args)
        unload_ollama(args)
    (output / "summary.json").write_text(json.dumps(summarize(rows), ensure_ascii=False, indent=2) + "\n")
    print(output)
    return 0 if all(row.success and not row.fallback for row in rows if not row.warmup) else 1


if __name__ == "__main__":
    raise SystemExit(main())
