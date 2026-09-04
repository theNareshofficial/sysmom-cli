"""
Snapshot exporters (JSON, Markdown, and formatted console summaries).
"""

import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sysmon.config import DEFAULT_CONFIG
from sysmon.dashboard import DashboardRenderer
from sysmon.monitor import SystemSnapshot, format_bytes


def snapshot_to_dict(snap: SystemSnapshot) -> dict:
    return {
        "timestamp": snap.timestamp.isoformat(),
        "system_info": {
            "hostname": snap.system_info.hostname,
            "os_name": snap.system_info.os_name,
            "os_release": snap.system_info.os_release,
            "os_version": snap.system_info.os_version,
            "architecture": snap.system_info.architecture,
            "cpu_model": snap.system_info.cpu_model,
            "physical_cores": snap.system_info.physical_cores,
            "logical_cores": snap.system_info.logical_cores,
            "uptime": snap.system_info.uptime,
            "boot_time": snap.system_info.boot_time.isoformat(),
        },
        "cpu": {
            "total_percent": snap.cpu.total_percent,
            "per_core": snap.cpu.per_core,
            "frequency_current_mhz": snap.cpu.frequency_current_mhz,
        },
        "memory": {
            "ram_total_bytes": snap.memory.ram_total,
            "ram_used_bytes": snap.memory.ram_used,
            "ram_free_bytes": snap.memory.ram_free,
            "ram_percent": snap.memory.ram_percent,
            "swap_total_bytes": snap.memory.swap_total,
            "swap_used_bytes": snap.memory.swap_used,
            "swap_percent": snap.memory.swap_percent,
        },
        "disks": [
            {
                "device": d.device,
                "mountpoint": d.mountpoint,
                "fstype": d.fstype,
                "total_bytes": d.total,
                "used_bytes": d.used,
                "free_bytes": d.free,
                "percent": d.percent,
            }
            for d in snap.disks
        ],
        "network": {
            "bytes_sent_rate": snap.network.bytes_sent_rate,
            "bytes_recv_rate": snap.network.bytes_recv_rate,
            "total_sent_bytes": snap.network.total_sent,
            "total_recv_bytes": snap.network.total_recv,
        },
        "battery": {
            "present": snap.battery.present,
            "percent": snap.battery.percent,
            "power_plugged": snap.battery.power_plugged,
            "time_left": snap.battery.time_left,
        },
        "sensors": {
            "fans": [
                {"name": f.name, "label": f.label, "current_rpm": f.current_rpm}
                for f in snap.sensors.fans
            ],
            "temperatures": [
                {
                    "name": t.name,
                    "label": t.label,
                    "current_celsius": t.current_celsius,
                }
                for t in snap.sensors.temperatures
            ],
        },
        "top_processes": [
            {
                "pid": p.pid,
                "name": p.name,
                "cpu_percent": p.cpu_percent,
                "memory_percent": p.memory_percent,
                "memory_rss_bytes": p.memory_rss,
                "status": p.status,
                "username": p.username,
                "threads": p.num_threads,
            }
            for p in snap.top_processes
        ],
    }


def snapshot_to_markdown(snap: SystemSnapshot) -> str:
    lines = [
        f"# System Health Snapshot - {snap.system_info.hostname}",
        f"**Timestamp:** {snap.timestamp.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**OS:** {snap.system_info.os_name} {snap.system_info.os_release} ({snap.system_info.architecture})  ",
        f"**Uptime:** {snap.system_info.uptime}  ",
        f"**CPU Model:** {snap.system_info.cpu_model} ({snap.system_info.physical_cores} Cores / {snap.system_info.logical_cores} Threads)  ",
        "",
        "## CPU & Memory Usage",
        f"- **Overall CPU:** {snap.cpu.total_percent:.1f}%",
        f"- **RAM Usage:** {format_bytes(snap.memory.ram_used)} / {format_bytes(snap.memory.ram_total)} ({snap.memory.ram_percent:.1f}%)",
        f"- **Swap Usage:** {format_bytes(snap.memory.swap_used)} / {format_bytes(snap.memory.swap_total)} ({snap.memory.swap_percent:.1f}%)",
        "",
        "## Hardware Sensors & Fans",
    ]

    if snap.sensors.fans:
        for fan in snap.sensors.fans:
            lines.append(f"- **Fan ({fan.label}):** {fan.current_rpm:,} RPM")
    else:
        lines.append("- **Fan Speeds:** Sensor not available or not reported by OS")

    if snap.sensors.temperatures:
        for temp in snap.sensors.temperatures:
            lines.append(f"- **Temperature ({temp.label}):** {temp.current_celsius:.1f}°C")

    lines.extend([
        "",
        "## Disk Storage",
        "| Mountpoint | Filesystem | Used | Total | Usage % |",
        "|:---|:---|:---|:---|:---|",
    ])
    for d in snap.disks:
        lines.append(
            f"| {d.mountpoint} | {d.fstype} | {format_bytes(d.used)} | {format_bytes(d.total)} | {d.percent:.1f}% |"
        )

    lines.extend([
        "",
        "## Network Activity",
        f"- **Download Rate:** {format_bytes(snap.network.bytes_recv_rate)}/s",
        f"- **Upload Rate:** {format_bytes(snap.network.bytes_sent_rate)}/s",
        f"- **Total Received:** {format_bytes(snap.network.total_recv)}",
        f"- **Total Sent:** {format_bytes(snap.network.total_sent)}",
        "",
        "## Top Processes",
        "| PID | Name | User | CPU % | RAM % | Memory RSS | Threads |",
        "|:---|:---|:---|:---|:---|:---|:---|",
    ])
    for p in snap.top_processes:
        lines.append(
            f"| {p.pid} | {p.name} | {p.username or '-'} | {p.cpu_percent:.1f}% | {p.memory_percent:.1f}% | {format_bytes(p.memory_rss)} | {p.num_threads} |"
        )

    return "\n".join(lines)


def print_console_snapshot(snap: SystemSnapshot) -> None:
    console = Console()
    renderer = DashboardRenderer(DEFAULT_CONFIG)

    console.print(renderer.make_header(snap))
    console.print(renderer.make_cpu_panel(snap))
    console.print(renderer.make_memory_panel(snap))
    console.print(renderer.make_sensors_panel(snap))
    console.print(renderer.make_storage_panel(snap))
    console.print(renderer.make_network_panel(snap))
    console.print(renderer.make_process_table(snap))
