"""Finite forward-only dialogue execution with separate line/scene acceptance."""
from __future__ import annotations

import json

from server.registry import deps
from server.modules import draft_packet_budget, draft_schedule
from server.modules.ollama_context import DraftContextError


class DraftDialogueRun:
    def __init__(self, job_id, request, characters, plan, developments, planned_targets,
                 capability, cast_context, aliases, debug_directory, seed):
        self.job_id, self.request, self.characters = job_id, request, characters
        self.plan, self.chapters = plan, plan["chapters"]
        self.developments, self.pending = developments, [list(items) for items in developments]
        self.planned_targets, self.capability = planned_targets, capability
        self.cast_context, self.aliases = cast_context, aliases
        self.debug_directory, self.seed = debug_directory, seed
        self.token_budget = int(capability["outputTokenLimit"])
        self.max_block = int(capability["maxChunkCharacters"])
        self.target = draft_packet_budget.duration_character_target(request)
        profile = deps.draft_performance_profile(request)
        schedule = draft_schedule.planned_call_budget(
            len(planned_targets), structured=deps.draft_schema_batching_available(request),
            learned_batch=profile["batch"])
        self.primary_limit = schedule["primary"]
        self.reserve_limit = schedule["reserve"]
        self.predicted_calls, self.call_limit = schedule["predicted"], schedule["hardCap"]
        self.coverage_limit, self.recovery_limit = schedule["coverage"], schedule["recovery"]
        self.ending_limit = schedule["ending"]
        self.used_primary = self.used_reserve = 0
        self.calls = self.accepted = self.failed_calls = 0
        self.used_coverage = self.used_recovery = self.used_ending = 0
        self.batch_size = schedule["batch"]
        self.maximum_batch = 3 if deps.draft_schema_batching_available(request) else 1
        self.completed: list[str] = []
        self.processed: set[str] = set()
        self.finalized_incomplete: set[str] = set()
        self.attempted: set[str] = set()
        self.attempt_counts: dict[str, int] = {}
        self.ending_source = next(reversed(planned_targets))
        ordered = list(planned_targets)
        self.coverage_queue = ordered[:-1]
        self.recovery_queue: list[str] = []
        self.ending_pending = True
        self.queue_kind = "coverage"
        self.source_characters: dict[str, int] = {}
        self.partial_continuation = False
        self.stop_reason = ""
        self.evidence: list[dict] = []
        self.prior_texts: list[str] = []
        self.continuity = ["" for _ in self.chapters]
        self.source_chapters = {item.split("|", 1)[0]: index for index, items in enumerate(developments)
                                for item in items}
        self.drafted = [{"index": index, "chapter": chapter, "dialogue": {"lines": []}, "spoken": 0,
                         "discarded_duplicates": 0, "target": 0} for index, chapter in enumerate(self.chapters)]
        names = [str(item["name"]).strip() for item in characters]
        self.name_to_id = {name: str(item["id"]) for item, name in zip(characters, names) if names.count(name) == 1}
        self.name_to_id.update({alias: cast_id for cast_id, alias in aliases.items()})
        self.names_by_id = {str(item["id"]): str(item["name"]).strip() for item in characters}

    def execute(self):
        deps.update_draft_job(self.job_id, predictedCalls=self.predicted_calls, hardCallCap=self.call_limit,
                             plannedDialogueCalls=self.call_limit,
                             plannedPrimaryCalls=self.primary_limit, plannedReserveCalls=self.reserve_limit,
                             usedPrimaryCalls=0, usedReserveCalls=0,
                             initialDialogueBatchSize=1, maximumDialogueBatchSize=self.maximum_batch,
                             usedDialogueBatchSizes=[], dialogueBatchHistory=[], dialogueBatchShrinkReasons=[],
                             developmentAcceptance={}, retryInputTokens=0)
        try:
            while self.has_work() and self.calls < self.call_limit:
                deps._raise_if_draft_cancelled(lambda: deps.draft_cancel_requested(self.job_id))
                if not self.step():
                    break
            if self.has_work() and self.calls >= self.call_limit:
                self.stop_reason = "dialogue_budget_exhausted"
        finally:
            self.write_diagnostics()
        return self.drafted, self.completion_reasons()

    def completion_reasons(self):
        incomplete = any(self.pending) or bool(self.finalized_incomplete)
        # A transient empty/repeated response may be followed by a successful
        # final call. Do not expose that stale attempt result as a job warning.
        if not incomplete:
            self.stop_reason = ""
        reasons = [self.stop_reason]
        if incomplete:
            reasons.append("incomplete_developments")
        return ",".join(filter(None, reasons))

    def has_work(self):
        return bool(self.coverage_queue or self.recovery_queue or self.ending_pending)

    def select(self):
        if not hasattr(self, "coverage_queue"):
            ordered = [item.split("|", 1)[0] for items in self.pending for item in items]
            self.ending_source = ordered[-1]
            self.coverage_queue, self.recovery_queue = ordered[:-1], []
            self.ending_pending, self.queue_kind = True, "coverage"
            self.developments = self.pending
        if self.coverage_queue:
            self.queue_kind = "coverage"
            sources = self.coverage_queue[:self.batch_size]
        elif self.recovery_queue and self.accepted < max(0, self.target - self.planned_targets[self.ending_source]):
            self.queue_kind = "recovery"
            sources = [self.recovery_queue[0]]
        else:
            self.recovery_queue.clear()
            self.queue_kind = "ending"
            sources = [self.ending_source]
        selected = [item for items in self.developments for item in items
                    if item.split("|", 1)[0] in sources]
        outstanding = {source: max(80, target - self.source_characters.get(source, 0))
                       for source, target in self.planned_targets.items() if source in sources}
        duration_target = draft_packet_budget.remaining_character_target(
            self.drafted, self.request, self.accepted, self.target)
        remaining = max(80 * len(outstanding), duration_target - self.accepted)
        outstanding = deps.allocate_source_targets(list(outstanding), remaining, outstanding)
        requested = min(self.max_block, sum(outstanding.values()))
        targets = deps.allocate_source_targets(sources, requested, outstanding)
        return selected, sources, sum(targets.values()), targets

    def generate(self, selected, sources, requested, targets, chapter_index):
        from server.modules.draft_forward_job import _packet_context
        chapter, casts, aliases = _packet_context(
            self.chapters, selected, self.source_chapters, True,
            self.cast_context, self.characters, self.aliases)
        final_source = next(reversed(self.planned_targets))
        for item in chapter:
            item["final_conclusion"] = any(beat.split("|", 1)[0] == final_source for beat in item["beats"])
        continuation = bool(set(sources) & self.attempted)
        self.partial_continuation |= continuation
        message = f"第{chapter_index + 1}章・場面{sources[0].split('.')[-1]}を" + (
            "途中まで受理、続きを生成中" if continuation else "生成中")
        deps.begin_draft_llm_call(self.job_id, phase="dialogue", message=message,
            currentChunk=self.calls, dialogueAttempt=self.calls, requestedCharacters=requested,
            currentChunkTargetCharacters=requested)
        return deps.generate_draft_dialogue(
            self.request, cast_context=deps.draft_dialogue_cast_context(casts), plan=self.plan, chapter=chapter,
            chapter_index=chapter_index, requested_characters=requested,
            remaining_characters=max(0, self.target - self.accepted),
            accepted_dialogue=deps.accepted_draft_context(self.drafted),
            continuity_state=self.continuity[chapter_index], token_budget=self.token_budget,
            completion_ledger=deps.draft_completion_ledger(self.chapters, self.developments, self.pending, self.completed),
            cast_alias_by_id=aliases, debug_response_path=self.debug_directory / f"dialogue-{self.calls:02d}.txt",
            on_progress=deps.draft_stream_progress_reporter(self.job_id, self.accepted, self.aliases, self.target, message),
            should_cancel=lambda: deps.draft_cancel_requested(self.job_id), job_id=self.job_id,
            source_targets=targets, benchmark_seed=self.seed)

    def step(self):
        from server.modules.draft_forward_job import _normalize, _store_candidate
        selected, sources, requested, targets = self.select()
        chapter_index = self.source_chapters[sources[0]]
        self.calls += 1
        if self.queue_kind == "coverage":
            self.used_coverage += 1
        elif self.queue_kind == "recovery":
            self.used_recovery += 1
        else:
            self.used_ending += 1
        if self.used_primary < self.primary_limit:
            self.used_primary += 1
        else:
            self.used_reserve += 1
        raw, failure = {"lines": []}, ""
        try:
            raw, failure = self.generate(selected, sources, requested, targets, chapter_index)
        except deps.GenerationCancelled:
            self.stop_reason = "cancelled"
            raise
        except DraftContextError as error:
            failure = "draft_context_insufficient"
            raw["_error"] = str(error)
        except Exception as error:
            failure = "draft_transport_failed" if isinstance(error, deps.TransportFailure) else "dialogue_call_failures"
        sources = raw.get("_requested_sources", sources)
        self.attempted.update(sources)
        self.processed.update(sources)
        for source in sources:
            self.attempt_counts[source] = self.attempt_counts.get(source, 0) + 1
        requested = raw.get("_requested_characters", requested)
        candidate, discarded = _normalize(raw, permitted=set(self.aliases), name_to_id=self.name_to_id,
            chapter_index=chapter_index, prior_texts=self.prior_texts, limit=self.max_block)
        if raw.get("_contract_mode", "legacy") == "legacy":
            for line in candidate["lines"]:
                if not line.get("development_id"):
                    line["development_id"] = sources[0]
        positions = {source: index for index, source in enumerate(sources)}
        candidate["lines"] = [line for line in candidate["lines"] if line.get("development_id") in positions]
        sequence = [positions[line["development_id"]] for line in candidate["lines"]]
        reordered = any(a > b for a, b in zip(sequence, sequence[1:]))
        candidate["lines"].sort(key=lambda line: positions[line["development_id"]])
        completion = set(raw.get("_completed_sources", [])) | {
            line.get("development_id") for line in raw.get("lines", []) if line.get("source_complete") is True}
        owned = ({line["development_id"] for line in candidate["lines"]}
                 if deps.dialogue_has_semantic_content(candidate) else set()) | set(self.source_characters)
        completed = completion & owned & set(sources)
        exhausted = {source for source in sources if self.attempt_counts.get(source, 0) >= 2} - completed
        self.finalized_incomplete.update(exhausted)
        self.completed.extend(source for source in sources if source in completed and source not in self.completed)
        new_characters = deps.spoken_dialogue_count(candidate)
        missing = [source for source in sources if source not in completed]
        self.record(raw, sources, requested, targets, candidate, missing, failure, discarded, reordered)
        if not candidate["lines"] or not deps.dialogue_has_semantic_content(candidate):
            self.failed_calls += 1
            self.finalized_incomplete.update(source for source in sources if source not in completed)
            self._resolve_attempt(sources, completed, useful=False)
            self.stop_reason = failure or "draft_no_usable_output"
            self.publish()
            return self.has_work()
        # Completion survives rejection of repeated or malformed sibling lines.
        self.accepted += new_characters
        for line in candidate["lines"]:
            source = line["development_id"]
            self.source_characters[source] = self.source_characters.get(source, 0) + len(line["text"])
        self.prior_texts.extend(line["text"] for line in candidate["lines"])
        _store_candidate(self.drafted, candidate, self.source_chapters, chapter_index, discarded)
        order = {source: index for index, source in enumerate(self.planned_targets)}
        for item in self.drafted:
            item["dialogue"]["lines"].sort(key=lambda line: order.get(line.get("development_id"), len(order)))
            deps.resequence_draft_dialogue(item["dialogue"], item["index"])
        self.continuity[chapter_index] = "この場面で受理済みの最新発話:\n" + deps.draft_dialogue_prompt_records(
            candidate["lines"][-3:], self.aliases)
        reasons = self.evidence[-1].get("shrinkReasons", []) if self.evidence else []
        deps.record_draft_yield(
            self.request, requested=requested, accepted=new_characters,
            requested_developments=len(sources), completed_developments=len(completed),
            batch_size=len(sources), truncated="truncated_response" in reasons,
            repeated="repetition" in reasons, transport_failed=bool(failure),
            section="ending" if self.queue_kind == "ending" else ("intro" if self.calls == 1 else "body"))
        self._resolve_attempt(sources, completed, useful=True)
        self.publish()
        return self.has_work()

    def _resolve_attempt(self, sources, completed, *, useful):
        for source in sources:
            if source in self.coverage_queue:
                self.coverage_queue.remove(source)
            if source in self.recovery_queue:
                self.recovery_queue.remove(source)
            if source == self.ending_source:
                if source in completed or not useful or self.attempt_counts[source] >= 2:
                    self.ending_pending = False
                continue
            if source not in completed and useful and self.attempt_counts[source] == 1:
                self.recovery_queue.append(source)
        self.pending = [[item for item in items
                         if item.split("|", 1)[0] not in self.completed
                         and item.split("|", 1)[0] not in self.finalized_incomplete]
                        for items in self.developments]

    def record(self, raw, sources, requested, targets, candidate, missing, failure, discarded, reordered):
        from server.modules.draft_forward_job import _batch_shrink_reasons
        reasons = _batch_shrink_reasons(raw, failure or "", missing, discarded, reordered)
        healthy = raw.get("_contract_mode") == "schema" and not reasons
        self.batch_size = min(self.maximum_batch, self.batch_size + 1) if healthy else 1
        budget = self.capability.get("lastCall", {})
        evidence = {**budget, "call": self.calls, "sources": sources, "batchSize": len(sources),
                    "requested": requested, "accepted": deps.spoken_dialogue_count(candidate),
                    "sourceRequestedCharacters": targets, "pendingSources": missing,
                    "completedSources": [source for source in sources if source not in missing],
                    "mode": raw.get("_contract_mode", "legacy"), "shrinkReasons": reasons,
                    "extractedLines": len(raw.get("lines", [])), "acceptedLines": len(candidate["lines"]),
                    "manifest": raw.get("_manifest", []), "discardedLines": discarded,
                    "finishReason": raw.get("_finish_reason"), "failed": failure or "",
                    "error": raw.get("_error", ""),
                    "providerOutputTokens": raw.get("_provider_output_tokens"),
                    "budgetShrinkReasons": budget.get("shrinkReasons", [])}
        self.evidence.append(evidence)
        if raw.get("_finish_reason") == "missing_terminal_event":
            self.stop_reason = "stream_interrupted"
        with deps.DRAFT_JOBS_LOCK:
            job = deps.DRAFT_JOBS[self.job_id]
            job["usedDialogueBatchSizes"].append(len(sources))
            job["dialogueBatchHistory"].append(evidence)
            job["dialogueBatchShrinkReasons"] = list(dict.fromkeys(job["dialogueBatchShrinkReasons"] + reasons))
            job["developmentAcceptance"].update({source: "pending" if source in missing else "accepted" for source in sources})

    def publish(self):
        ending = (self.plan.get("_author_ending") or {}).get("id") or self.ending_source
        ending_completed = ending in self.completed
        story_completed = ending_completed and not self.finalized_incomplete
        deps.update_draft_job(self.job_id, completedBlocks=len(self.completed), completedDevelopments=len(self.completed),
            completedChunks=self.calls, completedChapters=sum(all(item.split("|", 1)[0] in self.completed for item in items)
                                  for items in self.developments),
            acceptedCharactersTotal=self.accepted, actualCharacters=self.accepted, failedDialogueCalls=self.failed_calls,
            usedPrimaryCalls=self.used_primary, usedReserveCalls=self.used_reserve,
            processedDevelopments=len(self.processed),
            estimatedGeneratedCharacters=None, receivedCharacters=0,
            usedCoverageCalls=self.used_coverage, usedRecoveryCalls=self.used_recovery,
            usedEndingCalls=self.used_ending, endingAttempted=self.attempt_counts.get(self.ending_source, 0) > 0,
            endingCompleted=ending_completed, storyCompleted=story_completed,
            authorEndingCompleted=ending_completed, partialContinuationUsed=self.partial_continuation)
        deps.advance_draft_progress(
            self.job_id, generated_characters=self.accepted,
            overall_progress=deps.draft_dialogue_overall_progress(self.accepted, self.target),
        )

    def write_diagnostics(self):
        deps.write_draft_debug_response(self.debug_directory / "forward-pipeline.json", json.dumps({
            "target": self.target, "targetMinutes": self.request.target_minutes,
            "plannedDialogueCalls": self.call_limit, "stopReason": self.stop_reason,
            "plannedPrimaryCalls": self.primary_limit, "plannedReserveCalls": self.reserve_limit,
            "usedPrimaryCalls": self.used_primary, "usedReserveCalls": self.used_reserve,
            "plannedContext": self.capability.get("jobContext", self.capability.get("effectiveContext")),
            "plannedDevelopments": len(self.planned_targets), "completedSources": self.completed,
            "pendingSources": self.pending, "partialContinuationUsed": self.partial_continuation,
            "developmentAttempts": self.attempt_counts,
            "finalizedIncomplete": sorted(self.finalized_incomplete),
            "authorEndingText": (self.plan.get("_author_ending") or {}).get("text", ""),
            "acceptedDialogue": [line for item in self.drafted for line in item["dialogue"].get("lines", [])],
            "calls": self.evidence,
        }, ensure_ascii=False, indent=2))
