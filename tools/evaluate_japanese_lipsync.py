#!/usr/bin/env python3
"""Offline Japanese mouth LAB comparison. Source WAV/LAB/TXT are read only."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import shutil
import wave
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import linalg, signal
from lipsync_temporal import bridge_uncertain_frames, suppress_short_vowels

TICKS = 10_000_000
VOWELS = ("a", "i", "u", "e", "o")
LABELS = frozenset((*VOWELS, "N", "pau"))
# Approximate adult female Japanese vowel centers; only a screening heuristic.
FORMANTS = {"a": (850, 1600), "i": (360, 2750), "u": (400, 1550), "e": (550, 2250), "o": (570, 1050)}


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError(f"16-bit mono PCM WAV required: {path.name}")
        rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64) / 32768
    if rate <= 0 or not len(samples):
        raise ValueError(f"Empty or invalid WAV: {path.name}")
    return samples, rate


def read_lab(path: Path, duration: float) -> list[tuple[int, int, str]]:
    rows = []
    cursor = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            raw_start, raw_end, label = line.split()
            start, end = int(raw_start), int(raw_end)
        except ValueError as error:
            raise ValueError(f"Invalid LAB row {path.name}:{number}") from error
        if start != cursor or end <= start or label not in LABELS:
            raise ValueError(f"Noncontinuous LAB row {path.name}:{number}")
        rows.append((start, end, label))
        cursor = end
    if not rows or abs(cursor / TICKS - duration) > 0.011:
        raise ValueError(f"LAB/WAV length mismatch: {path.name}")
    return rows


def merge(rows: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    result = []
    for start, end, label in rows:
        if result and result[-1][2] == label:
            result[-1] = (result[-1][0], end, label)
        else:
            result.append((start, end, label))
    return result


def contextual(rows: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Extend a neighboring vowel through short Rhubarb B intervals."""
    changed = []
    for index, (start, end, label) in enumerate(rows):
        if label != "i" or end - start > 1_800_000:
            changed.append((start, end, label))
            continue
        before = rows[index - 1][2] if index else None
        after = rows[index + 1][2] if index + 1 < len(rows) else None
        replacement = after if after in VOWELS and after != "i" else before
        changed.append((start, end, replacement if replacement in VOWELS else label))
    return merge(changed)


def frame_formants(frame: np.ndarray, rate: int) -> tuple[float, float] | None:
    emphasized = signal.lfilter([1.0, -0.96], [1.0], frame) * np.hamming(len(frame))
    correlations = signal.correlate(emphasized, emphasized, mode="full", method="fft")
    r = correlations[len(frame) - 1 : len(frame) + 16]
    if r[0] < 1e-6:
        return None
    try:
        coeffs = linalg.solve_toeplitz((r[:16], r[:16]), -r[1:17], check_finite=False)
    except linalg.LinAlgError:
        return None
    roots = np.roots(np.r_[1.0, coeffs])
    roots = roots[np.imag(roots) > 0]
    frequencies = np.angle(roots) * rate / (2 * np.pi)
    bandwidths = -np.log(np.abs(roots)) * rate / np.pi
    accepted = sorted(float(frequency) for frequency, bandwidth in zip(frequencies, bandwidths)
                      if 220 < frequency < 3500 and 0 < bandwidth < 500)
    if len(accepted) < 2 or not 350 < accepted[1] - accepted[0] < 2600:
        return None
    return accepted[0], accepted[1]


def classify_formants(formants: tuple[float, float] | None) -> str | None:
    if formants is None:
        return None
    f1, f2 = formants
    if 700 <= f1 <= 1100 and 1050 <= f2 <= 2200:
        return "a"
    scores = sorted((math.hypot((f1 - center[0]) / 300, (f2 - center[1]) / 600), label)
                    for label, center in FORMANTS.items())
    if scores[0][0] > 0.95 or scores[1][0] - scores[0][0] < 0.32:
        return None
    return scores[0][1]


