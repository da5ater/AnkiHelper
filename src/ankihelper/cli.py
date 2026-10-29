import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime

from . import agents, batch, checks, config
from .anki import AnkiConnect, SetupProblem
from .config import Config
from .platforms import current as platform


def _log_traceback(name: str):
    log = config.log_dir() / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.log"
    log.write_text(traceback.format_exc())
    return log


def cmd_batch(args) -> int:
    cfg = Config.load()
    try:
        summary = batch.run(cfg, AnkiConnect(cfg.anki_url), agent=args.agent)
    except batch.BatchRunning as error:
        platform.notify("AnkiHelper", str(error))
        print(error, file=sys.stderr)
        return 4
    except SetupProblem as error:
        platform.notify("AnkiHelper: setup problem", f"{error}\nCards imported before this point are saved.", offer_setup=True)
        print(error, file=sys.stderr)
        return 2
    except agents.AgentError as error:
        log = _log_traceback("batch")
        platform.notify("AnkiHelper: agent problem", f"{error}\nNothing was imported. Log: {log}", offer_setup=True)
        print(error, file=sys.stderr)
        return 3
    except Exception as error:
        log = _log_traceback("batch")
        platform.notify("AnkiHelper: batch crashed", f"{error}\nLog: {log}", offer_setup=True)
        raise
    if not (summary.imported or summary.duplicates or summary.skipped or summary.failed or summary.fixed or summary.fix_errors or summary.suggestions):
        platform.notify("AnkiHelper", "Inbox is empty")
        print("Inbox is empty")
        return 0
    platform.notify("AnkiHelper batch", summary.message(), offer_setup=bool(summary.failed))
    print(summary.message())
    for entry_id, error in summary.failed.items():
        print(f"  {entry_id}: {error}", file=sys.stderr)
    return 1 if summary.failed else 0


def cmd_anki(args) -> int:
    """JSON in on stdin, JSON out on stdout: the protocol the Anki add-on speaks."""
    from . import bridge, learning

    request = json.loads(sys.stdin.read() or "{}")
    cfg = Config.load()
    try:
        if args.action == "fix":
            reply = bridge.rewrite(
                cfg, int(request["note_id"]), request["question_html"], request["answer_html"], request["feedback"], request.get("tags")
            )
        elif args.action == "optimize":
            entry = bridge.optimize(cfg, int(request["note_id"]), request["question_html"], request["answer_html"], request.get("deck", ""))
            subprocess.Popen(
                [sys.executable, "-m", "ankihelper", "setup", "review", "--entry", entry.id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            reply = {"entry_id": entry.id}
        elif args.action == "work":
            from . import jobs

            reply = jobs.run_batch(cfg, AnkiConnect(cfg.anki_url)) or {"idle": True}
        elif args.action == "jobs":
            from . import jobs

            reply = {"active": len(jobs.active())}
        elif args.action == "flag":
            bridge.flag(int(request["note_id"]), request.get("feedback", ""))
            reply = {"ok": True}
        elif args.action == "event":
            learn_now = bridge.report(request)
            if learn_now:
                subprocess.Popen(
                    [sys.executable, "-m", "ankihelper", "learn"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            reply = {"ok": True}
        elif args.action == "chat":
            reply = bridge.chat(
                cfg, int(request["note_id"]), request["question_html"], request["answer_html"], request["messages"], request.get("draft")
            )
        elif args.action == "chat-done":
            reply = bridge.finish_chat(
                cfg,
                int(request["note_id"]),
                request["before"],
                request.get("draft"),
                request["messages"],
                request.get("tags") or [],
                request.get("added") or [],
            )
        elif args.action == "unflag":
            bridge.unflag_note(int(request["note_id"]))
            reply = {"ok": True}
        elif args.action == "written":
            bridge.note_written(int(request["note_id"]))
            reply = {"ok": True}
        elif args.action == "history":
            reply = bridge.history(int(request["note_id"]))
        elif args.action == "use-version":
            reply = bridge.use_version(int(request["note_id"]), request["card"])
        else:
            reply = {"error": f"unknown action {args.action}"}
    except Exception as error:
        _log_traceback("anki-bridge")
        reply = {"error": str(error)}
    print(json.dumps(reply, ensure_ascii=False))
    return 0 if "error" not in reply else 1


def cmd_learn(args) -> int:
    from . import learning

    found = learning.learn(Config.load())
    if found:
        platform.notify("AnkiHelper", f"{len(found)} new rule suggestion(s) from how you edit and delete cards. See Settings.")
    for item in found:
        print(f"- {item['rule']}  ({item['evidence']})")
    return 0


def cmd_install_addon(args) -> int:
    from . import addon

    print(addon.install())
    return 0


def cmd_doctor(args) -> int:
    cfg = Config.load()
    results = checks.run_all(cfg)
    for check, result in results:
        print(f"{'PASS' if result.ok else 'FAIL'}  {check.title}: {result.detail}")
    return 0 if all(r.ok for _, r in results) else 1


def cmd_capture(args) -> int:
    from . import gui

    return gui.run("capture", close_after_save=not args.stay)


def cmd_setup(args) -> int:
    return gui_page(args.page, args.entry)


def gui_page(page: str, entry_id: str | None = None) -> int:
    from . import gui

    return gui.run(page, entry_id=entry_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ankihelper", description="Dictate Anki cards; batch-clean and import them.")
    sub = parser.add_subparsers(dest="command")
    capture = sub.add_parser("capture", help="open the window on the capture page")
    capture.add_argument("--stay", action="store_true", help="keep the window open after saving a card")
    capture.set_defaults(func=cmd_capture)
    batch_parser = sub.add_parser("batch", help="clean the inbox with the agent and import it into Anki")
    batch_parser.add_argument("--agent", choices=list(agents.AGENTS), help="override the default agent for this run")
    batch_parser.set_defaults(func=cmd_batch)
    window = sub.add_parser("setup", help="open the window (setup page by default)")
    window.add_argument("page", nargs="?", default="setup", choices=["capture", "inbox", "setup", "settings", "review"])
    window.add_argument("--entry", help="with the review page: the inbox entry to preview")
    window.set_defaults(func=cmd_setup)
    sub.add_parser("doctor", help="print the setup checklist").set_defaults(func=cmd_doctor)
    anki_parser = sub.add_parser("anki", help="requests from the AnkiHelper add-on inside Anki (JSON on stdin)")
    anki_parser.add_argument(
        "action", choices=["fix", "flag", "event", "written", "history", "use-version", "optimize", "work", "jobs", "unflag", "chat", "chat-done"]
    )
    anki_parser.set_defaults(func=cmd_anki)
    sub.add_parser("learn", help="suggest rules from your recent edits and deletions in Anki").set_defaults(func=cmd_learn)
    sub.add_parser("install-addon", help="install the AnkiHelper add-on into Anki").set_defaults(func=cmd_install_addon)
    args = parser.parse_args(argv)
    if not args.command:
        return gui_page("capture")
    return args.func(args)
