from __future__ import annotations

import importlib
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch
from fastapi import HTTPException
from server import app as _app  # noqa: F401
from server.modules import lora_resource_guard as guard
from server.modules import resource_coordinator, llm_runtime_binding


def dependency_patch(name, *args, **kwargs):
    owner = importlib.import_module(guard.deps._owners[name])
    return patch.object(owner, name, *args, **kwargs)


class TrainingResourceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(guard, '_JOB_ID', None))
        self.stack.enter_context(dependency_patch('shutdown_inference_worker'))
        self.stack.enter_context(dependency_patch('release_memory'))
        self.stack.enter_context(dependency_patch('reset_tts_runtime'))
        self.stack.enter_context(dependency_patch('active_export_job', return_value=None))
        self.stack.enter_context(dependency_patch('active_draft_job', return_value=None))
        self.stack.enter_context(dependency_patch('session_usage', return_value={'history': []}))
        self.stack.enter_context(dependency_patch('llm_model_test_active', return_value=False))
        self.stack.enter_context(dependency_patch('memory_ownership', return_value={'llmResident': False}))
        self.stack.enter_context(patch('server.modules.model_runtime_jobs.active_jobs', return_value=[]))

    def test_duplicate_admission_and_stale_completion_never_release_current_owner(self):
        guard.reserve_training('first')
        with self.assertRaises(HTTPException) as failure:
            guard.reserve_training('second')
        self.assertEqual(failure.exception.status_code, 409)
        guard.release_training('second')
        self.assertEqual(guard.training_job_id(), 'first')
        guard.release_training('first')
        guard.require_runtime_available()
        guard.reserve_training('second')
        guard.release_training('first')
        self.assertEqual(guard.training_job_id(), 'second')

    def test_runtime_transitions_reject_training_without_releasing_owned_processes(self):
        guard.reserve_training('job')
        for invoke in [lambda: resource_coordinator.acquire_tts_memory('test'),
                       lambda: resource_coordinator.acquire_llm_memory('test'),
                       lambda: llm_runtime_binding.require_generation_available('openai'),
                       lambda: llm_runtime_binding.require_load_available('model')]:
            with self.assertRaises(HTTPException):
                invoke()
        guard.deps.shutdown_inference_worker.assert_called_once()

    def test_active_synthesis_blocks_without_stopping_it(self):
        lock = threading.Lock()
        lock.acquire()
        with dependency_patch('INFERENCE_SYNTHESIS_LOCK', lock), self.assertRaises(HTTPException):
            guard.reserve_training('job')
        self.assertIsNone(guard.training_job_id())
        guard.deps.shutdown_inference_worker.assert_not_called()

    def test_resident_llm_and_running_remote_llm_are_retained(self):
        for target, value in [('memory_ownership', {'llmResident': True}),
                              ('session_usage', {'history': [{'status': 'running', 'provider': 'openai'}]})]:
            with dependency_patch(target, return_value=value), self.assertRaises(HTTPException):
                guard.reserve_training('job')
        guard.deps.shutdown_inference_worker.assert_not_called()
        self.assertIsNone(guard.training_job_id())

    def test_failed_owned_worker_stop_does_not_publish_reservation(self):
        guard.deps.shutdown_inference_worker.side_effect = RuntimeError('still alive')
        with self.assertRaises(RuntimeError):
            guard.reserve_training('job')
        self.assertIsNone(guard.training_job_id())

    def test_busy_outer_runtime_lock_fails_immediately(self):
        lock = Mock()
        lock.acquire.return_value = False
        with patch.object(guard, 'LOCK', lock), self.assertRaises(HTTPException):
            guard.reserve_training('job')
        lock.acquire.assert_called_once_with(blocking=False)
        lock.release.assert_not_called()
        guard.deps.shutdown_inference_worker.assert_not_called()
