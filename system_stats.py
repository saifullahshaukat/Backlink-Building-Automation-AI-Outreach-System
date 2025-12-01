import psutil
import platform
from datetime import datetime
import time

class SystemStats:
    def __init__(self):
        self.boot_time = datetime.fromtimestamp(psutil.boot_time())
        self.cpu_count = psutil.cpu_count()
        self.cpu_count_logical = psutil.cpu_count(logical=True)
        
    def get_cpu_stats(self):
        cpu_percent = psutil.cpu_percent(interval=0.1, percpu=True)
        cpu_freq = psutil.cpu_freq()
        
        return {
            'total_percent': psutil.cpu_percent(interval=0.1),
            'per_cpu': cpu_percent,
            'frequency': {
                'current': cpu_freq.current if cpu_freq else 0,
                'min': cpu_freq.min if cpu_freq else 0,
                'max': cpu_freq.max if cpu_freq else 0
            },
            'count_physical': self.cpu_count,
            'count_logical': self.cpu_count_logical
        }
    
    def get_memory_stats(self):
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            'virtual': {
                'total': memory.total,
                'available': memory.available,
                'used': memory.used,
                'percent': memory.percent,
                'free': memory.free
            },
            'swap': {
                'total': swap.total,
                'used': swap.used,
                'free': swap.free,
                'percent': swap.percent
            }
        }
    
    def get_disk_stats(self):
        partitions = psutil.disk_partitions()
        disk_info = []
        
        for partition in partitions:
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_info.append({
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'fstype': partition.fstype,
                    'total': usage.total,
                    'used': usage.used,
                    'free': usage.free,
                    'percent': usage.percent
                })
            except PermissionError:
                continue
        
        disk_io = psutil.disk_io_counters()
        
        return {
            'partitions': disk_info,
            'io': {
                'read_count': disk_io.read_count if disk_io else 0,
                'write_count': disk_io.write_count if disk_io else 0,
                'read_bytes': disk_io.read_bytes if disk_io else 0,
                'write_bytes': disk_io.write_bytes if disk_io else 0
            }
        }
    
    def get_network_stats(self):
        net_io = psutil.net_io_counters()
        connections = len(psutil.net_connections())
        
        return {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv,
            'errors_in': net_io.errin,
            'errors_out': net_io.errout,
            'drop_in': net_io.dropin,
            'drop_out': net_io.dropout,
            'connections': connections
        }
    
    def get_process_stats(self):
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
        
        return {
            'total': len(processes),
            'top_cpu': processes[:10],
            'top_memory': sorted(processes, key=lambda x: x['memory_percent'] or 0, reverse=True)[:10]
        }
    
    def get_system_info(self):
        return {
            'platform': platform.system(),
            'platform_release': platform.release(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'hostname': platform.node(),
            'processor': platform.processor(),
            'boot_time': self.boot_time.strftime('%Y-%m-%d %H:%M:%S'),
            'uptime': str(datetime.now() - self.boot_time).split('.')[0]
        }
    
    def get_all_stats(self):
        return {
            'cpu': self.get_cpu_stats(),
            'memory': self.get_memory_stats(),
            'disk': self.get_disk_stats(),
            'network': self.get_network_stats(),
            'processes': self.get_process_stats(),
            'system': self.get_system_info(),
            'timestamp': datetime.now().isoformat()
        }
    
    @staticmethod
    def format_bytes(bytes_value):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"