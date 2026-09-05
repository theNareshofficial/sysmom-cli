"""
System metrics monitoring and data collection engine using psutil and Windows sensor fallbacks.
"""

from dataclasses import dataclass, field
import datetime
import os
import platform
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
import psutil


def format_bytes(bytes_value: float) -> str:
    """Format bytes into a human-readable string (KB, MB, GB, TB)."""
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(bytes_value) < 1024.0:
            return f"{bytes_value:3.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format duration in seconds into human-readable HH:MM:SS or days."""
    delta = datetime.timedelta(seconds=int(seconds))
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    return f"{hours:02d}h {minutes:02d}m {secs:02d}s"


@dataclass
class SystemInfo:
    hostname: str
    os_name: str
    os_release: str
    os_version: str
    architecture: str
    cpu_model: str
    physical_cores: int
    logical_cores: int
    boot_time: datetime.datetime
    uptime: str


@dataclass
class CPUMetrics:
    total_percent: float
    per_core: List[float]
    frequency_current_mhz: Optional[float] = None
    frequency_min_mhz: Optional[float] = None
    frequency_max_mhz: Optional[float] = None


@dataclass
class MemoryMetrics:
    ram_total: int
    ram_used: int
    ram_free: int
    ram_available: int
    ram_percent: float
    swap_total: int
    swap_used: int
    swap_free: int
    swap_percent: float


@dataclass
class DiskPartitionMetrics:
    device: str
    mountpoint: str
    fstype: str
    total: int
    used: int
    free: int
    percent: float


@dataclass
class DiskIOMetrics:
    read_bytes_rate: float
    write_bytes_rate: float
    read_count_rate: float
    write_count_rate: float


@dataclass
class NetworkInterface:
    name: str
    ip_addresses: List[str]
    is_up: bool
    speed_mbps: int


@dataclass
class NetworkIOMetrics:
    bytes_sent_rate: float  
    bytes_recv_rate: float  
    total_sent: int
    total_recv: int
    interfaces: List[NetworkInterface] = field(default_factory=list)


@dataclass
class BatteryMetrics:
    present: bool
    percent: Optional[float] = None
    power_plugged: Optional[bool] = None
    time_left: Optional[str] = None


@dataclass
class FanSensor:
    name: str
    label: str
    current_rpm: int
    unit: str = "RPM"


@dataclass
class TemperatureSensor:
    name: str
    label: str
    current_celsius: float
    high_celsius: Optional[float] = None
    critical_celsius: Optional[float] = None


@dataclass
class HardwareSensors:
    fans: List[FanSensor] = field(default_factory=list)
    temperatures: List[TemperatureSensor] = field(default_factory=list)


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_rss: int
    status: str
    username: str
    num_threads: int


@dataclass
class SystemSnapshot:
    timestamp: datetime.datetime
    system_info: SystemInfo
    cpu: CPUMetrics
    memory: MemoryMetrics
    disks: List[DiskPartitionMetrics]
    disk_io: DiskIOMetrics
    network: NetworkIOMetrics
    battery: BatteryMetrics
    sensors: HardwareSensors
    top_processes: List[ProcessInfo]


