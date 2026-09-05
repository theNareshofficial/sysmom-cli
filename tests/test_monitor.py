"""
Unit tests for SysMon CLI metric collectors, exporters, and CLI commands.
"""

import json
import pytest
from typer.testing import CliRunner

from sysmon.cli import app
from sysmon.exporter import snapshot_to_dict, snapshot_to_markdown
from sysmon.monitor import (
    FanSensor,
    HardwareSensors,
    SystemMonitor,
    format_bytes,
    format_duration,
)


def test_format_bytes():
    assert format_bytes(500) == "500.0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024 * 1.5) == "1.5 MB"
    assert format_bytes(1024 * 1024 * 1024 * 4) == "4.0 GB"


def test_format_duration():
    assert "00m 45s" in format_duration(45)
    assert "01h 01m" in format_duration(3660)
    assert "1d" in format_duration(90000)


def test_system_info_collection():
    monitor = SystemMonitor()
    info = monitor.get_system_info()

    assert info.hostname
    assert info.os_name
    assert info.physical_cores >= 1
    assert info.logical_cores >= 1
    assert info.uptime


def test_cpu_metrics_collection():
    monitor = SystemMonitor()
    cpu = monitor.get_cpu_metrics()

    assert 0.0 <= cpu.total_percent <= 100.0
    assert len(cpu.per_core) == monitor.get_system_info().logical_cores
    for core_pct in cpu.per_core:
        assert 0.0 <= core_pct <= 100.0


def test_memory_metrics_collection():
    monitor = SystemMonitor()
    mem = monitor.get_memory_metrics()

    assert mem.ram_total > 0
    assert mem.ram_used >= 0
    assert 0.0 <= mem.ram_percent <= 100.0
    assert mem.swap_total >= 0


def test_disk_metrics_collection():
    monitor = SystemMonitor()
    disks = monitor.get_disk_metrics()

    assert isinstance(disks, list)
    if disks:
        d = disks[0]
        assert d.mountpoint
        assert d.total > 0
        assert 0.0 <= d.percent <= 100.0


def test_network_metrics_collection():
    monitor = SystemMonitor()
    net = monitor.get_network_metrics()

    assert net.bytes_recv_rate >= 0.0
    assert net.bytes_sent_rate >= 0.0
    assert net.total_recv >= 0
    assert net.total_sent >= 0


def test_sensors_and_fans_metrics():
    monitor = SystemMonitor()
    sensors = monitor.get_sensors_metrics()

    assert isinstance(sensors.fans, list)
    assert isinstance(sensors.temperatures, list)

    # Validate FanSensor model
    sample_fan = FanSensor(name="cpu_fan", label="CPU Fan", current_rpm=2400)
    assert sample_fan.current_rpm == 2400
    assert sample_fan.label == "CPU Fan"


def test_top_processes():
    monitor = SystemMonitor()
    procs = monitor.get_top_processes(limit=5, sort_by="cpu")

    assert len(procs) <= 5
    for p in procs:
        assert p.pid >= 0
        assert p.name


def test_snapshot_and_exporters():
    monitor = SystemMonitor()
    snap = monitor.get_snapshot(process_limit=3)

    d = snapshot_to_dict(snap)
    assert "timestamp" in d
    assert "cpu" in d
    assert "memory" in d
    assert "sensors" in d
    assert "top_processes" in d
    
    json_str = json.dumps(d)
    assert json_str

    
    md = snapshot_to_markdown(snap)
    assert "# System Health Snapshot" in md
    assert "RAM Usage" in md
    assert "Hardware Sensors & Fans" in md


def test_cli_subcommands():
    runner = CliRunner()

    # Test snapshot command
    result = runner.invoke(app, ["snapshot", "--limit", "2"])
    assert result.exit_code == 0
    assert "CPU Utilization" in result.output

    # Test top command
    result = runner.invoke(app, ["top", "--limit", "2"])
    assert result.exit_code == 0
    assert "PID" in result.output

    # Test disk command
    result = runner.invoke(app, ["disk"])
    assert result.exit_code == 0
    assert "Disk Storage Metrics" in result.output

    # Test net command
    result = runner.invoke(app, ["net"])
    assert result.exit_code == 0
    assert "Network Interfaces & Traffic" in result.output

    # Test sensors command
    result = runner.invoke(app, ["sensors"])
    assert result.exit_code == 0

    # Test export json command
    result = runner.invoke(app, ["export", "--format", "json", "--output", "test_report.json"])
    assert result.exit_code == 0
    assert "System report exported" in result.output
