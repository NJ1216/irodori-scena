"""Core-frame vowel support and bounded, phonetic closure review for offline LABs."""
import numpy as np

from evaluate_japanese_lipsync import merge
from lipsync_vowel_evidence import common_support_enabled, nucleus_support, onset_supported, vowel_evidence_policy

TICKS = 10_000_000
VOWELS = frozenset(('a', 'i', 'u', 'e', 'o'))
CLOSED = frozenset(('m', 'b', 'p', 'N', 'cl'))
OPEN_ONSETS = frozenset(('k', 'g', 's', 'z', 'sh', 'j', 't', 'd', 'ch', 'ts', 'n', 'h', 'f', 'r', 'y', 'w'))
SPECIAL = frozenset(('PAD', 'SOS', 'EOS', 'UNK', 'sil', 'pau'))


def core_events(frames):
    """Reconstruct greedy runs from saved probabilities; blank remains unknown."""
    runs = []
    for frame in frames:
        if not frame['candidates']:
            continue
        phone = max(frame['candidates'], key=frame['candidates'].get)
        confidence = frame['candidates'][phone]
        margin = confidence - max((p for label, p in frame['candidates'].items() if label != phone), default=0)
        if runs and runs[-1]['phone'] == phone:
            runs[-1]['probabilities'].append(confidence)
            runs[-1]['times'].append(frame['time'])
            runs[-1]['margins'].append(margin)
        else:
            runs.append({'time': frame['time'], 'phone': phone, 'probabilities': [confidence],
                         'times': [frame['time']], 'margins': [margin]})
    result = []
    for run in runs:
        if run['phone'] in SPECIAL:
            continue
        probabilities = run['probabilities']
        consecutive = any(a >= 0.6 and b >= 0.6 for a, b in zip(probabilities, probabilities[1:]))
        result.append({'time': run['time'], 'phone': run['phone'],
                       'confidence': float(np.mean(probabilities)), 'peak': max(probabilities),
                       'coreEndTime': max((t for t, p in zip(run['times'], probabilities) if p >= 0.5), default=run['time']),
                       'coreSupported': nucleus_support(run, max(probabilities) >= 0.95
                           and (min(probabilities) >= 0.95 or (np.mean(probabilities) >= 0.75 and consecutive)))})
    return result


def vowel_windows(events, duration):
    """Keep short supported nuclei; labial onset is never an open-vowel lead-in."""
    windows, audit = [], []
    for index, event in enumerate(events):
        shape = event['phone'].lower()
        if shape not in VOWELS or not event['coreSupported'] or index == 0:
            continue
        before = events[index - 1]
        if before['phone'] not in OPEN_ONSETS | CLOSED or not onset_supported(before):
            continue
        if not 0 < event['time'] - before['time'] <= 0.12:
            continue
        start = event['time'] - 0.01
        if before['phone'] in OPEN_ONSETS:
            start = before['time'] - 0.01
        after = events[index + 1] if index + 1 < len(events) else None
        end = min(duration, event['time'] + 0.25)
        if after:
            end = min(end, after['time'] - (0.04 if after['phone'] in CLOSED else 0.01))
        if end - start < 0.02:
            continue
        window = (round(max(0, start) * TICKS), round(end * TICKS), shape)
        windows.append(window)
        audit.append({'start': window[0] / TICKS, 'end': window[1] / TICKS, 'shape': shape,
                      'time': event['time'], 'coreEndTime': event['coreEndTime'], 'onset': before['phone'], 'average': event['confidence'], 'peak': event['peak'],
                      'reason': 'consecutive_core_frames' if event['confidence'] < 0.95 else 'strong_core'})
    return windows, audit


