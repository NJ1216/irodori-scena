"""Confirm missed vowel nuclei in two acoustic contexts, without reading overrides."""
import numpy as np

from lipsync_articulation import (OPEN_ONSETS, TICKS, VOWELS, closure_guards, core_events)
from lipsync_context_recovery import absolute_frames, apply_windows


def missed_nuclei(rows, events):
    targets = []
    for index, event in enumerate(events):
        shape = event['phone'].lower()
        if shape not in VOWELS or event['peak'] < .9 or event['confidence'] < .7:
            continue
        tick = round(event['time'] * TICKS)
        label = next((label for a, b, label in rows if a <= tick < b), None)
        if label not in VOWELS or label == shape:
            continue
        # A candidate is only a trigger. Neither its score nor the script authorizes an edit.
        targets.append((index, event))
    return targets


def corroboration(events, target):
    nearby = [event for event in events if event['phone'].lower() in VOWELS
              and abs(event['time'] - target['time']) <= .06 + 1e-9]
    matches = [event for event in nearby if event['phone'].lower() == target['phone'].lower()
               and event['coreSupported']]
    if len(matches) != 1:
        return None
    if any(event['phone'].lower() != target['phone'].lower() and event['coreSupported']
           and abs(event['time'] - target['time']) <= .04 + 1e-9 for event in nearby):
        return None
    return matches[0]


def target_window(index, events, duration, matches=()):
    event = events[index]
    start = event['time'] - .01
    if index:
        prior = events[index - 1]
        if (prior['phone'] in OPEN_ONSETS and prior['confidence'] >= .9
                and 0 < event['time'] - prior['time'] <= .1):
            start = prior['time'] - .01
    # CTC blank is a hold, not a proven vowel end. Bound a hold by the next
    # actual phone in the full input AND both independently confirmed contexts.
    end = min(duration, event['time'] + .25,
              *(match['nextTime'] - .01 for match in matches if match.get('nextTime') is not None))
    if index + 1 < len(events):
        end = min(end, events[index + 1]['time'] - .01)
    return round(max(0, start) * TICKS), round(end * TICKS), event['phone'].lower()


def confirmed_window(index, full, contexts, duration, protected):
    target = full[index]
    matches = [corroboration(events, target) for events in contexts]
    if not all(matches):
        return None, 'contexts_disagree'
    window = target_window(index, full, duration, matches)
    if any(shape.lower() != window[2] and max(a, window[0]) < min(b, window[1])
           for a, b, shape in protected):
        return None, 'adopted_nucleus_conflict'
    if window[1] - window[0] < 200_000:
        return None, 'too_short'
    return window, 'two_context_support'


def confirm_missed_vowels(rows, frames, audio, rate, recognizer, *, protected=()):
    """Require two independent crop contexts; retain pauses, closures and competing cores."""
    full = core_events(frames)
    targets = missed_nuclei(rows, full)
    attempts, windows, guards, decisions = [], [], [*closure_guards(full), *protected], []
    duration = len(audio) / rate
    # Nearby candidates share the same evidence; no retries are joined across a pause.
    groups = []
    for index, event in targets:
        start, end = max(0, event['time'] - .1), min(duration, event['time'] + .16)
        if (groups and start <= groups[-1]['end'] + .12
                and not any(label == 'pau' and max(a / TICKS, groups[-1]['end']) < min(b / TICKS, start)
                            for a, b, label in rows)):
            groups[-1]['end'] = max(groups[-1]['end'], end)
            groups[-1]['targets'].append((index, event))
        else:
            groups.append({'start': start, 'end': end, 'targets': [(index, event)]})
    for group in groups:
        contexts = []
        for padding, prefix in ((.2, 0), (.4, .4)):
            start, end = max(0, group['start'] - padding), min(duration, group['end'] + padding)
            samples = audio[round(start * rate):round(end * rate)]
            if prefix:
                samples = np.concatenate((np.zeros(round(prefix * rate), dtype=audio.dtype), samples))
            audit = {'start': start, 'end': end, 'prefixSeconds': prefix}
            try:
                _, local = recognizer(samples, rate)
                events = [{**event, 'coreSupported': bool(event['coreSupported'])}
                          for event in core_events(absolute_frames(local, start, end, prefix))]
                for current, following in zip(events, events[1:]):
                    current['nextTime'] = following['time']
                contexts.append(events)
                audit.update(events=events, reason='acoustic_confirmation')
            except Exception as error:
                audit.update(reason='recognizer_failure', error=type(error).__name__)
            attempts.append(audit)
        if len(contexts) != 2:
            continue
        for index, target in group['targets']:
            window, reason = confirmed_window(index, full, contexts, duration, protected)
            decisions.append({'time': target['time'], 'phone': target['phone'], 'reason': reason,
                              'window': window})
            if window is None:
                continue
            windows.append(window)
            for events in contexts:
                guards.extend(closure_guards(events))
    # Strong contradictory full-utterance evidence is not displaced by a crop.
    for event in full:
        if event['coreSupported'] and event['phone'].lower() in VOWELS:
            protected = (round((event['time'] - .02) * TICKS),
                         round((event['coreEndTime'] + .02) * TICKS), event['phone'])
            if any(shape != event['phone'].lower() and max(a, protected[0]) < min(b, protected[1])
                   for a, b, shape in windows):
                guards.append(protected)
    output = apply_windows(rows, windows, guards, audio, rate)
    return output, {'attempts': attempts, 'windows': windows, 'guards': guards,
                    'decisions': decisions, 'targetCount': len(targets), 'textInfluence': 'none'}
