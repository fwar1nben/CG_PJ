"""Local retrieval memory tools for prior SVG icon runs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    source_path: str
    prompt: str
    summary: str
    success_patterns: tuple[str, ...] = ()
    failure_patterns: tuple[str, ...] = ()
    user_feedback: tuple[str, ...] = ()
    score: int | None = None
    tags: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_path": self.source_path,
            "prompt": self.prompt,
            "summary": self.summary,
            "success_patterns": list(self.success_patterns),
            "failure_patterns": list(self.failure_patterns),
            "user_feedback": list(self.user_feedback),
            "score": self.score,
            "tags": list(self.tags),
        }

    @property
    def search_text(self) -> str:
        parts = [
            self.prompt,
            self.summary,
            " ".join(self.success_patterns),
            " ".join(self.failure_patterns),
            " ".join(self.user_feedback),
            " ".join(self.tags),
        ]
        return " ".join(part for part in parts if part)


@dataclass(frozen=True)
class RetrievedMemory:
    record: MemoryRecord
    score: float

    def to_json(self) -> dict[str, Any]:
        data = self.record.to_json()
        data["retrieval_score"] = round(self.score, 4)
        return data


@dataclass(frozen=True)
class MemoryContext:
    enabled: bool
    top_k: int
    query: str
    records: tuple[RetrievedMemory, ...] = field(default_factory=tuple)

    @property
    def record_ids(self) -> list[str]:
        return [item.record.id for item in self.records]

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "top_k": self.top_k,
            "query": self.query,
            "records": [item.to_json() for item in self.records],
        }


class MemoryRetrievalTool:
    """Indexes local run summaries and retrieves similar memories; it is not an Agent."""

    def __init__(self, index_path: str | Path = Path("outputs/memory/memory_index.jsonl")) -> None:
        self.index_path = Path(index_path)

    def rebuild_from_outputs(self, outputs_root: str | Path = Path("outputs")) -> list[MemoryRecord]:
        root = Path(outputs_root)
        records: list[MemoryRecord] = []
        if root.exists():
            for plan_path in sorted(root.rglob("plans.json")):
                if "memory" in plan_path.parts:
                    continue
                record = _record_from_run_dir(plan_path.parent, root)
                if record is not None:
                    records.append(record)
        self.write_records(records)
        return records

    def write_records(self, records: list[MemoryRecord]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            "".join(json.dumps(record.to_json(), ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )

    def append_record(self, record: MemoryRecord) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {item.id: item for item in self.load_records()}
        existing[record.id] = record
        self.write_records(list(existing.values()))

    def load_records(self) -> list[MemoryRecord]:
        if not self.index_path.exists():
            return []
        records: list[MemoryRecord] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                records.append(_record_from_json(data))
        return records

    def retrieve(self, query: str, *, top_k: int = 3) -> MemoryContext:
        query_tokens = _tokens(query)
        records = self.load_records()
        if not query_tokens or top_k <= 0 or not records:
            return MemoryContext(enabled=True, top_k=max(0, top_k), query=query, records=())

        document_tokens = [_tokens(record.search_text) for record in records]
        document_count = len(document_tokens)
        document_frequency: dict[str, int] = {}
        for tokens in document_tokens:
            for token in set(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1

        scored: list[RetrievedMemory] = []
        for record, tokens in zip(records, document_tokens):
            score = _bm25_score(query_tokens, tokens, document_frequency, document_count)
            if score > 0:
                scored.append(RetrievedMemory(record=record, score=score))
        scored.sort(key=lambda item: item.score, reverse=True)
        return MemoryContext(enabled=True, top_k=top_k, query=query, records=tuple(scored[:top_k]))


def record_from_curated_json(
    *,
    run_dir: Path,
    prompt: str,
    data: dict[str, Any],
    fallback_score: int | None = None,
) -> MemoryRecord:
    record_id = _stable_id(str(run_dir), prompt, str(data.get("summary") or ""))
    return MemoryRecord(
        id=record_id,
        source_path=str(run_dir),
        prompt=prompt,
        summary=_text(data.get("summary"), fallback=f"Prior SVG icon run for: {prompt}"),
        success_patterns=_tuple_text(data.get("success_patterns")),
        failure_patterns=_tuple_text(data.get("failure_patterns")),
        user_feedback=_tuple_text(data.get("user_feedback")),
        score=_int_or_none(data.get("score"), fallback=fallback_score),
        tags=_tuple_text(data.get("tags")),
    )


def _record_from_run_dir(run_dir: Path, outputs_root: Path) -> MemoryRecord | None:
    plans = _read_json(run_dir / "plans.json")
    if not isinstance(plans, list) or not plans or not isinstance(plans[0], dict):
        return None
    plan = plans[0]
    trace_rows = _read_json(run_dir / "llm_trace.json")
    trace = trace_rows[0] if isinstance(trace_rows, list) and trace_rows and isinstance(trace_rows[0], dict) else {}
    metrics = _read_json(run_dir / "metrics.json")
    history = _read_json(run_dir / "refinement_history.json")

    prompt = _text(plan.get("prompt"), fallback=_text(trace.get("rewritten_prompt"), fallback=""))
    if not prompt:
        return None
    refined_score = _int_or_none(trace.get("refined_score"))
    if refined_score is None and isinstance(metrics, dict):
        refined_score = _int_or_none(metrics.get("refined_average_score"))
    user_feedback = _feedback_from_trace(trace)
    errors = tuple(str(error) for error in trace.get("errors") or () if isinstance(error, str))
    repair_notes = _repair_notes(history)
    selector = _text(trace.get("selector_rationale"), fallback="")
    summary_parts = [
        f"Prompt: {prompt}",
        f"Layout: {_text(plan.get('layout'), fallback='unknown')}",
        f"Selector: {selector}" if selector else "",
        f"Score: {refined_score}" if refined_score is not None else "",
    ]
    source_path = str(run_dir.relative_to(outputs_root)) if _is_relative_to(run_dir, outputs_root) else str(run_dir)
    return MemoryRecord(
        id=_stable_id(str(run_dir), prompt),
        source_path=source_path,
        prompt=prompt,
        summary=". ".join(part for part in summary_parts if part),
        success_patterns=_tuple_text(
            [
                trace.get("selector_rationale"),
                trace.get("selector_repair_brief"),
                trace.get("post_run_optimizer_feedback"),
            ]
        ),
        failure_patterns=errors + repair_notes,
        user_feedback=user_feedback,
        score=refined_score,
        tags=_tuple_text([plan.get("category"), plan.get("style"), *(plan.get("motifs") or [])]),
    )


def _record_from_json(data: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        id=_text(data.get("id"), fallback=_stable_id(str(data))),
        source_path=_text(data.get("source_path"), fallback=""),
        prompt=_text(data.get("prompt"), fallback=""),
        summary=_text(data.get("summary"), fallback=""),
        success_patterns=_tuple_text(data.get("success_patterns")),
        failure_patterns=_tuple_text(data.get("failure_patterns")),
        user_feedback=_tuple_text(data.get("user_feedback")),
        score=_int_or_none(data.get("score")),
        tags=_tuple_text(data.get("tags")),
    )


def _bm25_score(
    query_tokens: list[str],
    document_tokens: list[str],
    document_frequency: dict[str, int],
    document_count: int,
) -> float:
    counts: dict[str, int] = {}
    for token in document_tokens:
        counts[token] = counts.get(token, 0) + 1
    score = 0.0
    length = max(1, len(document_tokens))
    avg_length = max(1.0, sum(document_frequency.values()) / max(1, document_count))
    k1 = 1.2
    b = 0.75
    for token in query_tokens:
        tf = counts.get(token, 0)
        if tf == 0:
            continue
        df = document_frequency.get(token, 0)
        idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * length / avg_length))
    return score


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"mem-{digest}"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _feedback_from_trace(trace: dict[str, Any]) -> tuple[str, ...]:
    return _tuple_text(
        [
            trace.get("manual_optimizer_feedback"),
            trace.get("post_run_optimizer_feedback"),
        ]
    )


def _repair_notes(history: Any) -> tuple[str, ...]:
    if not isinstance(history, list):
        return ()
    notes = []
    for item in history:
        if not isinstance(item, dict):
            continue
        for report_key in ("baseline_report", "refined_report"):
            report = item.get(report_key)
            if not isinstance(report, dict):
                continue
            for issue in report.get("issues") or ():
                if isinstance(issue, dict) and isinstance(issue.get("message"), str):
                    notes.append(issue["message"])
    return tuple(notes[:8])


def _tuple_text(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    cleaned = []
    for item in value:
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip())
    return tuple(cleaned)


def _text(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _int_or_none(value: Any, *, fallback: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
