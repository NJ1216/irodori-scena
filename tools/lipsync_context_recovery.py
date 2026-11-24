"""Recover local blank-heavy speech with bounded retries and retained posteriors."""
import math

import numpy as np

from evaluate_japanese_lipsync import merge
from lipsync_articulation import (CLOSED, OPEN_ONSETS, TICKS, VOWELS, closure_guards, core_events,
                                 limit_at_pauses, speech_supported, vowel_windows)
from lipsync_phrase_recovery import uncovered_ranges


def context_gaps(frames, rows, audio, rate, *, short_vowel_retries=True):
    """Join nearby unsupported speech, but never join across a baseline pause."""
    events = core_events(frames)
    gaps = uncovered_ranges(events, rows, audio, rate)
    # A short vowel can be too brief for the 120ms voiced-gap detector. A near-strong
    # nucleus with a strong consonant triggers a retry, never a direct correction.
    for prior, event in zip(events, events[1:]) if short_vowel_retries else ():
        shape = event['phone'].lower()
        tick = round(event['time'] * TICKS)
        current = next((label for a, b, label in rows if a <= tick < b), None)
        if (shape in VOWELS and not event['coreSupported'] and event['peak'] >= .9
                and event['confidence'] >= .7 and prior['phone'] in OPEN_ONSETS
                and prior['confidence'] >= .95 and 0 < event['time'] - prior['time'] <= .08
                and current in VOWELS and current != shape):
            gaps.append((max(0, prior['time'] - .01),
                         min(len(audio) / rate, event['time'] + .25)))
    gaps.sort()
    pauses = [(a / TICKS, b / TICKS) for a, b, label in rows if label == 'pau']
    grouped = []
    for start, end in gaps:
        if (grouped and start - grouped[-1][1] <= 0.12 + 1e-9
                and not any(max(a, grouped[-1][1]) < min(b, start) for a, b in pauses)):
            grouped[-1][1] = max(grouped[-1][1], float(end))
        else:
            grouped.append([float(start), float(end)])
    return grouped


def absolute_frames(frames, start, end, prefix):
    """Reject synthetic prefix evidence and malformed/out-of-crop timestamps."""
    result = []
    previous = -math.inf
    for frame in frames:
        local = float(frame['time'])
        candidates = frame['candidates']
        if not math.isfinite(local) or local <= previous:
            raise ValueError('Nonmonotonic frame times')
        previous = local
        if any(not math.isfinite(p) or not 0 <= p <= 1 for p in candidates.values()):
            raise ValueError('Invalid posterior')
        time = start + (local - prefix)
        if start <= time < end:
            result.append({**frame, 'time': time})
    return result


def recovered_windows(frames, rows, duration, left, right):
    events = core_events(frames)
    windows, evidence = vowel_windows(events, duration)
    # Adjacent supported vowels are valid hiatus; do not require a fabricated consonant.
    for index, event in enumerate(events):
        if index == 0 or event['phone'].lower() not in VOWELS or not event['coreSupported']:
            continue
        prior = events[index - 1]
        if prior['phone'].lower() not in VOWELS or not prior['coreSupported']:
            continue
        if not 0 < event['time'] - prior['time'] <= 0.25:
            continue
        following = events[index + 1] if index + 1 < len(events) else None
        start, end = event['time'] - 0.01, min(duration, event['time'] + 0.25)
        if following:
            end = min(end, following['time'] - (0.04 if following['phone'] in CLOSED else 0.01))
        if end - start >= 0.02:
            windows.append((round(start * TICKS), round(end * TICKS), event['phone'].lower()))
            evidence.append({**event, 'shape': event['phone'].lower(), 'reason': 'supported_hiatus'})
    windows, evidence = limit_at_pauses(windows, evidence, rows)
    clipped = []
    for a, b, label in windows:
        a, b = max(a, round(left * TICKS)), min(b, round(right * TICKS))
        if b - a >= 200_000:
            clipped.append((a, b, label))
    return clipped, evidence, events


def apply_windows(rows, windows, protected, audio, rate):
    output = []
    for start, end, label in rows:
        if label in ('N', 'pau'):
            output.append((start, end, label))
            continue
        cuts = {start, end}
        for a, b, _ in (*windows, *protected):
            cuts.update(t for t in (a, b) if start < t < end)
        ordered = sorted(cuts)
        for a, b in zip(ordered, ordered[1:]):
            middle = (a + b) / 2
            shape = next((s for left, right, s in windows if left <= middle < right), label)
            if (b - a < 200_000 or any(left <= middle < right for left, right, _ in protected)
                    or not speech_supported(audio, rate, a, b)):
                shape = label
            output.append((a, b, shape))
    return merge(output)


def recover_context(rows, frames, audio, rate, recognizer, *, short_vowel_retries=True, retained_nuclei=()):
    """Two attempts per gap; preserve all existing N/pau and strong full-CTC cores."""
    attempts, windows, recovered_guards = [], [], []
    duration = len(audio) / rate
    full = core_events(frames)
    protected = [*closure_guards(full), *retained_nuclei]
    protected.extend((round((e['time'] - 0.02) * TICKS),
                      round((e['coreEndTime'] + 0.02) * TICKS), e['phone'])
                     for e in full if e['coreSupported'])
    for left, right in context_gaps(frames, rows, audio, rate, short_vowel_retries=short_vowel_retries):
        options = []
        for padding, prefix in ((0.2, 0.0), (0.4, 0.4)):
            start, end = max(0, left - padding), min(duration, right + padding)
            segment = audio[round(start * rate):round(end * rate)]
            if prefix:
                segment = np.concatenate((np.zeros(round(prefix * rate), dtype=audio.dtype), segment))
            audit = {'gap': [left, right], 'start': start, 'end': end, 'prefixSeconds': prefix}
            try:
                _, local = recognizer(segment, rate)
                local = absolute_frames(local, start, end, prefix)
                proposals, evidence, events = recovered_windows(local, rows, duration, left, right)
                # Compare actual supporting nuclei, not long blank holds or TXT agreement.
                score = sum(0.02 + e['coreEndTime'] - e['time'] for e in events
                            if left <= e['time'] < right and e['coreSupported']
                            and e['phone'].lower() in VOWELS)
                audit.update(frames=local, evidence=evidence, windows=proposals, score=score,
                             reason='acoustic_support', selected=False)
                options.append((score, proposals, events, audit))
            except Exception as error:
                audit.update(reason='recognizer_failure', error=type(error).__name__, selected=False)
            attempts.append(audit)
        if options:
            _, proposals, events, selected = max(options, key=lambda item: item[0])
            selected['selected'] = True
            windows.extend(proposals)
            recovered_guards.extend(closure_guards(events))
    after = apply_windows(rows, windows, [*protected, *recovered_guards], audio, rate)
    return after, {'attempts': attempts, 'windows': windows,
                   'guards': [*protected, *recovered_guards], 'textInfluence': 'none'}
