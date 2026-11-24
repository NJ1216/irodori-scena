"""Shared boundary for the public portion of a job."""
from __future__ import annotations

from typing import Any
from copy import deepcopy


class PublicJob(dict):
    """Detached JSON mapping; ordering metadata never enters public JSON."""
    def __init__(self, values: dict[str, Any], version: int):
        super().__init__(values)
        self.version = version


def public_job(job: dict[str, Any], hidden: set[str]) -> dict[str, Any]:
    # Call only under the feature's job lock, including GET/reconnect snapshots.
    version = int(job.get("_progressVersion", 0)) + 1
    job["_progressVersion"] = version
    values = {key: value for key, value in job.items() if key not in hidden and key != "_progressVersion"}
    return PublicJob(deepcopy(values), version)
