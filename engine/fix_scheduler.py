
from pathlib import Path

scheduler_path = str(Path(__file__).parent / "qlib_vnpy_platform/core/scheduler.py")

with open(scheduler_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_status = '''    @property
    def status(self):
        return {
            "running": self._running,
            "watch_list": self._watch_list,
            "scan_interval": self._scan_interval,
            "scan_count": self._scan_count,
            "last_scan_time": str(self._last_scan_time) if self._last_scan_time else None,
            "auto_trade": self._auto_trade,
        }'''

new_status = '''    @property
    def status(self):
        return {
            "running": self._running,
            "watch_list": self.engine._watch_list,
            "scan_interval": self._scan_interval,
            "scan_count": self._scan_count,
            "last_scan_time": str(self._last_scan_time) if self._last_scan_time else None,
            "auto_trade": self._auto_trade,
        }'''

content = content.replace(old_status, new_status)

with open(scheduler_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("修复成功！")
