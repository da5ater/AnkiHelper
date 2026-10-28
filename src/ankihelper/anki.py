import json
import time
import urllib.error
import urllib.request

from .platforms import current as platform


class AnkiError(Exception):
    """AnkiConnect answered with an error for this request."""


class SetupProblem(Exception):
    """Something `ankihelper setup` should fix before a batch can run."""


class AnkiUnreachable(SetupProblem):
    """Anki is not running, or AnkiConnect is not installed."""


class DuplicateNote(AnkiError):
    pass


class AnkiConnect:
    def __init__(self, url: str):
        self.url = url

    def invoke(self, action: str, timeout: float = 30, **params):
        body = json.dumps({"action": action, "version": 6, "params": params}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url, body), timeout=timeout) as resp:
                reply = json.load(resp)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise AnkiUnreachable(f"AnkiConnect not reachable at {self.url}: {e}") from e
        if reply.get("error"):
            message = str(reply["error"])
            if "duplicate" in message.lower():
                raise DuplicateNote(message)
            raise AnkiError(message)
        return reply["result"]

    def is_up(self, timeout: float = 1) -> bool:
        try:
            self.invoke("version", timeout=timeout)
            return True
        except AnkiUnreachable:
            return False

    def ensure_running(self, wait: float = 60) -> None:
        if self.is_up():
            return
        if not platform.anki_installed():
            raise AnkiUnreachable("Anki is not installed")
        platform.launch_anki()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(1)
            if self.is_up():
                return
        raise AnkiUnreachable(f"Started Anki but AnkiConnect did not answer within {wait:.0f}s")

    def deck_names(self) -> list[str]:
        return self.invoke("deckNames")

    def field_names(self, note_type: str) -> list[str]:
        return self.invoke("modelFieldNames", modelName=note_type)

    def create_deck(self, name: str) -> None:
        self.invoke("createDeck", deck=name)

    def add_note(self, deck: str, note_type: str, front: str, back: str, tags: list[str]) -> int:
        return self.invoke(
            "addNote",
            note={
                "deckName": deck,
                "modelName": note_type,
                "fields": {"Front": front, "Back": back},
                "tags": tags,
                "options": {"allowDuplicate": False, "duplicateScope": "collection"},
            },
        )

    def store_media(self, name: str, path: str) -> None:
        self.invoke("storeMediaFile", filename=name, path=path)

    def sync(self) -> None:
        self.invoke("sync", timeout=120)
