"""
Command-line interface (CLI) entry point for SysMon.
"""

import json
from pathlib import Path
import sys
from typing import Annotated, Optional


if sys.platform == "win32":
    try:
        if sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.table import Table

from sysmon import __version__
from sysmon.config import Config, DEFAULT_CONFIG
from sysmon.dashboard import run_live_dashboard
from sysmon.exporter import print_console_snapshot, snapshot_to_dict, snapshot_to_markdown
from sysmon.monitor import SystemMonitor, format_bytes

app = typer.Typer(
    name="sysmon",
    help="SysMon CLI: Real-Time System Monitoring & Resource Dashboard",
    add_completion=False,
)
console = Console()


def launch_dashboard(refresh: float = 1.0, limit: int = 8, sort_by: str = "cpu") -> None:
    """Internal helper to start the live dashboard."""
    refresh_val = float(refresh) if not isinstance(refresh, (int, float)) else refresh
    limit_val = int(limit) if not isinstance(limit, int) else limit
    sort_val = str(sort_by)

    cfg = Config(refresh_rate=refresh_val, process_limit=limit_val, sort_by=sort_val)
    monitor = SystemMonitor()
    run_live_dashboard(monitor, cfg)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-v", help="Show version and exit.", is_eager=True),
    ] = None,
):
    if version:
        console.print(f"[bold cyan]SysMon CLI[/bold cyan] version [green]{__version__}[/green]")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        launch_dashboard()


@app.command()
def dashboard(
    refresh: Annotated[float, typer.Option("--refresh", "-r", help="Refresh rate in seconds.")] = 1.0,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of processes to display.")] = 8,
    sort_by: Annotated[str, typer.Option("--sort-by", "-s", help="Sort processes by 'cpu' or 'memory'.")] = "cpu",
):
    """Launch the interactive live terminal dashboard."""
    launch_dashboard(refresh=refresh, limit=limit, sort_by=sort_by)


@app.command()
def snapshot(
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of processes to display.")] = 8,
    sort_by: Annotated[str, typer.Option("--sort-by", "-s", help="Sort processes by 'cpu' or 'memory'.")] = "cpu",
):
    monitor = SystemMonitor()
    snap = monitor.get_snapshot(process_limit=limit, sort_by=sort_by)
    print_console_snapshot(snap)


@app.command()
def top(
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of processes to list.")] = 15,
    sort_by: Annotated[str, typer.Option("--sort-by", "-s", help="Sort by 'cpu' or 'memory'.")] = "cpu",
):

    monitor = SystemMonitor()
    processes = monitor.get_top_processes(limit=limit, sort_by=sort_by)

    table = Table(title=f"Top Processes (Sorted by {sort_by.upper()})", header_style="bold cyan")
    table.add_column("PID", justify="right", style="dim")
    table.add_column("Name", style="bold white")
    table.add_column("User", style="dim")
    table.add_column("Status")
    table.add_column("CPU %", justify="right", style="bold red")
    table.add_column("RAM %", justify="right", style="bold green")
    table.add_column("Memory RSS", justify="right")
    table.add_column("Threads", justify="right", style="dim")

    for p in processes:
        table.add_row(
            str(p.pid),
            p.name,
            p.username or "-",
            p.status,
            f"{p.cpu_percent:.1f}%",
            f"{p.memory_percent:.1f}%",
            format_bytes(p.memory_rss),
            str(p.num_threads),
        )

    console.print(table)


@app.command()
def disk():
    """Display detailed disk storage and partition information."""
    monitor = SystemMonitor()
    disks = monitor.get_disk_metrics()
    io = monitor.get_disk_io_metrics()

    table = Table(title="Disk Storage Metrics", header_style="bold magenta")
    table.add_column("Device", style="dim")
    table.add_column("Mountpoint", style="bold white")
    table.add_column("Filesystem")
    table.add_column("Total", justify="right")
    table.add_column("Used", justify="right")
    table.add_column("Free", justify="right")
    table.add_column("Usage %", justify="right", style="bold yellow")

    for d in disks:
        table.add_row(
            d.device,
            d.mountpoint,
            d.fstype,
            format_bytes(d.total),
            format_bytes(d.used),
            format_bytes(d.free),
            f"{d.percent:.1f}%",
        )

    console.print(table)
    console.print(
        f"[dim]Disk I/O:[/dim] Read [cyan]{format_bytes(io.read_bytes_rate)}/s[/cyan] | Write [magenta]{format_bytes(io.write_bytes_rate)}/s[/magenta]"
    )


@app.command()
def net():
    """Display network interfaces, IP addresses, and throughput."""
    monitor = SystemMonitor()
    net_metrics = monitor.get_network_metrics()

    table = Table(title="Network Interfaces & Traffic", header_style="bold blue")
    table.add_column("Interface", style="bold white")
    table.add_column("Status")
    table.add_column("IP Addresses", style="yellow")
    table.add_column("Speed (Mbps)", justify="right")

    for iface in net_metrics.interfaces:
        status_text = "[green]UP[/green]" if iface.is_up else "[red]DOWN[/red]"
        table.add_row(
            iface.name,
            status_text,
            ", ".join(iface.ip_addresses) if iface.ip_addresses else "-",
            str(iface.speed_mbps) if iface.speed_mbps else "-",
        )

    console.print(table)
    console.print(
        f"[bold]Total Download:[/bold] [green]{format_bytes(net_metrics.total_recv)}[/green] | [bold]Total Upload:[/bold] [cyan]{format_bytes(net_metrics.total_sent)}[/cyan]"
    )


@app.command()
def sensors():
    """Display hardware sensors: Fan Speeds (RPM) and Temperatures."""
    monitor = SystemMonitor()
    s = monitor.get_sensors_metrics()

    table = Table(title="Hardware Sensors (Fan RPM & Temperatures)", header_style="bold yellow")
    table.add_column("Sensor Type", style="bold white")
    table.add_column("Label / Device")
    table.add_column("Current Reading", justify="right", style="bold cyan")
    table.add_column("Threshold / Notes", style="dim")

    has_entries = False

    for fan in s.fans:
        has_entries = True
        table.add_row("Fan", fan.label, f"{fan.current_rpm:,} RPM", "Fan Speed")

    for temp in s.temperatures:
        has_entries = True
        crit_str = f"High: {temp.high_celsius}°C" if temp.high_celsius else "-"
        table.add_row("Temperature", temp.label, f"{temp.current_celsius:.1f}°C", crit_str)

    if not has_entries:
        console.print("[yellow]No hardware fan or temperature sensors detected on this system/OS.[/yellow]")
    else:
        console.print(table)


@app.command()
def export(
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="File path to save the report.")] = None,
    format: Annotated[str, typer.Option("--format", "-f", help="Output format: 'json' or 'md' (markdown).")] = "json",
):
    """Export a system health snapshot to a JSON or Markdown file."""
    monitor = SystemMonitor()
    snap = monitor.get_snapshot()

    if format.lower() == "md" or format.lower() == "markdown":
        content = snapshot_to_markdown(snap)
        default_file = "sysmon_report.md"
    else:
        content = json.dumps(snapshot_to_dict(snap), indent=2)
        default_file = "sysmon_report.json"

    target_path = output or Path(default_file)
    target_path.write_text(content, encoding="utf-8")
    console.print(f"[bold green]OK[/bold green] System report exported successfully to [cyan]{target_path.resolve()}[/cyan]")


if __name__ == "__main__":
    app()
