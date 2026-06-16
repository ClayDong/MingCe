"""Helper functions and shared globals for the web app package."""

import re
import time
import json

import numpy as np
from flask import jsonify

# Global engine instance (set from outside)
_engine_instance = None

# Global constants
_last_analyze_time = {}
ANALYZE_COOLDOWN = 30
VALID_SYMBOL_PATTERN = re.compile(r"^(SZ|SH|BJ)\d{6}$")


def _sanitize_json(obj):
    """Clean JSON values for safe serialization (handle NaN, Inf, numpy types)."""
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    elif isinstance(obj, float):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return 0
        return obj
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        v = float(obj)
        if v != v or v == float("inf") or v == float("-inf"):
            return 0
        return v
    elif isinstance(obj, np.ndarray):
        return _sanitize_json(obj.tolist())
    return obj


def get_engine():
    """Get the global MainEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        from qlib_vnpy_platform.config import load_config
        from qlib_vnpy_platform.core.main_engine import MainEngine
        load_config()
        _engine_instance = MainEngine()
    return _engine_instance


def _set_engine(engine):
    """Set the global MainEngine instance (used by entry point)."""
    global _engine_instance
    _engine_instance = engine


def safe_jsonify(data):
    """JSON-serialize data safely, handling numpy types and NaN."""
    return jsonify(_sanitize_json(data))
