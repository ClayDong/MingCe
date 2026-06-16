import os
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from qlib_vnpy_platform.config import get_config, LOGS_DIR


_log_configured = False


def setup_logging():
    global _log_configured
    if _log_configured:
        return

    config = get_config()
    log_level = config.get("logging", {}).get("level", "INFO")
    rotation = config.get("logging", {}).get("rotation", "50 MB")
    retention = config.get("logging", {}).get("retention", "30 days")

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        test_file = LOGS_DIR / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        log_dir = LOGS_DIR
    except Exception:
        log_dir = Path(tempfile.gettempdir()) / "qlib_vnpy_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        print(f"[WARN] Using fallback log directory: {log_dir}")

    logger.add(
        str(log_dir / "platform_{time:YYYY-MM-DD}.log"),
        level=log_level,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
        enqueue=True,
    )

    logger.add(
        str(log_dir / "trades_{time:YYYY-MM-DD}.log"),
        level="INFO",
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        filter=lambda record: "Trade executed" in record["message"] or "Order" in record["message"],
        enqueue=True,
    )

    _log_configured = True
    logger.info("Logging system initialized")


def get_log_files() -> list:
    try:
        if not LOGS_DIR.exists():
            return []
        files = sorted(LOGS_DIR.glob("*.log"), reverse=True)
        return [{"name": f.name, "size": f.stat().st_size, "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()} for f in files]
    except Exception:
        return []


def read_log(filename: str, lines: int = 200, level_filter: str = None) -> list:
    filepath = (LOGS_DIR / filename).resolve()
    if not filepath.exists() or not str(filepath).startswith(str(LOGS_DIR.resolve())):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except Exception:
        return []

    result = []
    for line in all_lines[-lines * 3:]:
        line = line.strip()
        if not line:
            continue

        parsed = _parse_log_line(line)
        if level_filter and parsed.get("level") != level_filter:
            continue
        result.append(parsed)

    return result[-lines:]


def _parse_log_line(line: str) -> dict:
    parts = line.split(" | ", 2)
    if len(parts) >= 3:
        source_msg = parts[2].strip()
        if " - " in source_msg:
            source, message = source_msg.split(" - ", 1)
        else:
            source = ""
            message = source_msg
        return {
            "timestamp": parts[0].strip(),
            "level": parts[1].strip(),
            "source": source,
            "message": message,
        }
    if len(parts) == 2:
        return {
            "timestamp": parts[0].strip(),
            "level": parts[1].strip(),
            "message": "",
        }
    return {"raw": line}


def export_logs(filename: str = None, date_from: str = None, date_to: str = None,
                level: str = None, format: str = "json") -> str:
    if filename:
        files = [LOGS_DIR / filename]
    else:
        pattern = "platform_*.log"
        try:
            files = sorted(LOGS_DIR.glob(pattern), reverse=True)
        except Exception:
            return json.dumps([]) if format == "json" else ""

    all_entries = []
    for f in files:
        if not f.exists():
            continue

        if date_from or date_to:
            date_str = f.stem.replace("platform_", "")
            try:
                file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if date_from:
                    from_date = datetime.strptime(date_from, "%Y-%m-%d").date()
                    if file_date < from_date:
                        continue
                if date_to:
                    to_date = datetime.strptime(date_to, "%Y-%m-%d").date()
                    if file_date > to_date:
                        continue
            except ValueError:
                continue

        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    parsed = _parse_log_line(line.strip())
                    if level and parsed.get("level") != level:
                        continue
                    if parsed.get("raw") or parsed.get("message"):
                        all_entries.append(parsed)
        except Exception:
            continue

    if format == "json":
        return json.dumps(all_entries, ensure_ascii=False, indent=2)
    else:
        lines = []
        for e in all_entries:
            if e.get("raw"):
                lines.append(e["raw"])
            else:
                lines.append(f"{e.get('timestamp', '')} | {e.get('level', '')} | {e.get('source', '')} | {e.get('message', '')}")
        return "\n".join(lines)


def get_log_stats() -> dict:
    try:
        files = get_log_files()
        total_size = sum(f["size"] for f in files)
        return {
            "total_files": len(files),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "files": files[:10],
        }
    except Exception:
        return {"total_files": 0, "total_size_mb": 0, "files": []}
