"""
Diff 引擎单元测试
"""
import pytest
from drift_detector.models import Snapshot, SnapshotSource, ChangeType, Severity
from drift_detector.differ.engine import DiffEngine, diff_dicts


class TestDiffDicts:
    def test_no_changes(self):
        baseline = {"a": "string", "b": "integer"}
        current = {"a": "string", "b": "integer"}
        diffs = diff_dicts(baseline, current)
        assert diffs == []

    def test_field_added(self):
        baseline = {"a": "string"}
        current = {"a": "string", "b": "integer"}
        diffs = diff_dicts(baseline, current)
        assert len(diffs) == 1
        assert diffs[0].change_type == ChangeType.ADDED
        assert diffs[0].severity == Severity.NON_BREAKING

    def test_field_removed(self):
        baseline = {"a": "string", "b": "integer"}
        current = {"a": "string"}
        diffs = diff_dicts(baseline, current)
        assert len(diffs) == 1
        assert diffs[0].change_type == ChangeType.REMOVED
        assert diffs[0].severity == Severity.BREAKING

    def test_value_changed(self):
        baseline = {"type": "object"}
        current = {"type": "array"}
        diffs = diff_dicts(baseline, current)
        assert len(diffs) == 1
        assert diffs[0].change_type == ChangeType.MODIFIED
        assert diffs[0].before == "object"
        assert diffs[0].after == "array"


class TestDiffEngine:
    def _make_api_snapshot(self, vendor: str, endpoint: str, structure: dict) -> Snapshot:
        return Snapshot(
            vendor=vendor,
            endpoint=endpoint,
            source=SnapshotSource.API,
            captured_at="2026-04-01T00:00:00Z",
            response_structure=structure,
        )

    def test_no_changes(self):
        engine = DiffEngine()
        s1 = self._make_api_snapshot("openai", "chat_completions", {"id": "string", "choices": [{"message": {"content": "string"}}]})
        s2 = self._make_api_snapshot("openai", "chat_completions", {"id": "string", "choices": [{"message": {"content": "string"}}]})
        report = engine.compare(s1, s2)
        assert not report.has_changes

    def test_new_field_detected(self):
        engine = DiffEngine()
        s1 = self._make_api_snapshot("openai", "chat_completions", {"id": "string"})
        s2 = self._make_api_snapshot("openai", "chat_completions", {"id": "string", "new_field": "string"})
        report = engine.compare(s1, s2)
        assert report.has_changes
        assert report.breaking_count == 0
        assert any(d.change_type == ChangeType.ADDED for d in report.diffs)

    def test_breaking_field_removed(self):
        engine = DiffEngine()
        s1 = self._make_api_snapshot("openai", "chat_completions", {
            "id": "string",
            "choices": [{"message": {"content": "string", "role": "string"}}]
        })
        s2 = self._make_api_snapshot("openai", "chat_completions", {
            "id": "string",
            "choices": [{"message": {"content": "string"}}]
        })
        report = engine.compare(s1, s2)
        assert report.has_changes
        assert report.breaking_count > 0

    def test_summary_format(self):
        engine = DiffEngine()
        s1 = self._make_api_snapshot("openai", "chat_completions", {"a": "string"})
        s2 = self._make_api_snapshot("openai", "chat_completions", {"a": "string", "b": "integer"})
        report = engine.compare(s1, s2)
        assert "openai/chat_completions" in report.summary
        assert "added" in report.summary
