"""The complete Japanese refinement sequence; Rhubarb remains the fallback."""
import hashlib
from contextlib import nullcontext

from evaluate_japanese_lipsync import acoustic, acoustic_frames
from lipsync_articulation import safe_refine_articulation
from lipsync_boundary_refinement import refine_boundaries, waveform_changes
from lipsync_ctc_probe import correct_uncertain, vowel_proposals
from lipsync_context_recovery import recover_context
from lipsync_isolated_vowels import recover_isolated_vowels
from lipsync_phrase_recovery import local_proposals, recover_local, recover_phrases
from lipsync_supported_conflicts import resolve_supported_conflicts
from lipsync_confirmed_vowels import confirm_missed_vowels
from lipsync_model_profile import COMMON_ANALYSIS_VERSION
from lipsync_unrecognized_vowels import preserve_unrecognized_vowels
from lipsync_vowel_evidence import adopted_nuclei, join_unsupported_fragments, vowel_evidence_policy

ANALYSIS_VERSION = 'japanese-ctc-context-v3'


def memoized_recognizer(infer):
    """Reuse identical retries within one WAV only; do not retain cross-take audio."""
    cache = {}

    def recognizer(samples, frequency):
        key = (frequency, hashlib.sha256(samples.tobytes()).digest())
        if key not in cache:
            cache[key] = infer(samples, frequency)
        elif hasattr(infer, "memo_hit"):
            infer.memo_hit(samples, frequency)
        return cache[key]

    return recognizer


def refine_japanese(rows, audio, rate, recognizer, *, memoize=True, confirm_vowels=False, snapshot=None):
    with vowel_evidence_policy(confirm_vowels):
        return _refine_japanese(rows, audio, rate, recognizer, memoize=memoize,
                                confirm_vowels=confirm_vowels, snapshot=snapshot)


def _refine_japanese(rows, audio, rate, recognizer, *, memoize, confirm_vowels, snapshot):
    diagnostic = recognizer
    def phase(name):
        return diagnostic.phase(name) if hasattr(diagnostic, "phase") else nullcontext()
    recognizer = memoized_recognizer(recognizer) if memoize else recognizer
    def capture(name, values):
        if snapshot is not None:
            snapshot(name, tuple(tuple(row) for row in values))

    capture('original', rows)

    duration = len(audio) / rate
    with phase('full'):
        full_events, frames = recognizer(audio, rate)
    def event_recognizer(samples, frequency):
        return recognizer(samples, frequency)[0]
    with phase('phrase'):
        events, phrase_audit = recover_phrases(full_events, rows, audio, rate, event_recognizer)
    with phase('acoustic_frames'):
        observations, step = acoustic_frames(audio, rate)
    with phase('acoustic'):
        stable = acoustic(rows, audio, rate, stabilize=True, frame_observations=(observations, step))
    capture('acoustic', stable)
    with phase('correction'):
        corrected = correct_uncertain(stable, vowel_proposals(events, duration), observations, step)
    capture('correction', corrected)
    with phase('boundary'):
        candidate, moves = refine_boundaries(corrected, events, *waveform_changes(audio, rate))
    capture('boundary', candidate)
    with phase('local'):
        recovered, attempts = recover_local(events, rows, audio, rate, event_recognizer)
    proposals = local_proposals(recovered, attempts, duration)
    if proposals:
        candidate = correct_uncertain(candidate, proposals, observations, step, protect_supported=True)
    capture('local', candidate)
    with phase('conflicts'):
        candidate, conflicts = resolve_supported_conflicts(candidate, recovered)
    capture('conflicts', candidate)
    with phase('articulation'):
        candidate, articulation = safe_refine_articulation(candidate, frames, audio, rate)
    capture('articulation', candidate)
    # Preserve the reviewed stages: first broad blank recovery, then confirmation
    # of short near-strong vowels. Both stages retain their own accepted baseline.
    with phase('context'):
        candidate, context = recover_context(candidate, frames, audio, rate, recognizer,
                                             short_vowel_retries=False)
    capture('context', candidate)
    retained = adopted_nuclei(candidate, context) if confirm_vowels else []
    with phase('shortVowel'):
        candidate, short = recover_context(candidate, frames, audio, rate, recognizer, retained_nuclei=retained)
    capture('shortVowel', candidate)
    if confirm_vowels:
        retained.extend(adopted_nuclei(candidate, short))
    with phase('isolatedVowel'):
        candidate, isolated = recover_isolated_vowels(candidate, frames, audio, rate, recognizer)
    capture('isolatedVowel', candidate)
    if confirm_vowels:
        retained.extend(adopted_nuclei(candidate, isolated))
    confirmed = {}
    if confirm_vowels:
        with phase('confirmedVowels'):
            candidate, confirmed = confirm_missed_vowels(candidate, frames, audio, rate, recognizer,
                                                        protected=retained)
        capture('confirmedVowels', candidate)
        candidate, fragments = join_unsupported_fragments(candidate, frames, retained)
        confirmed['fragmentChanges'] = fragments
        capture('coalescedVowels', candidate)
        with phase('unrecognizedVowels'):
            candidate, fallback = preserve_unrecognized_vowels(rows, candidate, recovered, audio, rate, recognizer)
        confirmed['unrecognizedVowels'] = fallback
        capture('unrecognizedVowels', candidate)
    return candidate, {'analysisVersion': COMMON_ANALYSIS_VERSION if confirm_vowels else ANALYSIS_VERSION,
                       'textInfluence': 'none', 'confirmedVowels': confirmed,
                       'phrase': phrase_audit, 'local': attempts, 'boundaryMoves': moves,
                       'conflicts': conflicts, 'articulation': articulation,
                       'context': context, 'shortVowel': short, 'isolatedVowel': isolated}