def limit_at_pauses(windows, evidence, rows):
    """A blank hold cannot resume a vowel on the far side of a baseline pause."""
    result, accepted = [], []
    pauses = [(a, b) for a, b, label in rows if label == 'pau']
    for (start, end, shape), item in zip(windows, evidence):
        peak = round(item['time'] * TICKS)
        containing = next(((a, b) for a, b in pauses if a <= peak < b), None)
        if containing:
            _, pause_end = containing
            if round(item['coreEndTime'] * TICKS) <= pause_end or pause_end - peak > 400_000:
                continue
            # Preserve the pause, but use actual supporting frames on its far side.
            peak = round(item['coreEndTime'] * TICKS)
            start = max(start, pause_end)
        end = min([end] + [a for a, _ in pauses if peak < a < end])
        start = max([start] + [b for _, b in pauses if start < b <= peak])
        if end - start >= 200_000:
            result.append((start, end, shape))
            accepted.append({**item, 'start': start / TICKS, 'end': end / TICKS})
    return result, accepted


def closure_guards(events):
    """Preserve bilabial articulation, nasal closure and stop evidence."""
    guards = []
    for index, event in enumerate(events):
        if event['phone'] not in CLOSED or event['confidence'] < 0.9:
            continue
        end = event['time'] + 0.12
        if index + 1 < len(events):
            end = min(end, events[index + 1]['time'] - 0.01)
        guards.append((round(max(0, event['time'] - 0.04) * TICKS), round(end * TICKS), event['phone']))
    return guards


def align_labial_edges(rows, events):
    """Move an existing labial closure edge <=40ms; never add arbitrary closures."""
    result, moves = list(rows), []
    all_guards = closure_guards(events)
    reliable = [event for event in events if event['phone'] in ('m', 'b', 'p')
                and event['confidence'] >= 0.95]
    guards = closure_guards(reliable_with_followers(events, reliable))
    for index, (start, end, label) in enumerate(result):
        if label != 'N' or index == 0 or index + 1 == len(result):
            continue
        before, after = result[index - 1], result[index + 1]
        if before[2] not in VOWELS or after[2] not in VOWELS:
            continue
        matches = [(a, b) for a, b, phone in guards if phone in ('m', 'b', 'p')
                   and min(end, b) - max(start, a) >= 200_000]
        if len(matches) != 1:
            continue
        left, right = matches[0]
        left = left if abs(left - start) <= 400_000 else start
        right = right if abs(right - end) <= 400_000 else end
        if min(left - before[0], right - left, after[1] - right) < 200_000:
            continue
        if (left, right) == (start, end) or not covers_original_guards(start, end, left, right, all_guards):
            continue
        result[index - 1] = (before[0], left, before[2])
        result[index] = (left, right, 'N')
        result[index + 1] = (right, after[1], after[2])
        moves.append({'from': [start / TICKS, end / TICKS], 'to': [left / TICKS, right / TICKS],
                      'reason': 'bounded_labial_closure_alignment'})
    return result, moves


def covers_original_guards(start, end, left, right, guards):
    """An overlapping stop plus labial sequence must retain both closure guards."""
    return all(left <= max(start, a) and right >= min(end, b)
               for a, b, _ in guards if max(start, a) < min(end, b))


def reliable_with_followers(events, reliable):
    """Retain actual following phones so a guard ends before its vowel nucleus."""
    return [{**event, 'confidence': event['confidence'] if event in reliable
             or event['phone'] not in CLOSED else 0} for event in events]


def speech_supported(audio, rate, start, end):
    segment = audio[round(start / TICKS * rate):round(end / TICKS * rate)]
    return bool(len(segment) and np.sqrt(np.mean(segment ** 2)) >= 0.009)


