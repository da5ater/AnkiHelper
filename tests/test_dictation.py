import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ankihelper import dictation


@pytest.fixture
def fake_hex(tmp_path, monkeypatch):
    """A running Hex: its discovery file plus a local API that answers `status` and records commands."""
    hex_state = {"status": {"listener": {"running": True}, "capture": {"state": "idle", "pending_jobs": 0}, "model": {"installed": True, "name": "Parakeet"}}, "commands": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers["Authorization"] != "Bearer secret":
                self.send_response(401)
                self.end_headers()
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            hex_state["commands"].append(body)
            reply = hex_state["status"] if body["command"] == "status" else {"changed": True}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (tmp_path / "local-api.json").write_text(json.dumps({"port": server.server_address[1], "token": "secret", "pid": 1}))
    monkeypatch.setattr(dictation, "_hex_dir", lambda: tmp_path)
    yield hex_state
    server.shutdown()


def test_mic_button_follows_hex_and_toggles_it(fake_hex):
    hex_engine = dictation.get("hex")
    assert hex_engine.state() == "idle"

    fake_hex["status"]["capture"]["state"] = "recording"
    assert hex_engine.state() == "recording"
    fake_hex["status"]["capture"] = {"state": "idle", "pending_jobs": 1}
    assert hex_engine.state() == "transcribing"

    hex_engine.toggle()
    assert fake_hex["commands"][-1] == {"version": 4, "command": "dictation", "action": "toggle"}


def test_setup_says_when_hex_is_still_downloading_its_model(fake_hex):
    assert dictation.status("hex") == (True, "Hex is ready with Parakeet")
    fake_hex["status"]["model"]["installed"] = False
    ok, detail = dictation.status("hex")
    assert not ok and "downloading" in detail


def test_hex_not_running_disables_the_mic(tmp_path, monkeypatch):
    monkeypatch.setattr(dictation, "_hex_dir", lambda: tmp_path)
    assert dictation.get("hex").state() is None
    assert dictation.status("hex")[0] is False
