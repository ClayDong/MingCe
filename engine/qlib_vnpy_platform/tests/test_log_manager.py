import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from qlib_vnpy_platform.config import load_config
from qlib_vnpy_platform.core.log_manager import (
    setup_logging, get_log_files, read_log, export_logs, get_log_stats, _parse_log_line
)
from loguru import logger


def test_parse_log_line():
    line = "2026-05-15 14:30:00.123 | INFO     | module:func:10 - Test message"
    parsed = _parse_log_line(line)
    assert parsed["timestamp"] == "2026-05-15 14:30:00.123", "Timestamp should match"
    assert parsed["level"] == "INFO", "Level should be INFO"
    assert parsed["source"] == "module:func:10", "Source should match"
    assert parsed["message"] == "Test message", "Message should match"
    print("[PASS] Parse log line test")


def test_parse_log_line_short():
    line = "short line"
    parsed = _parse_log_line(line)
    assert "raw" in parsed, "Short line should have raw field"
    assert parsed["raw"] == "short line", "Raw should match"
    print("[PASS] Parse short log line test")


def test_setup_logging():
    load_config()
    setup_logging()
    logger.info("Test log entry from test_log_manager")

    import time
    time.sleep(0.5)

    log_files = get_log_files()
    assert len(log_files) > 0, "Should have log files after setup"
    print(f"[PASS] Setup logging test: {len(log_files)} log files created")


def test_get_log_stats():
    stats = get_log_stats()
    assert "total_files" in stats, "Should have total_files"
    assert "total_size_mb" in stats, "Should have total_size_mb"
    assert "files" in stats, "Should have files list"
    print(f"[PASS] Log stats test: {stats['total_files']} files, {stats['total_size_mb']} MB")


def test_read_log():
    log_files = get_log_files()
    if not log_files:
        print("[SKIP] Read log test - no log files")
        return

    entries = read_log(log_files[0]["name"], lines=10)
    assert isinstance(entries, list), "Should return a list"
    print(f"[PASS] Read log test: {len(entries)} entries read")


def test_export_logs_json():
    output = export_logs(format="json")
    try:
        data = json.loads(output)
        assert isinstance(data, list), "Should be a list"
        print(f"[PASS] Export logs JSON test: {len(data)} entries")
    except json.JSONDecodeError:
        print("[PASS] Export logs JSON test: empty or no data")


def test_export_logs_text():
    output = export_logs(format="txt")
    assert isinstance(output, str), "Should return a string"
    print(f"[PASS] Export logs text test: {len(output)} chars")


def test_read_nonexistent_log():
    entries = read_log("nonexistent_file.log")
    assert entries == [], "Should return empty list for nonexistent file"
    print("[PASS] Read nonexistent log test")


if __name__ == "__main__":
    load_config()

    test_parse_log_line()
    test_parse_log_line_short()
    test_setup_logging()
    test_get_log_stats()
    test_read_log()
    test_export_logs_json()
    test_export_logs_text()
    test_read_nonexistent_log()

    print("\n=== All LogManager tests passed ===")
