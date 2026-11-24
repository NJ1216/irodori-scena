"""Opt-in fixed-model experiments; caches and diagnostic records belong to one row."""
import hashlib
import json
import time
from contextlib import contextmanager

from lipsync_ctc_probe import decode_logits, prepare_input


class CandidateRecognizer:
    """Same experimental output path without per-inference diagnostic work."""
    def __init__(self, session, settings, identity, *, mode='lazy', cache=True):
        self.session, self.settings, self.identity = session, settings, identity
        self.mode, self.cache_enabled = mode, cache
        self.cache, self.calls, self.stages = {}, [], {}
        self.identity_hash = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def __call__(self, audio, rate):
        vocab, config, processor = self.settings
        values = prepare_input(audio, rate, processor)
        key = None
        if self.mode == 'prepared' and self.cache_enabled:
            key = (self.identity_hash, values.shape, hashlib.sha256(values.tobytes()).digest())
            if key in self.cache:
                return self.cache[key]
        logits = self.session.run(None, {'input_values': values})[0][0]
        result = decode_logits(logits, vocab, config, with_frames='lazy')
        if key is not None:
            self.cache[key] = result
        return result

    def clear(self):
        self.cache.clear()


class DiagnosticRecognizer:
    def __init__(self, session, settings, identity, *, mode='baseline', cache=True):
        self.session, self.settings, self.identity = session, settings, identity
        self.mode, self.cache_enabled = mode, cache
        self.stage = 'full'
        self.calls, self.stages, self.cache = [], {}, {}
        self.identity_hash = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    @contextmanager
    def phase(self, name):
        previous, self.stage = self.stage, name
        started = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0) + time.perf_counter() - started
            self.stage = previous

    def __call__(self, audio, rate):
        vocab, config, processor = self.settings
        started = time.perf_counter()
        values = prepare_input(audio, rate, processor)
        prepared = time.perf_counter() - started
        digest = hashlib.sha256(values.tobytes()).hexdigest()
        key = (self.identity_hash, values.shape, digest)
        hit = self.mode == 'prepared' and self.cache_enabled and key in self.cache
        inference, post = 0, 0
        if hit:
            result = self.cache[key]
        else:
            before = time.perf_counter()
            logits = self.session.run(None, {'input_values': values})[0][0]
            inference = time.perf_counter() - before
            before = time.perf_counter()
            result = decode_logits(logits, vocab, config,
                                   with_frames=True if self.mode == 'baseline' else 'lazy')
            post = time.perf_counter() - before
            if self.mode == 'prepared' and self.cache_enabled:
                self.cache[key] = result
        self.calls.append({'stage': self.stage, 'samples': values.shape[1], 'inputSha256': digest,
                           'identitySha256': self.identity_hash, 'cacheHit': hit,
                           'preprocessSeconds': prepared, 'inferenceSeconds': inference,
                           'postprocessSeconds': post, 'seconds': time.perf_counter() - started})
        return result

    def memo_hit(self, audio, rate):
        # Raw-input cache hits are observable too; hashing here is diagnostic overhead.
        values = prepare_input(audio, rate, self.settings[2])
        self.calls.append({'stage': self.stage, 'samples': values.shape[1],
                           'inputSha256': hashlib.sha256(values.tobytes()).hexdigest(),
                           'identitySha256': self.identity_hash, 'cacheHit': True,
                           'cacheKind': 'raw', 'inferenceSeconds': 0})

    def clear(self):
        self.cache.clear()
