# tests/test_logging_config.py
import json
import logging

from core.logging_config import REQUEST_ID_VAR, setup_logging


def test_plain_format_does_not_crash():
    setup_logging(json_mode=False)
    logging.getLogger("test").info("plain log")


def test_json_format_produces_valid_json(capsys):
    setup_logging(json_mode=True)
    REQUEST_ID_VAR.set("abc123")
    logging.getLogger("test_json").warning("hello world")
    captured = capsys.readouterr()
    # Find the JSON line in captured stderr
    for line in captured.err.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("message") == "hello world":
            assert data["level"] == "WARNING"
            assert data["logger"] == "test_json"
            assert data["request_id"] == "abc123"
            assert "timestamp" in data
            return
    raise AssertionError("No matching JSON log line found in output")


def test_request_id_defaults_to_dash(capsys):
    setup_logging(json_mode=True)
    REQUEST_ID_VAR.set("-")
    logging.getLogger("test_default").info("no id")
    captured = capsys.readouterr()
    for line in captured.err.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("message") == "no id":
            assert data["request_id"] == "-"
            return
    raise AssertionError("No matching JSON log line found")