def closure_replacement(row, windows, guards, audio, rate):
    """Review N separately; do not erase long unanchored closures wholesale."""
    start, end, _ = row
    pieces, audit = [], []
    cuts = {start, end}
    for a, b, _ in (*windows, *guards):
        cuts.update(t for t in (a, b) if start < t < end)
    ordered = sorted(cuts)
    for a, b in zip(ordered, ordered[1:]):
        middle = (a + b) / 2
        protected = any(left <= middle < right for left, right, _ in guards)
        shape = next((label for left, right, label in windows if left <= middle < right), None)
        if not protected and shape and speech_supported(audio, rate, a, b):
            pieces.append((a, b, shape))
        else:
            pieces.append((a, b, 'N'))
    pieces = merge(pieces)
    # A boundary trim is at most 40ms and leaves >=20ms of the remaining closure.
    if len(pieces) == 2 and any(piece[2] == 'N' for piece in pieces):
        closed = next(piece for piece in pieces if piece[2] == 'N')
        opened = next(piece for piece in pieces if piece[2] != 'N')
        if closed[1] - closed[0] >= 200_000 and opened[1] - opened[0] <= 400_000:
            audit.append({'start': opened[0] / TICKS, 'end': opened[1] / TICKS,
                          'before': 'N', 'after': opened[2], 'reason': 'bounded_closure_edge'})
            return pieces, audit
    # Remove only <=40ms closures covered by a supported window; guard overlap forbids this.
    if end - start <= 400_000 and not any(max(start, a) < min(end, b) for a, b, _ in guards):
        shape = next((label for a, b, label in windows if a <= (start + end) / 2 < b
                      and a <= start + 100_000 and b >= end - 100_000), None)
        if shape and speech_supported(audio, rate, start, end):
            return [(start, end, shape)], [{'start': start / TICKS, 'end': end / TICKS,
                                           'before': 'N', 'after': shape, 'reason': 'short_nonlabial_closure'}]
    return [row], [{'start': start / TICKS, 'end': end / TICKS, 'reason': 'closure_preserved',
                    'guarded': any(max(start, a) < min(end, b) for a, b, _ in guards)}]


def refine_articulation(rows, frames, audio, rate):
    events = core_events(frames)
    windows, evidence = vowel_windows(events, len(audio) / rate)
    windows, evidence = limit_at_pauses(windows, evidence, rows)
    # Vowel support calibration must not silently recalibrate closed-mouth edits.
    closure_windows = windows
    if common_support_enabled():
        with vowel_evidence_policy(False):
            legacy_windows, legacy_evidence = vowel_windows(core_events(frames), len(audio) / rate)
            closure_windows, _ = limit_at_pauses(legacy_windows, legacy_evidence, rows)
    guards = closure_guards(events)
    rows, labial_moves = align_labial_edges(rows, events)
    output, changes, closure_audit = [], [], []
    for start, end, label in rows:
        if label == 'pau':
            output.append((start, end, label))
        elif label == 'N':
            pieces, audit = closure_replacement((start, end, label), closure_windows, guards, audio, rate)
            output.extend(pieces)
            closure_audit.extend(audit)
            changes.extend(item for item in audit if 'after' in item)
        else:
            cuts = {start, end}
            for a, b, _ in windows:
                cuts.update(t for t in (a, b) if start < t < end)
            ordered = sorted(cuts)
            for a, b in zip(ordered, ordered[1:]):
                shape = next((shape for left, right, shape in windows if left <= (a + b) / 2 < right), label)
                # Do not invent sub-20ms fragments at a partially overlapping edge.
                if b - a < 200_000:
                    shape = label
                output.append((a, b, shape))
                if shape != label:
                    changes.append({'start': a / TICKS, 'end': b / TICKS, 'before': label,
                                    'after': shape, 'reason': 'core_supported_vowel'})
    return merge(output), {'changes': changes, 'vowelEvidence': evidence,
                          'closureAudit': closure_audit, 'guards': guards, 'labialMoves': labial_moves}


def safe_refine_articulation(rows, frames, audio, rate):
    """Analysis failure retains the current LAB; input integrity is checked by caller."""
    try:
        return refine_articulation(rows, frames, audio, rate)
    except (ValueError, RuntimeError, KeyError, TypeError) as error:
        return list(rows), {'changes': [], 'vowelEvidence': [], 'closureAudit': [], 'guards': [],
                            'labialMoves': [], 'fallback': type(error).__name__}