class SystemMonitor:
    """Collects and aggregates real-time hardware and OS metrics."""

    def __init__(self):
        self._last_net_io = psutil.net_io_counters()
        self._last_net_time = time.time()
        self._last_disk_io = psutil.disk_io_counters()
        self._last_disk_time = time.time()
        self._has_nvidia = True  # Tentative flag, set False if nvidia-smi not available
        # Prime psutil cpu measurement
        psutil.cpu_percent(interval=None, percpu=True)

    def get_system_info(self) -> SystemInfo:
        uname = platform.uname()
        boot_time_ts = psutil.boot_time()
        boot_time = datetime.datetime.fromtimestamp(boot_time_ts)
        uptime = format_duration(time.time() - boot_time_ts)

        cpu_model = uname.processor or platform.machine()
        if not cpu_model:
            cpu_model = "CPU"

        return SystemInfo(
            hostname=socket.gethostname(),
            os_name=platform.system(),
            os_release=platform.release(),
            os_version=platform.version(),
            architecture=platform.machine(),
            cpu_model=cpu_model,
            physical_cores=psutil.cpu_count(logical=False) or 1,
            logical_cores=psutil.cpu_count(logical=True) or 1,
            boot_time=boot_time,
            uptime=uptime,
        )

    def get_cpu_metrics(self) -> CPUMetrics:
        total = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        freq = psutil.cpu_freq()

        freq_curr = freq.current if freq else None
        freq_min = freq.min if freq else None
        freq_max = freq.max if freq else None

        return CPUMetrics(
            total_percent=total,
            per_core=per_core,
            frequency_current_mhz=freq_curr,
            frequency_min_mhz=freq_min,
            frequency_max_mhz=freq_max,
        )

    def get_memory_metrics(self) -> MemoryMetrics:
        vmem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return MemoryMetrics(
            ram_total=vmem.total,
            ram_used=vmem.used,
            ram_free=vmem.free,
            ram_available=vmem.available,
            ram_percent=vmem.percent,
            swap_total=swap.total,
            swap_used=swap.used,
            swap_free=swap.free,
            swap_percent=swap.percent,
        )

    def get_disk_metrics(self) -> List[DiskPartitionMetrics]:
        partitions = psutil.disk_partitions(all=False)
        result = []
        seen_mountpoints = set()

        for part in partitions:
            if part.mountpoint in seen_mountpoints:
                continue
            seen_mountpoints.add(part.mountpoint)
            try:
                usage = psutil.disk_usage(part.mountpoint)
                result.append(
                    DiskPartitionMetrics(
                        device=part.device,
                        mountpoint=part.mountpoint,
                        fstype=part.fstype,
                        total=usage.total,
                        used=usage.used,
                        free=usage.free,
                        percent=usage.percent,
                    )
                )
            except (PermissionError, OSError):
                continue

        return result

    def get_disk_io_metrics(self) -> DiskIOMetrics:
        now = time.time()
        current_io = psutil.disk_io_counters()
        dt = max(now - self._last_disk_time, 0.001)

        read_bytes_rate = 0.0
        write_bytes_rate = 0.0
        read_count_rate = 0.0
        write_count_rate = 0.0

        if current_io and self._last_disk_io:
            read_bytes_rate = max(0.0, (current_io.read_bytes - self._last_disk_io.read_bytes) / dt)
            write_bytes_rate = max(0.0, (current_io.write_bytes - self._last_disk_io.write_bytes) / dt)
            read_count_rate = max(0.0, (current_io.read_count - self._last_disk_io.read_count) / dt)
            write_count_rate = max(0.0, (current_io.write_count - self._last_disk_io.write_count) / dt)

        self._last_disk_io = current_io
        self._last_disk_time = now

        return DiskIOMetrics(
            read_bytes_rate=read_bytes_rate,
            write_bytes_rate=write_bytes_rate,
            read_count_rate=read_count_rate,
            write_count_rate=write_count_rate,
        )

    def get_network_metrics(self) -> NetworkIOMetrics:
        now = time.time()
        current_io = psutil.net_io_counters()
        dt = max(now - self._last_net_time, 0.001)

        bytes_sent_rate = 0.0
        bytes_recv_rate = 0.0

        if current_io and self._last_net_io:
            bytes_sent_rate = max(0.0, (current_io.bytes_sent - self._last_net_io.bytes_sent) / dt)
            bytes_recv_rate = max(0.0, (current_io.bytes_recv - self._last_net_io.bytes_recv) / dt)

        self._last_net_io = current_io
        self._last_net_time = now

        # Get interfaces info
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        interfaces = []

        for if_name, addr_list in addrs.items():
            ip_list = []
            for addr in addr_list:
                if addr.family == socket.AF_INET or addr.family == socket.AF_INET6:
                    ip_list.append(addr.address)

            stat = stats.get(if_name)
            is_up = stat.isup if stat else False
            speed = stat.speed if stat else 0

            # Filter loopback or disconnected unless all are down
            if ip_list:
                interfaces.append(
                    NetworkInterface(
                        name=if_name,
                        ip_addresses=ip_list,
                        is_up=is_up,
                        speed_mbps=speed,
                    )
                )

        return NetworkIOMetrics(
            bytes_sent_rate=bytes_sent_rate,
            bytes_recv_rate=bytes_recv_rate,
            total_sent=current_io.bytes_sent if current_io else 0,
            total_recv=current_io.bytes_recv if current_io else 0,
            interfaces=interfaces,
        )

    def get_battery_metrics(self) -> BatteryMetrics:
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                return BatteryMetrics(present=False)

            time_left = None
            if battery.secsleft != psutil.POWER_TIME_UNLIMITED and battery.secsleft != psutil.POWER_TIME_UNKNOWN:
                time_left = format_duration(battery.secsleft)
            elif battery.power_plugged:
                time_left = "Charging / Plugged"

            return BatteryMetrics(
                present=True,
                percent=battery.percent,
                power_plugged=battery.power_plugged,
                time_left=time_left,
            )
        except Exception:
            return BatteryMetrics(present=False)

    def _get_nvidia_sensors(self) -> tuple[List[FanSensor], List[TemperatureSensor]]:
        fans: List[FanSensor] = []
        temps: List[TemperatureSensor] = []
        if not self._has_nvidia:
            return fans, temps

        try:
            # Query nvidia-smi for fan speed and gpu temperature
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,fan.speed,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1.5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().splitlines()
                for i, line in enumerate(lines):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        gpu_name, fan_speed_str, temp_str = parts[0], parts[1], parts[2]
                        
                        # Fan reading (percentage or RPM if reported)
                        try:
                            fan_val = int(float(fan_speed_str))
                            fans.append(
                                FanSensor(
                                    name=f"gpu_fan_{i}",
                                    label=f"GPU Fan ({gpu_name[:12]})",
                                    current_rpm=fan_val,
                                    unit="%" if fan_val <= 100 else "RPM",
                                )
                            )
                        except ValueError:
                            pass

                        # Temp reading
                        try:
                            temp_val = float(temp_str)
                            temps.append(
                                TemperatureSensor(
                                    name=f"gpu_temp_{i}",
                                    label=f"GPU ({gpu_name[:12]})",
                                    current_celsius=temp_val,
                                    high_celsius=85.0,
                                    critical_celsius=95.0,
                                )
                            )
                        except ValueError:
                            pass
            else:
                self._has_nvidia = False
        except Exception:
            self._has_nvidia = False

        return fans, temps

    def _get_wmi_sensors(self) -> tuple[List[FanSensor], List[TemperatureSensor]]:
        fans: List[FanSensor] = []
        temps: List[TemperatureSensor] = []

        if sys.platform != "win32":
            return fans, temps

        try:
            # Query WMI MSAcpi_ThermalZoneTemperature or LibreHardwareMonitor / OpenHardwareMonitor
            # Using PowerShell lightweight command or CIM
            ps_cmd = (
                "$Output = @(); "
                "$acpi = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue; "
                "if ($acpi) { foreach ($t in $acpi) { $c = ($t.CurrentTemperature - 2732) / 10.0; $Output += \"TEMP:ACPI Thermal Zone:$c\" } }; "
                "$lhm = Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor -ErrorAction SilentlyContinue; "
                "if ($lhm) { foreach ($s in $lhm) { if ($s.SensorType -eq 'Fan') { $Output += \"FAN:$($s.Name):$($s.Value)\" } elseif ($s.SensorType -eq 'Temperature') { $Output += \"TEMP:$($s.Name):$($s.Value)\" } } }; "
                "$Output -join '|'"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2.0,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0 and result.stdout.strip():
                items = result.stdout.strip().split("|")
                for item in items:
                    parts = item.strip().split(":")
                    if len(parts) >= 3:
                        tag, label, val_str = parts[0], parts[1], parts[2]
                        try:
                            val = float(val_str)
                            if tag == "FAN":
                                fans.append(
                                    FanSensor(
                                        name=label.lower().replace(" ", "_"),
                                        label=label,
                                        current_rpm=int(val),
                                    )
                                )
                            elif tag == "TEMP" and 0 <= val <= 130:
                                temps.append(
                                    TemperatureSensor(
                                        name=label.lower().replace(" ", "_"),
                                        label=label,
                                        current_celsius=val,
                                    )
                                )
                        except ValueError:
                            continue
        except Exception:
            pass

        return fans, temps

    def get_sensors_metrics(self) -> HardwareSensors:
        fans_list: List[FanSensor] = []
        temps_list: List[TemperatureSensor] = []

        # 1. Standard psutil fans (Linux / macOS)
        if hasattr(psutil, "sensors_fans"):
            try:
                fans = psutil.sensors_fans()
                if fans:
                    for name, entries in fans.items():
                        for entry in entries:
                            fans_list.append(
                                FanSensor(
                                    name=name,
                                    label=entry.label or name,
                                    current_rpm=entry.current,
                                )
                            )
            except Exception:
                pass

        # 2. Standard psutil temperatures (Linux / macOS)
        if hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        for entry in entries:
                            temps_list.append(
                                TemperatureSensor(
                                    name=name,
                                    label=entry.label or name,
                                    current_celsius=entry.current,
                                    high_celsius=entry.high,
                                    critical_celsius=entry.critical,
                                )
                            )
            except Exception:
                pass

        # 3. NVIDIA GPU Fan & Temp (Windows / Linux)
        nv_fans, nv_temps = self._get_nvidia_sensors()
        fans_list.extend(nv_fans)
        temps_list.extend(nv_temps)

        # 4. Windows WMI / ACPI / LibreHardwareMonitor if fans or temps are still empty
        if not fans_list or not temps_list:
            wmi_fans, wmi_temps = self._get_wmi_sensors()
            if not fans_list:
                fans_list.extend(wmi_fans)
            if not temps_list:
                temps_list.extend(wmi_temps)

        return HardwareSensors(fans=fans_list, temperatures=temps_list)

    def get_top_processes(self, limit: int = 10, sort_by: str = "cpu") -> List[ProcessInfo]:
        processes: List[ProcessInfo] = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent", "memory_info", "status", "username", "num_threads"]
        ):
            try:
                info = proc.info
                mem_rss = info["memory_info"].rss if info.get("memory_info") else 0
                processes.append(
                    ProcessInfo(
                        pid=info["pid"],
                        name=info["name"] or "unknown",
                        cpu_percent=info.get("cpu_percent") or 0.0,
                        memory_percent=info.get("memory_percent") or 0.0,
                        memory_rss=mem_rss,
                        status=info.get("status") or "running",
                        username=info.get("username") or "",
                        num_threads=info.get("num_threads") or 0,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if sort_by.lower() == "memory":
            processes.sort(key=lambda p: p.memory_percent, reverse=True)
        else:
            processes.sort(key=lambda p: p.cpu_percent, reverse=True)

        return processes[:limit]

    def get_snapshot(self, process_limit: int = 10, sort_by: str = "cpu") -> SystemSnapshot:
        return SystemSnapshot(
            timestamp=datetime.datetime.now(),
            system_info=self.get_system_info(),
            cpu=self.get_cpu_metrics(),
            memory=self.get_memory_metrics(),
            disks=self.get_disk_metrics(),
            disk_io=self.get_disk_io_metrics(),
            network=self.get_network_metrics(),
            battery=self.get_battery_metrics(),
            sensors=self.get_sensors_metrics(),
            top_processes=self.get_top_processes(limit=process_limit, sort_by=sort_by),
        )
