"""Snapshotter 抽象基类"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from drift_detector.config import VendorConfig, AppConfig
from drift_detector.models import Snapshot, SnapshotSource


class BaseSnapshotter(ABC):
    def __init__(self, config: AppConfig):
        self.config = config

    @abstractmethod
    def capture(self, vendor: str, endpoint_name: str) -> Snapshot:
        """采集一个快照"""
        ...

    def snapshot_path(self, vendor: str, endpoint_name: str, source: SnapshotSource, timestamp: str) -> Path:
        """生成快照文件路径"""
        date = timestamp[:10]  # 取 YYYY-MM-DD
        filename = f"{endpoint_name}_{source.value}_{timestamp.replace(':', '-')}.json"
        return self.config.snapshots_dir / vendor / date / filename

    def latest_snapshot_path(self, vendor: str, endpoint_name: str, source: SnapshotSource) -> Path:
        """最新快照的符号路径（latest.json）"""
        return self.config.snapshots_dir / vendor / f"{endpoint_name}_{source.value}_latest.json"

    def find_snapshots(
        self, vendor: str, endpoint_name: str, source: SnapshotSource
    ) -> list[Path]:
        """按时间顺序返回所有历史快照路径"""
        vendor_dir = self.config.snapshots_dir / vendor
        if not vendor_dir.exists():
            return []
        pattern = f"**/{endpoint_name}_{source.value}_*.json"
        # 排除 latest.json
        paths = sorted(
            [p for p in vendor_dir.glob(pattern) if "latest" not in p.name],
            key=lambda p: p.stem,
        )
        return paths

    def save_snapshot(self, snapshot: Snapshot) -> Path:
        """保存快照到磁盘，同时更新 latest.json"""
        ts_path = self.snapshot_path(snapshot.vendor, snapshot.endpoint, snapshot.source, snapshot.captured_at)
        snapshot.save(ts_path)

        # 更新 latest
        latest_path = self.latest_snapshot_path(snapshot.vendor, snapshot.endpoint, snapshot.source)
        snapshot.save(latest_path)

        return ts_path

    def load_latest(self, vendor: str, endpoint_name: str, source: SnapshotSource) -> Snapshot | None:
        """加载最新快照"""
        p = self.latest_snapshot_path(vendor, endpoint_name, source)
        if not p.exists():
            return None
        return Snapshot.load(p)

    def load_previous(self, vendor: str, endpoint_name: str, source: SnapshotSource) -> Snapshot | None:
        """加载倒数第二个快照（基准）"""
        paths = self.find_snapshots(vendor, endpoint_name, source)
        if len(paths) < 2:
            return None
        return Snapshot.load(paths[-2])