def acoustic_frames(audio: np.ndarray, rate: int) -> tuple[list[str | None], float]:
    target = 12000
    factor = math.gcd(rate, target)
    reduced = signal.resample_poly(audio, target // factor, rate // factor)
    hop, width = 240, 360  # 20 ms step, 30 ms window
    labels = []
    rms_values = []
    for offset in range(0, len(reduced), hop):
        frame = reduced[max(0, offset - width // 2) : min(len(reduced), offset + width // 2)]
        if len(frame) < width:
            frame = np.pad(frame, (0, width - len(frame)))
        rms = float(np.sqrt(np.mean(frame * frame)))
        rms_values.append(rms)
        labels.append(classify_formants(frame_formants(frame, target)) if rms >= 0.009 else None)
    stable = [None] * len(labels)
    for index in range(2, len(labels) - 2):
        window = labels[index - 2 : index + 3]
        counts = Counter(item for item in window if item is not None)
        if counts:
            label, count = counts.most_common(1)[0]
            if count >= 4 and labels[index] == label:
                stable[index] = label
    quiet_limit = max(0.001, float(np.percentile(rms_values, 90)) * 0.015)
    index = 0
    while index < len(stable):
        if rms_values[index] >= quiet_limit:
            index += 1
            continue
        end = index + 1
        while end < len(stable) and rms_values[end] < quiet_limit:
            end += 1
        if end - index >= 2:
            quiet_shape = "pau" if end - index >= 6 else "N"
            stable[index:end] = [quiet_shape] * (end - index)
        index = end
    return stable, hop / target


def acoustic(rows: list[tuple[int, int, str]], audio: np.ndarray, rate: int,
             stabilize: bool = False, *,
             frame_observations: tuple[list[str | None], float] | None = None
             ) -> list[tuple[int, int, str]]:
    observations, step = frame_observations if frame_observations is not None else acoustic_frames(audio, rate)
    original = observations
    if stabilize:
        observations = bridge_uncertain_frames(observations)
    output = []
    for start, end, label in rows:
        if label == "pau":
            output.append((start, end, label))
            continue
        boundaries = [start]
        first, last = math.ceil(start / (step * TICKS)), math.floor(end / (step * TICKS))
        boundaries.extend(int(round(index * step * TICKS)) for index in range(first, last + 1)
                          if start < index * step * TICKS < end)
        boundaries.append(end)
        for left, right in zip(boundaries, boundaries[1:]):
            index = min(len(observations) - 1, int(((left + right) / (2 * TICKS)) / step))
            original_label = original[index] or label
            replacement = observations[index] or label
            output.append((left, right, original_label if original_label in ("N", "pau") else replacement))
    merged = merge(output)
    return suppress_short_vowels(merged) if stabilize else merged


def metrics(rows: list[tuple[int, int, str]]) -> dict[str, object]:
    by_label = Counter()
    for start, end, label in rows:
        by_label[label] += end - start
    speech = sum(duration for label, duration in by_label.items() if label != "pau")
    return {"segments": len(rows), "speechIShare": round(by_label["i"] / speech, 4) if speech else None,
            "vowelsSeconds": {label: round(by_label[label] / TICKS, 3) for label in VOWELS},
            "pauSeconds": round(by_label["pau"] / TICKS, 3)}


def category(rows: list[tuple[int, int, str]], text: str) -> str:
    speech = sum(end - start for start, end, label in rows if label != "pau")
    longest_i = max((end - start for start, end, label in rows if label == "i"), default=0)
    if any(word in text for word in ("あは", "はは", "ふふ", "……", "…", "笑")):
        return "laugh_or_pause"
    if longest_i >= 5_000_000 or (speech and sum(end - start for start, end, label in rows if label == "i") / speech > 0.65):
        return "long_i"
    return "vowel_mix"


def collect(source: Path, corpus: str) -> list[dict[str, object]]:
    result = []
    other_text = {}
    summary = source.parent / "summary.json"
    if corpus == "other" and summary.is_file():
        payload = json.loads(summary.read_text(encoding="utf-8"))
        other_text = {str(item["key"]): str(item.get("text", "")) for item in payload.get("records", [])
                      if item.get("key")}
    for lab in sorted(source.glob("*.lab")):
        wav, txt = lab.with_suffix(".wav"), lab.with_suffix(".txt")
        if wav.is_file():
            text = txt.read_text(encoding="utf-8").strip() if txt.is_file() else ""
            if not text:
                text = next((value for key, value in other_text.items() if key in lab.stem), "")
            result.append({"corpus": corpus, "stem": lab.stem, "wav": wav, "lab": lab,
                           "text": text})
    return result


def select_review(records: list[dict[str, object]]) -> list[dict[str, object]]:
    chosen = []
    for corpus in ("provided", "other"):
        for group in ("long_i", "vowel_mix", "laugh_or_pause"):
            eligible = [record for record in records if record["corpus"] == corpus and record["category"] == group]
            ranked = sorted(eligible, key=lambda item: hashlib.sha256(str(item["stem"]).encode()).digest())
            chosen.extend(ranked[:4 if corpus == "provided" else 2])
    return chosen


def preview(records: list[dict[str, object]], columns=None) -> str:
    columns = columns or (("baseline", "現行"), ("contextual", "前後の口形"), ("acoustic", "WAV 音響"))
    cards = []
    for record in records:
        stem = html.escape(str(record["reviewStem"]), quote=True)
        script = html.escape(str(record["text"]))
        cards.append(f'<article data-stem="{stem}"><h2>{stem}</h2><p>{script}</p>'
                     f'<audio controls preload="metadata" src="media/{stem}.wav"></audio>'
                     '<div class="comparison">'
                     + "".join(f'<section data-variant="{name}"><h3>{title}</h3>'
                               '<div class="stage"><img class="portrait" src="portrait/pau.png" alt="葵の全身">'
                               '<img class="face" src="portrait/pau-face.png" alt="葵の顔の拡大"></div>'
                               '<div class="shape">口形 <b>pau</b></div>'
                               f'<select aria-label="{title}の評価"><option value="">未評価</option>'
                               '<option value="usable">使用可能</option><option value="concern">懸念あり</option>'
                               '<option value="unusable">使用不可</option></select></section>'
                               for name, title in columns)
                     + '</div><p>違和感の時刻と種類 <input class="note" placeholder="例: 0.8秒、母音が閉じる"></p>'
                     + "".join(f'<label><input type="radio" name="{stem}" value="{name}">{title}</label>'
                               for name, title in (*((name, title + "がよい") for name, title in columns),
                                                   ("none", "どれも不可")))
                     + "</article>")
    page = (Path(__file__).with_name("lipsync_portrait_preview.html")).read_text(encoding="utf-8")
    embedded = json.dumps({str(record["reviewStem"]): record["variants"] for record in records}, ensure_ascii=False)
    return page.replace("<!-- CARDS -->", "\n".join(cards)).replace(
        "/* RECORDS */", "const records = " + embedded.replace("</", "<\\/") + ";"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--other", type=Path, help="Independent cast corpus with WAV/LAB pairs")
    parser.add_argument("--output", type=Path, required=True, help="New empty directory")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Output directory must be new or empty")
    inputs = collect(args.source, "provided") + (collect(args.other, "other") if args.other else [])
    if not inputs:
        parser.error("No matching WAV/LAB pairs")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "media").mkdir()
    records = []
    for item in inputs:
        audio, rate = read_wav(item["wav"])
        duration = len(audio) / rate
        baseline = read_lab(item["lab"], duration)
        variants = {"baseline": baseline, "contextual": contextual(baseline),
                    "acoustic": acoustic(baseline, audio, rate)}
        item.update({"category": category(baseline, item["text"]),
                     "sha256": hashlib.sha256(item["wav"].read_bytes()).hexdigest(),
                     "durationSeconds": duration, "metrics": {name: metrics(rows) for name, rows in variants.items()},
                     "variants": variants})
        records.append(item)
    review = select_review(records)
    review_data = {}
    for index, item in enumerate(review, 1):
        stem = f"{index:02d}_{item['corpus']}_{item['stem']}"
        item["reviewStem"] = stem
        shutil.copyfile(item["wav"], args.output / "media" / f"{stem}.wav")
        review_data[stem] = item["variants"]
        for name, rows in item["variants"].items():
            (args.output / "media" / f"{stem}.{name}.lab").write_text(
                "".join(f"{start} {end} {label}\n" for start, end, label in rows), encoding="utf-8")
    summary = [{key: item[key] for key in ("corpus", "stem", "category", "sha256", "durationSeconds", "metrics")}
               for item in records]
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "review-texts.json").write_text(json.dumps({item["reviewStem"]: item["text"] for item in review}, ensure_ascii=False), encoding="utf-8")
    (args.output / "review-data.json").write_text(json.dumps(review_data, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"total": len(records), "review": len(review), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
