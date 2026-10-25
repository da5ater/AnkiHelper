import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeAnki:
    """Just enough of AnkiConnect for the batch: decks, one note type, addNote with duplicate checks."""

    def __init__(self):
        self.decks = {"Default", "manual", "manual::ruby"}
        self.notes: list[dict] = []
        self.synced = 0
        self.reject_fronts_containing = "REJECTME"

    def handle(self, action: str, params: dict):
        if action == "version":
            return 6
        if action == "deckNames":
            return sorted(self.decks)
        if action == "modelFieldNames":
            if params["modelName"] != "Basic+":
                raise ValueError("model was not found")
            return ["Front", "Back"]
        if action == "createDeck":
            self.decks.add(params["deck"])
            return 1
        if action == "addNote":
            note = params["note"]
            front = note["fields"]["Front"]
            if self.reject_fronts_containing.lower() in front.lower():
                raise ValueError("cannot create note because the front contains a forbidden marker")
            if any(n["fields"]["Front"] == front for n in self.notes):
                raise ValueError("cannot create note because it is a duplicate")
            if note["deckName"] not in self.decks:
                raise ValueError(f"deck was not found: {note['deckName']}")
            self.notes.append(note)
            return len(self.notes)
        if action == "sync":
            self.synced += 1
            return None
        raise ValueError(f"unsupported action {action}")


@pytest.fixture
def fake_anki():
    anki = FakeAnki()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                reply = {"result": anki.handle(body["action"], body.get("params", {})), "error": None}
            except ValueError as e:
                reply = {"result": None, "error": str(e)}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    anki.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield anki
    server.shutdown()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKIHELPER_HOME", str(tmp_path / "home"))
    return tmp_path / "home"
