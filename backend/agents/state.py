"""
Shared state object passed between agents.

Phase 1 keeps this in-memory (per scan_id, held in a dict in main.py).
Phase 2/3 will persist this to PostgreSQL - the shape stays the same,
which is why it's a plain dataclass/dict rather than something ORM-bound.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentLogEntry:
    agent: str
    task: str
    status: str  # "running" | "success" | "warning" | "failed"
    timestamp: str = field(default_factory=now_iso)
    detail: str = ""


@dataclass
class ScanState:
    scan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    website_url: str = ""
    max_pages: int = 10
    max_depth: int = 2
    device: str = "desktop"  # desktop | mobile | tablet

    scan_status: str = "queued"  # queued|running|completed|failed
    current_agent: str = ""
    error: str | None = None

    pages: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[dict[str, Any]] = field(default_factory=list)
    console_errors: list[dict[str, Any]] = field(default_factory=list)
    network_errors: list[dict[str, Any]] = field(default_factory=list)

    functional_tests: list[dict[str, Any]] = field(default_factory=list)
    accessibility_findings: list[dict[str, Any]] = field(default_factory=list)
    visual_findings: list[dict[str, Any]] = field(default_factory=list)
    performance_metrics: list[dict[str, Any]] = field(default_factory=list)
    security_findings: list[dict[str, Any]] = field(default_factory=list)

    bugs: list[dict[str, Any]] = field(default_factory=list)
    quality_score: dict[str, Any] | None = None

    agent_log: list[dict[str, Any]] = field(default_factory=list)

    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None

    def log(self, agent: str, task: str, status: str, detail: str = ""):
        entry = AgentLogEntry(agent=agent, task=task, status=status, detail=detail)
        self.agent_log.append(entry.__dict__)
        self.current_agent = agent
        status_tags = {"running": "[RUNNING]", "success": "[SUCCESS]", "warning": "[WARNING]", "failed": "[FAILED]"}
        tag = status_tags.get(status, f"[{status.upper()}]")
        detail_str = f" - {detail}" if detail else ""
        msg = f"[{entry.timestamp}] {tag} [{agent}] {task}{detail_str}"
        try:
            print(msg, flush=True)
        except Exception:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "website_url": self.website_url,
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "device": self.device,
            "scan_status": self.scan_status,
            "current_agent": self.current_agent,
            "error": self.error,
            "pages": self.pages,
            "screenshots": self.screenshots,
            "console_errors": self.console_errors,
            "network_errors": self.network_errors,
            "functional_tests": self.functional_tests,
            "accessibility_findings": self.accessibility_findings,
            "visual_findings": self.visual_findings,
            "performance_metrics": self.performance_metrics,
            "security_findings": self.security_findings,
            "bugs": self.bugs,
            "quality_score": self.quality_score,
            "agent_log": self.agent_log,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
