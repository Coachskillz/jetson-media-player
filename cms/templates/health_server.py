#!/usr/bin/env python3
"""
Health Monitoring Server - Local web server for device health and remote control.

Provides:
- System stats (CPU, memory, disk, GPU, temperature)
- Player status
- Network information
- Camera status
- Remote control commands
- Log viewing

Runs on port 8080 by default.
"""

import os
import json
import subprocess
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SystemMonitor:
    """Collects system health metrics."""

    @staticmethod
    def get_cpu_usage() -> float:
        """Get CPU usage percentage."""
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()
            values = line.split()[1:8]
            values = [int(v) for v in values]
            idle = values[3]
            total = sum(values)

            if not hasattr(SystemMonitor, '_last_cpu'):
                SystemMonitor._last_cpu = (idle, total)
                time.sleep(0.1)
                return SystemMonitor.get_cpu_usage()

            last_idle, last_total = SystemMonitor._last_cpu
            SystemMonitor._last_cpu = (idle, total)

            idle_delta = idle - last_idle
            total_delta = total - last_total

            if total_delta == 0:
                return 0.0

            return round((1 - idle_delta / total_delta) * 100, 1)
        except:
            return 0.0

    @staticmethod
    def get_memory_info() -> Dict[str, Any]:
        """Get memory usage info."""
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()

            mem = {}
            for line in lines:
                parts = line.split()
                key = parts[0].rstrip(':')
                value = int(parts[1]) * 1024
                mem[key] = value

            total = mem.get('MemTotal', 0)
            available = mem.get('MemAvailable', 0)
            used = total - available

            return {
                'total_mb': round(total / 1024 / 1024),
                'used_mb': round(used / 1024 / 1024),
                'available_mb': round(available / 1024 / 1024),
                'percent': round(used / total * 100, 1) if total > 0 else 0
            }
        except:
            return {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'percent': 0}

    @staticmethod
    def get_disk_info() -> Dict[str, Any]:
        """Get disk usage info."""
        try:
            stat = os.statvfs('/')
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            used = total - free

            return {
                'total_gb': round(total / 1024 / 1024 / 1024, 1),
                'used_gb': round(used / 1024 / 1024 / 1024, 1),
                'free_gb': round(free / 1024 / 1024 / 1024, 1),
                'percent': round(used / total * 100, 1) if total > 0 else 0
            }
        except:
            return {'total_gb': 0, 'used_gb': 0, 'free_gb': 0, 'percent': 0}

    @staticmethod
    def get_gpu_info() -> Dict[str, Any]:
        """Get NVIDIA GPU info."""
        try:
            result = subprocess.run(
                ['tegrastats', '--interval', '100'],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                return {
                    'usage_percent': 0,
                    'temperature_c': 0,
                    'type': 'Jetson'
                }
        except:
            pass
        return {'usage_percent': 0, 'temperature_c': 0, 'type': 'Unknown'}

    @staticmethod
    def get_temperature() -> Dict[str, float]:
        """Get system temperatures."""
        temps = {}
        try:
            thermal_path = Path('/sys/class/thermal')
            for zone in thermal_path.glob('thermal_zone*'):
                try:
                    type_file = zone / 'type'
                    temp_file = zone / 'temp'
                    if type_file.exists() and temp_file.exists():
                        zone_type = type_file.read_text().strip()
                        temp = int(temp_file.read_text().strip()) / 1000
                        temps[zone_type] = round(temp, 1)
                except:
                    pass
        except:
            pass
        return temps

    @staticmethod
    def get_network_info() -> Dict[str, Any]:
        """Get network interface info."""
        interfaces = {}
        try:
            result = subprocess.run(['ip', '-j', 'addr', 'show'], capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for iface in data:
                    name = iface.get('ifname', '')
                    if name in ('lo',):
                        continue
                    addrs = []
                    for addr_info in iface.get('addr_info', []):
                        if addr_info.get('family') == 'inet':
                            addrs.append(addr_info.get('local', ''))
                    if addrs:
                        interfaces[name] = {'ip': addrs[0], 'state': iface.get('operstate', 'unknown')}
        except:
            pass
        return interfaces

    @staticmethod
    def get_uptime() -> Dict[str, Any]:
        """Get system uptime."""
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            return {'seconds': int(uptime_seconds), 'formatted': f'{days}d {hours}h {minutes}m'}
        except:
            return {'seconds': 0, 'formatted': 'unknown'}


DASHBOARD_HTML = '''<!DOCTYPE html>
<html>
<head>
    <title>Skillz Media Player - Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #667eea; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: #1e293b; border-radius: 12px; padding: 20px; }
        .card h3 { color: #94a3b8; font-size: 14px; text-transform: uppercase; margin-bottom: 15px; }
        .stat { display: flex; justify-content: space-between; margin-bottom: 10px; }
        .stat-label { color: #64748b; }
        .stat-value { font-weight: bold; }
        .progress-bar { height: 8px; background: #374151; border-radius: 4px; overflow: hidden; margin-top: 5px; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); }
        .status-ok { color: #22c55e; }
        .status-warn { color: #f59e0b; }
        .btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; margin: 5px; }
        .btn-primary { background: #667eea; color: white; }
        .btn-danger { background: #ef4444; color: white; }
        #logs { background: #0f172a; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 12px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Skillz Media Player Dashboard</h1>
        <div class="grid">
            <div class="card">
                <h3>System</h3>
                <div class="stat"><span class="stat-label">Uptime</span><span class="stat-value" id="uptime">-</span></div>
                <div class="stat"><span class="stat-label">CPU</span><span class="stat-value" id="cpu">-</span></div>
                <div class="progress-bar"><div class="progress-fill" id="cpu-bar" style="width: 0%"></div></div>
                <div class="stat" style="margin-top:15px"><span class="stat-label">Memory</span><span class="stat-value" id="memory">-</span></div>
                <div class="progress-bar"><div class="progress-fill" id="mem-bar" style="width: 0%"></div></div>
                <div class="stat" style="margin-top:15px"><span class="stat-label">Disk</span><span class="stat-value" id="disk">-</span></div>
                <div class="progress-bar"><div class="progress-fill" id="disk-bar" style="width: 0%"></div></div>
            </div>
            <div class="card">
                <h3>GPU & Temperature</h3>
                <div class="stat"><span class="stat-label">GPU</span><span class="stat-value" id="gpu">-</span></div>
                <div id="temps"></div>
            </div>
            <div class="card">
                <h3>Network</h3>
                <div id="network"></div>
            </div>
            <div class="card">
                <h3>Player Status</h3>
                <div class="stat"><span class="stat-label">Status</span><span class="stat-value" id="player-status">-</span></div>
                <div class="stat"><span class="stat-label">Device ID</span><span class="stat-value" id="device-id">-</span></div>
                <div class="stat"><span class="stat-label">Pairing Code</span><span class="stat-value" id="pairing-code">-</span></div>
                <div style="margin-top:15px">
                    <button class="btn btn-primary" onclick="sendCommand('minimize')">Minimize</button>
                    <button class="btn btn-primary" onclick="sendCommand('maximize')">Maximize</button>
                    <button class="btn btn-danger" onclick="sendCommand('restart')">Restart</button>
                    <button class="btn btn-danger" onclick="if(confirm('Reboot?')) sendCommand('reboot')">Reboot</button>
                </div>
            </div>
        </div>
        <div class="card" style="margin-top: 20px;"><h3>Recent Logs</h3><div id="logs">Loading...</div></div>
    </div>
    <script>
        function updateDashboard() {
            fetch('/api/system').then(r => r.json()).then(data => {
                document.getElementById('uptime').textContent = data.uptime.formatted;
                document.getElementById('cpu').textContent = data.cpu.usage + '%';
                document.getElementById('cpu-bar').style.width = data.cpu.usage + '%';
                document.getElementById('memory').textContent = data.memory.used_mb + ' / ' + data.memory.total_mb + ' MB';
                document.getElementById('mem-bar').style.width = data.memory.percent + '%';
                document.getElementById('disk').textContent = data.disk.used_gb + ' / ' + data.disk.total_gb + ' GB';
                document.getElementById('disk-bar').style.width = data.disk.percent + '%';
                document.getElementById('gpu').textContent = data.gpu.type;
                var tempsHtml = '';
                for (var k in data.temperature) { tempsHtml += '<div class="stat"><span class="stat-label">' + k + '</span><span class="stat-value">' + data.temperature[k] + 'C</span></div>'; }
                document.getElementById('temps').innerHTML = tempsHtml;
                var netHtml = '';
                for (var k in data.network) { netHtml += '<div class="stat"><span class="stat-label">' + k + '</span><span class="stat-value">' + data.network[k].ip + '</span></div>'; }
                document.getElementById('network').innerHTML = netHtml || 'No interfaces';
            });
            fetch('/api/player').then(r => r.json()).then(data => {
                document.getElementById('player-status').textContent = data.status || 'Unknown';
                document.getElementById('device-id').textContent = data.device_id || '-';
                document.getElementById('pairing-code').textContent = data.pairing_code || '-';
            });
            fetch('/api/logs').then(r => r.json()).then(data => { document.getElementById('logs').textContent = data.logs.join('\\n'); });
        }
        function sendCommand(cmd) { fetch('/api/command/' + cmd, {method: 'POST'}).then(r => r.json()).then(data => alert(data.message || data.error)); }
        updateDashboard(); setInterval(updateDashboard, 5000);
    </script>
</body>
</html>'''


class HealthRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health endpoints."""
    player_controller = None
    log_dir = Path('/home/nvidia/skillz-player/logs')

    def log_message(self, format, *args):
        logger.debug(f'HTTP: {args[0]}')

    def _send_json(self, data: Dict, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_html(self, html: str, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/' or path == '/dashboard':
            self._send_html(DASHBOARD_HTML)
        elif path == '/api/health':
            self._send_json({'status': 'ok', 'timestamp': datetime.now().isoformat()})
        elif path == '/api/system':
            self._send_json({
                'cpu': {'usage': SystemMonitor.get_cpu_usage()},
                'memory': SystemMonitor.get_memory_info(),
                'disk': SystemMonitor.get_disk_info(),
                'gpu': SystemMonitor.get_gpu_info(),
                'temperature': SystemMonitor.get_temperature(),
                'network': SystemMonitor.get_network_info(),
                'uptime': SystemMonitor.get_uptime(),
                'timestamp': datetime.now().isoformat()
            })
        elif path == '/api/player':
            status = {'status': 'unknown', 'device_id': None, 'pairing_code': None}
            if self.player_controller:
                try:
                    status.update(self.player_controller.get_status())
                except:
                    pass
            self._send_json(status)
        elif path == '/api/logs':
            logs = []
            try:
                log_file = self.log_dir / 'player.log'
                if log_file.exists():
                    with open(log_file, 'r') as f:
                        logs = f.readlines()[-50:]
            except:
                logs = ['Error reading logs']
            self._send_json({'logs': logs})
        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/command/minimize':
            if self.player_controller and hasattr(self.player_controller, 'minimize'):
                self.player_controller.minimize()
            self._send_json({'message': 'Player minimized'})
        elif path == '/api/command/maximize':
            if self.player_controller and hasattr(self.player_controller, 'maximize'):
                self.player_controller.maximize()
            self._send_json({'message': 'Player maximized'})
        elif path == '/api/command/restart':
            self._send_json({'message': 'Restarting player...'})
            threading.Thread(target=lambda: os.system('systemctl --user restart skillz-player'), daemon=True).start()
        elif path == '/api/command/reboot':
            self._send_json({'message': 'Rebooting device...'})
            threading.Thread(target=lambda: os.system('sudo reboot'), daemon=True).start()
        elif path == '/api/command/reset_pairing':
            # Reset pairing to show pairing screen
            self._reset_pairing()
            self._send_json({'message': 'Pairing reset. Restarting player...'})
            threading.Thread(target=lambda: os.system('systemctl --user restart skillz-player'), daemon=True).start()
        elif path == '/api/command/show_pairing':
            # Reset pairing to show pairing screen
            self._reset_pairing()
            self._send_json({'message': 'Showing pairing screen. Restarting player...'})
            threading.Thread(target=lambda: os.system('systemctl --user restart skillz-player'), daemon=True).start()
        else:
            self._send_json({'error': 'Unknown command'}, 404)

    def _reset_pairing(self):
        """Reset device pairing status."""
        import json
        config_path = Path('/home/nvidia/skillz-player/config/device.json')
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                config['paired'] = False
                config['status'] = 'pending'
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                logger.info("Pairing reset successfully")
            except Exception as e:
                logger.error(f"Failed to reset pairing: {e}")


class HealthServer:
    """Health monitoring HTTP server."""

    def __init__(self, port: int = 8080, player_controller=None):
        self.port = port
        self.server = None
        self._thread = None
        HealthRequestHandler.player_controller = player_controller

    def start(self):
        self.server = HTTPServer(('0.0.0.0', self.port), HealthRequestHandler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f'Health server started on port {self.port}')

    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info('Health server stopped')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print('Starting health server on port 8080...')
    print('Open http://localhost:8080 in your browser')
    server = HealthServer(port=8080)
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
