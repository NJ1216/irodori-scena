"""Request-local vowel support; legacy models retain their reviewed thresholds."""
from contextlib import contextmanager
from contextvars import ContextVar

_COMMON_SUPPORT = ContextVar('japanese_common_vowel_support', default=False)


def common_support_enabled():
    return _COMMON_SUPPORT.get()


@contextmanager
def vowel_evidence_policy(enabled):
    token = _COMMON_SUPPORT.set(enabled)
    try:
        yield
    finally:
        _COMMON_SUPPORT.reset(token)


def nucleus_support(run, legacy):
    """Weak run tails cannot erase a separated, adjacent two-frame vowel nucleus."""
    if not _COMMON_SUPPORT.get() or run['phone'].lower() not in ('a', 'i', 'u', 'e', 'o'):
        return legacy
    pairs = zip(run['probabilities'], run['probabilities'][1:], run['margins'],
                run['margins'][1:], run['times'], run['times'][1:])
    return legacy or any(min(a, b) >= .5 and max(a, b) >= .95
                         and min(ma, mb) >= .05 and (ma + mb) / 2 >= .4 and 0 < tb - ta <= .021
                         for a, b, ma, mb, ta, tb in pairs)


def onset_supported(event, threshold=.95):
    if event['confidence'] >= threshold:
        return True
    return (_COMMON_SUPPORT.get() and event.get('coreSupported', False)
            and event.get('peak', 0) >= .98 and event['confidence'] >= .7)


def adopted_nuclei(rows, audit):
    """Carry adopted nuclei corroborated by BOTH crop contexts, never blank holds."""
    from lipsync_articulation import TICKS, VOWELS, core_events
    result = []
    for attempt in audit.get('attempts', []):
        if not attempt.get('selected', attempt.get('accepted', False)):
            continue
        events = attempt.get('events') or core_events(attempt.get('frames', []))
        peers = [other for other in audit.get('attempts', []) if other is not attempt
                 and other.get('gap') == attempt.get('gap')
                 and other.get('reason') != 'recognizer_failure']
        for event in events:
            shape = event['phone'].lower()
            if shape not in VOWELS or not event['coreSupported']:
                continue
            if not any(any(e['phone'].lower() == shape and e['coreSupported']
                           and abs(e['time'] - event['time']) <= .04 + 1e-9
                           for e in (peer.get('events') or core_events(peer.get('frames', []))))
                       for peer in peers):
                continue
            tick = round(event['time'] * TICKS)
            for a, b, label in rows:
                if label == shape and a <= tick < b:
                    result.append((max(a, tick - 200_000),
                                   min(b, round((event['coreEndTime'] + .02) * TICKS)), shape))
    return result


def join_unsupported_fragments(rows, frames, retained):
    """Remove only sub-20ms opposite-vowel flicker between the same vowel."""
    from evaluate_japanese_lipsync import merge
    from lipsync_articulation import TICKS, VOWELS, core_events
    nuclei = [*retained, *((round(e['time'] * TICKS), round((e['coreEndTime'] + .02) * TICKS),
                           e['phone'].lower()) for e in core_events(frames) if e['coreSupported'])]
    output, changes = list(rows), []
    for i, (a, b, label) in enumerate(rows):
        if (i == 0 or i + 1 == len(rows) or label not in VOWELS or b - a >= 200_000
                or rows[i - 1][2] != rows[i + 1][2] or rows[i - 1][2] not in VOWELS):
            continue
        if any(shape == label and max(a, left) < min(b, right) for left, right, shape in nuclei):
            continue
        output[i] = (a, b, rows[i - 1][2])
        changes.append({'start': a, 'end': b, 'before': label, 'after': output[i][2],
                        'reason': 'unsupported_sub20ms_fragment'})
    return merge(output), changes
