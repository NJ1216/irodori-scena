"""Conservative vowel conflict experiments; closures and pauses remain protected."""
from evaluate_japanese_lipsync import merge
from lipsync_ctc_probe import vowel_proposals

VOWELS = frozenset(('a', 'i', 'u', 'e', 'o'))
ONSET = frozenset(('k', 'g', 's', 'z', 'sh', 'j', 't', 'd', 'ch', 'ts', 'n', 'h', 'f', 'r', 'y', 'w'))


def supported_proposals(events, duration):
    """Require strong consonant/vowel/next-phone anchors; do not extend blank tails."""
    accepted, decisions = [], []
    proposals = vowel_proposals(events, duration)
    for index, event in enumerate(events):
        if event['phone'].lower() not in VOWELS or not 0 < index < len(events) - 1:
            continue
        before, after = events[index - 1], events[index + 1]
        if (event['confidence'] < 0.99 or before['confidence'] < 0.99 or after['confidence'] < 0.95
                or before['phone'] not in ONSET
                or not 0 < event['time'] - before['time'] <= 0.06
                or not 0 < after['time'] - event['time'] <= 0.18):
            continue
        interval = next((row for row in proposals if row[2] == event['phone'].lower()
                         and row[0] / 1e7 <= event['time'] < row[1] / 1e7), None)
        if interval:
            accepted.append(interval)
            decisions.append({'start': interval[0] / 1e7, 'end': interval[1] / 1e7,
                              'shape': interval[2], 'anchors': [before, event, after]})
    return accepted, decisions


def resolve_supported_conflicts(rows, events):
    """Correct >=60ms overlapping vowels only; never overwrite N/pau or short rows."""
    proposals, evidence = supported_proposals(events, rows[-1][1] / 1e7)
    output, changes = [], []
    for start, end, label in rows:
        if label not in VOWELS or end - start < 600_000:
            output.append((start, end, label))
            continue
        cursor = start
        for a, b, shape in sorted(proposals):
            left, right = max(cursor, a), min(end, b)
            if shape == label or right - left < 600_000:
                continue
            if cursor < left:
                output.append((cursor, left, label))
            output.append((left, right, shape))
            changes.append({'start': left / 1e7, 'end': right / 1e7, 'before': label, 'after': shape,
                            'reason': 'strong_consonant_vowel_next_phone_anchors'})
            cursor = right
        if cursor < end:
            output.append((cursor, end, label))
    return merge(output), {'changes': changes, 'evidence': evidence}
