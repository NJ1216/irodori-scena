"""Two-context confirmation of short independent vowels bounded by existing pauses."""
import numpy as np

from lipsync_articulation import TICKS, VOWELS, closure_guards, core_events
from lipsync_context_recovery import absolute_frames, apply_windows


def recover_isolated_vowels(rows, frames, audio, rate, recognizer):
    full = core_events(frames)
    windows, attempts = [], []
    guards = closure_guards(full)
    guards.extend((round((e['time'] - .02) * TICKS),
                   round((e['coreEndTime'] + .02) * TICKS), e['phone'])
                  for e in full if e['coreSupported'])
    duration = len(audio) / rate
    for index, (a, b, label) in enumerate(rows):
        if (label not in VOWELS or not 200_000 <= b - a <= 1_800_000
                or index == 0 or index + 1 == len(rows)
                or rows[index - 1][2] != 'pau' or rows[index + 1][2] != 'pau'):
            continue
        candidates = [e for e in full if a <= e['time'] * TICKS < b
                      and e['phone'].lower() in VOWELS and e['phone'].lower() != label
                      and e['peak'] >= .9 and e['confidence'] >= .7]
        if len(candidates) != 1:
            continue
        target = candidates[0]['phone'].lower()
        options = []
        for padding, prefix in ((.2, 0), (.4, .4)):
            start, end = max(0, a / TICKS - padding), min(duration, b / TICKS + padding)
            segment = audio[round(start * rate):round(end * rate)]
            if prefix:
                segment = np.concatenate((np.zeros(round(prefix * rate), dtype=audio.dtype), segment))
            audit = {'gap': [a / TICKS, b / TICKS], 'prefixSeconds': prefix, 'target': target}
            try:
                _, local = recognizer(segment, rate)
                events = core_events(absolute_frames(local, start, end, prefix))
                supported = [e for e in events if a <= e['time'] * TICKS < b and e['coreSupported']
                             and e['phone'].lower() in VOWELS]
                accepted = len(supported) == 1 and supported[0]['phone'].lower() == target
                audit.update(events=events, accepted=accepted, reason='confirmation')
                options.append((accepted, events))
            except Exception as error:
                audit.update(accepted=False, reason='recognizer_failure', error=type(error).__name__)
            attempts.append(audit)
        # Require both contexts to agree. A single success or competing vowel is insufficient.
        if len(options) == 2 and all(accepted for accepted, _ in options):
            windows.append((a, b, target))
            for _, events in options:
                guards.extend(closure_guards(events))
    return apply_windows(rows, windows, guards, audio, rate), {
        'attempts': attempts, 'windows': windows, 'guards': guards, 'textInfluence': 'none'}
