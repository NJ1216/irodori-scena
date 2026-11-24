#!/usr/bin/env python3
"""Offline Japanese CTC experiment; never used by SCENA export."""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from scipy import signal

from evaluate_japanese_lipsync import TICKS, VOWELS, acoustic, acoustic_frames, merge, metrics, read_lab, read_wav
from lipsync_temporal import suppress_short_vowels
from lipsync_review_inputs import review_inputs


def conv_timing(config):
    stride, width = 1, 1
    for kernel, step in zip(config["conv_kernel"], config["conv_stride"]):
        width += (kernel - 1) * stride
        stride *= step
    return stride / 16000, width / 32000


def prepare_input(audio, rate, processor):
    """Preserve the reviewed resampling/normalization order before float32 casting."""
    factor = math.gcd(rate, 16000)
    samples = signal.resample_poly(audio, 16000 // factor, rate // factor)
    if processor["do_normalize"]:
        samples = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
    return samples.astype(np.float32)[None, :]


def recognize(session, audio, rate, vocab, config, processor, *, with_frames=False):
    logits = session.run(None, {"input_values": prepare_input(audio, rate, processor)})[0][0]
    return decode_logits(logits, vocab, config, with_frames=with_frames)


def decode_logits(logits, vocab, config, *, with_frames=False):
    probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    ids = probabilities.argmax(axis=1)
    reverse = {index: label for label, index in vocab.items()}
    step, offset = conv_timing(config)
    events = []
    index = 0
    while index < len(ids):
        end = index + 1
        while end < len(ids) and ids[end] == ids[index]:
            end += 1
        phone = reverse[int(ids[index])]
        if phone not in ("PAD", "SOS", "EOS", "UNK", "sil", "pau"):
            events.append({"time": index * step + offset, "phone": phone,
                           "confidence": float(probabilities[index:end, ids[index]].mean())})
        index = end
    if with_frames:
        if with_frames == "lazy":
            return LazyEvidence(events, probabilities, reverse, step, offset)
        frames = [{"time": i * step + offset,
                   "candidates": {reverse[int(j)]: float(row[j]) for j in np.argsort(row)[-5:]}}
                  for i, row in enumerate(probabilities)]
        return events, frames
    return events


class LazyEvidence:
    """Tuple-compatible evidence: event-only retries never materialize frame dictionaries."""
    def __init__(self, events, probabilities, reverse, step, offset):
        self.events = events
        self.probabilities = probabilities
        self.reverse, self.step, self.offset = reverse, step, offset
        self.frames = None

    def __getitem__(self, index):
        if index == 0:
            return self.events
        if index != 1:
            raise IndexError(index)
        if self.frames is None:
            self.frames = [{"time": i * self.step + self.offset,
                            "candidates": {self.reverse[int(j)]: float(row[j])
                                           for j in np.argsort(row)[-5:]}}
                           for i, row in enumerate(self.probabilities)]
            self.probabilities = None
        return self.frames


def vowel_proposals(events, duration):
    """CTC peaks are anchors, not proven phone boundaries; limit blank holds."""
    intervals = []
    for index, event in enumerate(events):
        label = event["phone"].lower()
        if label not in VOWELS or event["confidence"] < 0.95:
            continue
        start = max(0, event["time"] - 0.01)
        if index:
            before = events[index - 1]
            if (before["phone"] not in (*VOWELS, "I", "U", "N", "p", "b", "m", "cl")
                    and before["confidence"] >= 0.95 and event["time"] - before["time"] <= 0.1):
                start = max(0, before["time"] - 0.01)
        end = events[index + 1]["time"] - 0.01 if index + 1 < len(events) else duration
        end = min(end, event["time"] + 0.3, duration)
        if end > start:
            intervals.append((round(start * TICKS), round(end * TICKS), label))
    return intervals


def correct_uncertain(rows, proposals, observations, step, *, protect_supported=False):
    output = []
    for start, end, label in rows:
        if label in ("N", "pau"):
            output.append((start, end, label))
            continue
        boundaries = {start, end}
        for left, right, _ in proposals:
            boundaries.update(tick for tick in (left, right) if start < tick < end)
        first, last = math.ceil(start / (step * TICKS)), math.floor(end / (step * TICKS))
        boundaries.update(round(index * step * TICKS) for index in range(first, last + 1)
                          if start < index * step * TICKS < end)
        ticks = sorted(boundaries)
        for left, right in zip(ticks, ticks[1:]):
            middle = (left + right) / 2
            index = min(len(observations) - 1, int(middle / (step * TICKS)))
            candidate = next((shape for a, b, shape in proposals if a <= middle < b), None)
            replacement = candidate if observations[index] is None and candidate else label
            output.append((left, right, replacement))
    protected = [row for row in rows if row[1] - row[0] < 600_000] + list(proposals) if protect_supported else ()
    return suppress_short_vowels(merge(output), protected=protected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    args = parser.parse_args()
    model = args.model_dir / "model_quantized.onnx"
    vocab = json.loads((args.model_dir / "vocab.json").read_text())
    config = json.loads((args.model_dir / "config.json").read_text())
    processor = json.loads((args.model_dir / "preprocessor_config.json").read_text())
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    loaded = time.perf_counter()
    session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
    load_seconds = time.perf_counter() - loaded
    report, rtfs = {}, []
    inputs = review_inputs(args.source, args.review, True)
    first_audio, first_rate = read_wav(inputs[0][2])
    recognize(session, first_audio, first_rate, vocab, config, processor)  # warm-up only
    for key, stem, wav, text, saved_baseline in inputs:
        audio, rate = read_wav(wav)
        duration = len(audio) / rate
        baseline = saved_baseline or read_lab(wav.with_suffix(".lab"), duration)
        stable = acoustic(baseline, audio, rate, stabilize=True)
        started = time.perf_counter()
        events = recognize(session, audio, rate, vocab, config, processor)
        observations, step = acoustic_frames(audio, rate)
        candidate = correct_uncertain(stable, vowel_proposals(events, duration), observations, step)
        rtfs.append((time.perf_counter() - started) / duration)
        variants = {"baseline": baseline, "acoustic_stable": stable, "ctc_local": candidate}
        report[key] = {"events": events, "metrics": {name: metrics(rows) for name, rows in variants.items()},
                       "candidateRTF": rtfs[-1]}
        for name, rows in variants.items():
            target = args.review / "media" / f"{stem}.{name}.lab"
            target.write_text("".join(f"{a} {b} {shape}\n" for a, b, shape in rows))
            read_lab(target, duration)
        assert [r for r in stable if r[2] in ("N", "pau")] == [r for r in candidate if r[2] in ("N", "pau")]
    metadata = {"modelSha256": hashlib.sha256(model.read_bytes()).hexdigest(), "modelBytes": model.stat().st_size,
                "sessionLoadSeconds": load_seconds, "warmCandidateP95RTF": float(np.percentile(rtfs, 95)),
                "runtime": ort.__version__, "threads": 2, "records": report}
    (args.review / "ctc-local-report.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    print(json.dumps({key: value for key, value in metadata.items() if key != "records"}))


if __name__ == "__main__":
    main()
