"""Retry acoustically uncovered phrases without forcing transcript phones."""
import numpy as np

from lipsync_ctc_probe import recognize


def phrase_ranges(rows, duration):
    cuts = [0.0]
    cuts.extend((start + end) / 20_000_000 for start, end, label in rows
                if label == "pau" and end - start >= 1_200_000 and start > 0 and end / 10_000_000 < duration)
    cuts.append(duration)
    return list(zip(cuts, cuts[1:]))


def recover_phrases(events, rows, audio, rate, recognizer):
    ranges = phrase_ranges(rows, len(audio) / rate)
    if len(ranges) == 1:
        return list(events), []
    result, attempts = list(events), []
    for start, end in ranges:
        original = [event for event in events if start <= event["time"] < end]
        if any(event["phone"].lower() in ("a", "i", "u", "e", "o")
               and event["confidence"] >= 0.95 for event in original):
            continue
        segment = audio[round(start * rate):round(end * rate)]
        if end - start < 0.25 or not len(segment) or float(np.sqrt(np.mean(segment ** 2))) < 0.009:
            continue
        recovered = recognizer(segment, rate)
        strong = [{**event, "time": event["time"] + start} for event in recovered
                  if event["confidence"] >= 0.95]
        # Preserve old evidence. Weak retry events cannot shorten existing proposals.
        added = [event for event in strong if not any(
            old["phone"] == event["phone"] and old["confidence"] >= 0.95
            and abs(old["time"] - event["time"]) < 0.02 for old in result)]
        result.extend(added)
        attempts.append({"start": start, "end": end, "events": recovered, "added": added})
    return sorted(result, key=lambda event: event["time"]), attempts


def model_recognizer(session, vocab, config, processor):
    return lambda audio, rate: recognize(session, audio, rate, vocab, config, processor)


def uncovered_ranges(events, rows, audio, rate):
    """Find voiced local gaps; a supported vowel elsewhere cannot hide a gap."""
    step = 0.02
    gaps = []
    for left, right, label in rows:
        if label in ("N", "pau"):
            continue
        start, end = left / 1e7, right / 1e7
        for tick in np.arange(start, end, step):
            segment = audio[round(tick * rate):round(min(tick + step, end) * rate)]
            voiced = len(segment) and float(np.sqrt(np.mean(segment ** 2))) >= 0.009
            supported = any(event["confidence"] >= 0.95
                            and event["phone"].lower() in ("a", "i", "u", "e", "o")
                            and event["time"] - 0.1 <= tick <= event["time"] + 0.18 for event in events)
            if voiced and not supported:
                if gaps and abs(gaps[-1][1] - tick) < 0.001:
                    gaps[-1][1] = min(tick + step, end)
                else:
                    gaps.append([float(tick), float(min(tick + step, end))])
    return [(start, end) for start, end in gaps if end - start >= 0.12 - 1e-9]


def recover_local(events, rows, audio, rate, recognizer):
    """At most two context windows per gap, with conservative evidence merging."""
    result, attempts = list(events), []
    duration = len(audio) / rate
    for left, right in uncovered_ranges(events, rows, audio, rate):
        for padding in (0.2, 0.4):
            start, end = max(0, left - padding), min(duration, right + padding)
            segment = audio[round(start * rate):round(end * rate)]
            # A recording-edge crop lacks real left context. The second retry
            # supplies neutral context, then removes its exact duration from times.
            prefix = 0.4 if start == 0 and padding == 0.4 else 0.0
            if prefix:
                segment = np.concatenate((np.zeros(round(prefix * rate), dtype=audio.dtype), segment))
            try:
                recovered = recognizer(segment, rate)
            except Exception as error:
                attempts.append({"gap": [left, right], "start": start, "end": end,
                                 "added": [], "reason": "recognizer_failure", "error": type(error).__name__})
                continue
            strong = [{**event, "time": event["time"] + start - prefix} for event in recovered
                      if event["confidence"] >= 0.95
                      and 0 <= event["time"] + start - prefix < duration
                      and left - 0.04 <= event["time"] + start - prefix <= right + 0.04]
            added = [event for event in strong if not any(
                old["confidence"] >= 0.95 and abs(old["time"] - event["time"]) < 0.06 for old in result)]
            result.extend(added)
            attempts.append({"gap": [left, right], "start": start, "end": end, "prefixSeconds": prefix, "events": recovered,
                             "added": added, "reason": "acoustic_support" if added else "no_new_support"})
            if any(event["phone"].lower() in ("a", "i", "u", "e", "o") for event in added):
                break
    return sorted(result, key=lambda event: event["time"]), attempts


def local_proposals(events, attempts, duration):
    """Only newly supported vowels in each detected gap may alter the baseline."""
    from lipsync_ctc_probe import vowel_proposals
    proposals = []
    for attempt in attempts:
        left, right = attempt["gap"]
        for a, b, shape in vowel_proposals(events, duration):
            if any(a / 1e7 <= event["time"] <= b / 1e7 and event["phone"].lower() == shape
                   for event in attempt["added"]):
                start, end = max(a, round((left - 0.04) * 1e7)), min(b, round((right + 0.04) * 1e7))
                if end > start:
                    proposals.append((start, end, shape))
    return proposals
