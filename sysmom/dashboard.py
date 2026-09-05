"""
Interactive Rich Terminal User Interface (TUI) Dashboard for SysMom.
"""

import sys
import time

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress_bar import ProgressBar
from rich.live import Live

from sysmom.config import Config, DEFAULT_CONFIG
from sysmom.monitor import SystemMonitor, SystemSnapshot, format_bytes


def get_threshold_style(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return "bold red"
    elif value >= warn:
        return "bold yellow"
    return "bold green"


class DashboardRenderer:

    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config

    def make_header(self, snap: SystemSnapshot) -> Panel:
        info = snap.system_info
        header_table = Table.grid(expand=True)
        header_table.add_column(ratio=2)
        header_table.add_column(ratio=1, justify="right")

        left_text = Text()
        left_text.append("[*] ", style="bold yellow")
        left_text.append(f"{info.hostname}", style="bold cyan")
        left_text.append(" | ", style="dim")
        left_text.append(f"{info.os_name} {info.os_release}", style="white")
        left_text.append(" | ", style="dim")
        left_text.append(f"{info.cpu_model} ({info.physical_cores}C/{info.logical_cores}T)", style="magenta")

        right_text = Text()
        right_text.append("Uptime: ", style="dim")
        right_text.append(f"{info.uptime}", style="bold green")

        if snap.battery.present:
            right_text.append(" | ", style="dim")
            bat_style = "bold green" if (snap.battery.percent or 0) > 20 else "bold red"
            plug_sym = "[AC] " if snap.battery.power_plugged else "[BAT] "
            right_text.append(f"{plug_sym}{snap.battery.percent:.0f}%", style=bat_style)

        header_table.add_row(left_text, right_text)
        return Panel(header_table, style="blue", padding=(0, 1))

    def make_cpu_panel(self, snap: SystemSnapshot) -> Panel:
        cpu = snap.cpu
        style = get_threshold_style(
            cpu.total_percent,
            self.config.thresholds.cpu_warn,
            self.config.thresholds.cpu_crit,
        )

        table = Table(expand=True, show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", ratio=1)
        table.add_column("Bar", ratio=3)
        table.add_column("Value", ratio=1, justify="right")

        # Total CPU
        bar = ProgressBar(total=100, completed=cpu.total_percent, width=None, style="grey37", complete_style=style)
        freq_str = f" @ {cpu.frequency_current_mhz:.0f}MHz" if cpu.frequency_current_mhz else ""
        table.add_row(
            Text("CPU Total", style="bold white"),
            bar,
            Text(f"{cpu.total_percent:5.1f}%{freq_str}", style=style),
        )

        # Per core meters (up to 8 displayed cleanly)
        cores_to_show = cpu.per_core[:8]
        for i, core_pct in enumerate(cores_to_show):
            c_style = get_threshold_style(core_pct, 80.0, 95.0)
            c_bar = ProgressBar(total=100, completed=core_pct, width=None, style="grey23", complete_style=c_style)
            table.add_row(
                Text(f" Core {i:02d}", style="dim"),
                c_bar,
                Text(f"{core_pct:5.1f}%", style=c_style),
            )

        if len(cpu.per_core) > 8:
            table.add_row(
                Text(f" +{len(cpu.per_core) - 8} more cores", style="dim italic"),
                Text(""),
                Text(""),
            )

        return Panel(table, title="[bold cyan]CPU Utilization[/bold cyan]", border_style="cyan")

    def make_memory_panel(self, snap: SystemSnapshot) -> Panel:
        mem = snap.memory
        ram_style = get_threshold_style(
            mem.ram_percent,
            self.config.thresholds.ram_warn,
            self.config.thresholds.ram_crit,
        )

        table = Table(expand=True, show_header=False, box=None, padding=(0, 1))
        table.add_column("Type", ratio=1)
        table.add_column("Bar", ratio=3)
        table.add_column("Stats", ratio=2, justify="right")

        # RAM
        ram_bar = ProgressBar(total=100, completed=mem.ram_percent, width=None, style="grey37", complete_style=ram_style)
        ram_stats = f"{format_bytes(mem.ram_used)} / {format_bytes(mem.ram_total)} ({mem.ram_percent:.1f}%)"
        table.add_row(Text("RAM", style="bold white"), ram_bar, Text(ram_stats, style=ram_style))

        # Swap
        swap_style = get_threshold_style(mem.swap_percent, 75.0, 90.0)
        swap_bar = ProgressBar(total=100, completed=mem.swap_percent, width=None, style="grey23", complete_style=swap_style)
        swap_stats = f"{format_bytes(mem.swap_used)} / {format_bytes(mem.swap_total)} ({mem.swap_percent:.1f}%)"
        table.add_row(Text("Swap", style="dim"), swap_bar, Text(swap_stats, style=swap_style))

        return Panel(table, title="[bold green]Memory & Swap[/bold green]", border_style="green")

    def make_sensors_panel(self, snap: SystemSnapshot) -> Panel:
        sensors = snap.sensors
        table = Table(expand=True, show_header=True, box=None, padding=(0, 1))
        table.add_column("Sensor", style="bold white")
        table.add_column("Reading", justify="right")

        has_data = False

        # Fan Speeds (RPM or %)
        if sensors.fans:
            has_data = True
            for fan in sensors.fans:
                unit = getattr(fan, "unit", "RPM")
                rpm_style = "bold red" if fan.current_rpm >= self.config.thresholds.fan_rpm_high else "bold green"
                table.add_row(
                    f"Fan ({fan.label})",
                    Text(f"{fan.current_rpm:,} {unit}", style=rpm_style),
                )

        # Temperatures
        if sensors.temperatures:
            has_data = True
            for temp in sensors.temperatures[:4]:
                t_style = get_threshold_style(
                    temp.current_celsius,
                    self.config.thresholds.temp_warn,
                    self.config.thresholds.temp_crit,
                )
                table.add_row(
                    f"Temp ({temp.label})",
                    Text(f"{temp.current_celsius:.1f} deg C", style=t_style),
                )

        if not has_data:
            table.add_row(Text("Hardware Fans / Temp", style="dim"), Text("N/A on this OS", style="dim italic"))

        return Panel(table, title="[bold yellow]Hardware Sensors & Fan RPM[/bold yellow]", border_style="yellow")

    def make_storage_panel(self, snap: SystemSnapshot) -> Panel:
        table = Table(expand=True, show_header=False, box=None, padding=(0, 1))
        table.add_column("Mount", ratio=1)
        table.add_column("Bar", ratio=2)
        table.add_column("Usage", ratio=2, justify="right")

        for disk in snap.disks[:4]:
            d_style = get_threshold_style(
                disk.percent,
                self.config.thresholds.disk_warn,
                self.config.thresholds.disk_crit,
            )
            bar = ProgressBar(total=100, completed=disk.percent, width=None, style="grey23", complete_style=d_style)
            usage_str = f"{format_bytes(disk.used)} / {format_bytes(disk.total)} ({disk.percent:.1f}%)"
            table.add_row(Text(f"Disk {disk.mountpoint}", style="bold white"), bar, Text(usage_str, style=d_style))

        # Disk I/O rates
        io_table = Table.grid(expand=True)
        io_table.add_column(ratio=1)
        io_table.add_column(ratio=1, justify="right")
        io_table.add_row(
            Text(f"Read: {format_bytes(snap.disk_io.read_bytes_rate)}/s", style="cyan"),
            Text(f"Write: {format_bytes(snap.disk_io.write_bytes_rate)}/s", style="magenta"),
        )

        group = Group(table, io_table)
        return Panel(group, title="[bold magenta]Disk Storage & I/O[/bold magenta]", border_style="magenta")

    def make_network_panel(self, snap: SystemSnapshot) -> Panel:
        net = snap.network
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column("Item", ratio=1)
        table.add_column("Value", ratio=1, justify="right")

        table.add_row(
            Text("Download Rate:", style="bold white"),
            Text(f"{format_bytes(net.bytes_recv_rate)}/s", style="bold green"),
        )
        table.add_row(
            Text("Upload Rate:", style="bold white"),
            Text(f"{format_bytes(net.bytes_sent_rate)}/s", style="bold cyan"),
        )
        table.add_row(
            Text("Total Received:", style="dim"),
            Text(f"{format_bytes(net.total_recv)}", style="dim"),
        )
        table.add_row(
            Text("Total Sent:", style="dim"),
            Text(f"{format_bytes(net.total_sent)}", style="dim"),
        )

        # Active interface summary
        if net.interfaces:
            active_if = next((i for i in net.interfaces if i.is_up and i.ip_addresses), net.interfaces[0])
            ips = ", ".join(active_if.ip_addresses[:1])
            table.add_row(
                Text(f"Net ({active_if.name}):", style="dim"),
                Text(f"{ips}", style="dim yellow"),
            )

        return Panel(table, title="[bold blue]Network Traffic[/bold blue]", border_style="blue")

    def make_process_table(self, snap: SystemSnapshot) -> Panel:
        table = Table(expand=True, box=None, padding=(0, 1), show_edge=False)
        table.add_column("PID", style="dim", justify="right", width=7)
        table.add_column("Process Name", style="bold white", ratio=3)
        table.add_column("User", style="dim", ratio=2)
        table.add_column("Status", ratio=1)
        table.add_column("CPU %", justify="right", style="bold cyan", ratio=1)
        table.add_column("Memory %", justify="right", style="bold green", ratio=1)
        table.add_column("RAM (MB)", justify="right", ratio=1)
        table.add_column("Threads", justify="right", style="dim", ratio=1)

        for p in snap.top_processes:
            cpu_style = "bold red" if p.cpu_percent > 50 else ("yellow" if p.cpu_percent > 20 else "cyan")
            table.add_row(
                str(p.pid),
                p.name[:25],
                p.username[:15] if p.username else "-",
                p.status,
                Text(f"{p.cpu_percent:5.1f}%", style=cpu_style),
                f"{p.memory_percent:4.1f}%",
                f"{p.memory_rss / (1024 * 1024):6.1f}",
                str(p.num_threads),
            )

        title = f"[bold red]Top Processes[/bold red] (Sorted by {self.config.sort_by.upper()})"
        return Panel(table, title=title, border_style="red")

    def generate_layout(self, snap: SystemSnapshot) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=3),
            Layout(name="processes", ratio=2),
            Layout(name="footer", size=1),
        )

        layout["body"].split_row(
            Layout(name="left_col", ratio=1),
            Layout(name="right_col", ratio=1),
        )

        layout["left_col"].split_column(
            Layout(name="cpu", ratio=3),
            Layout(name="memory", ratio=2),
            Layout(name="sensors", ratio=2),
        )

        layout["right_col"].split_column(
            Layout(name="storage", ratio=3),
            Layout(name="network", ratio=2),
        )

        layout["header"].update(self.make_header(snap))
        layout["cpu"].update(self.make_cpu_panel(snap))
        layout["memory"].update(self.make_memory_panel(snap))
        layout["sensors"].update(self.make_sensors_panel(snap))
        layout["storage"].update(self.make_storage_panel(snap))
        layout["network"].update(self.make_network_panel(snap))
        layout["processes"].update(self.make_process_table(snap))

        footer_text = Text()
        footer_text.append("SysMom CLI", style="bold cyan")
        footer_text.append(" | Refresh: ", style="dim")
        footer_text.append(f"{self.config.refresh_rate}s", style="bold yellow")
        footer_text.append(" | Press ", style="dim")
        footer_text.append("Ctrl+C", style="bold white on red")
        footer_text.append(" to exit", style="dim")
        layout["footer"].update(footer_text)

        return layout


def run_live_dashboard(monitor: SystemMonitor, config: Config = DEFAULT_CONFIG) -> None:
    """Launch the interactive full-screen live dashboard."""
    console = Console()
    renderer = DashboardRenderer(config)

    with Live(console=console, screen=True, refresh_per_second=int(1 / config.refresh_rate) or 1) as live:
        try:
            while True:
                snapshot = monitor.get_snapshot(
                    process_limit=config.process_limit,
                    sort_by=config.sort_by,
                )
                layout = renderer.generate_layout(snapshot)
                live.update(layout)
                time.sleep(config.refresh_rate)
        except KeyboardInterrupt:
            pass
