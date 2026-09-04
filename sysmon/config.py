"""
Configuration and settings for SysMon CLI.
"""

from dataclasses import dataclass, field


@dataclass
class Thresholds:
    cpu_warn: float = 75.0
    cpu_crit: float = 90.0
    ram_warn: float = 80.0
    ram_crit: float = 92.0
    disk_warn: float = 85.0
    disk_crit: float = 95.0
    temp_warn: float = 75.0
    temp_crit: float = 88.0
    fan_rpm_high: int = 4500


@dataclass
class Config:
    refresh_rate: float = 1.0
    process_limit: int = 8
    sort_by: str = "cpu"  # 'cpu' or 'memory'
    thresholds: Thresholds = field(default_factory=Thresholds)


DEFAULT_CONFIG = Config()
