import argparse
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
    if summary.imported == summary.duplicates == summary.skipped == 0 and not summary.failed:
        platform.notify("AnkiHelper", "Inbox is empty")
        print("Inbox is empty")
        return 0
    platform.notify("AnkiHelper batch", summary.message(), offer_setup=bool(summary.failed))
    print(summary.message())
    for entry_id, error in summary.failed.items():
        print(f"  {entry_id}: {error}", file=sys.stderr)
    return 1 if summary.failed else 0


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
    return gui_page(args.page)


def gui_page(page: str) -> int:
    from . import gui

    return gui.run(page)


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
    window.add_argument("page", nargs="?", default="setup", choices=["capture", "inbox", "setup", "settings"])
    window.set_defaults(func=cmd_setup)
    sub.add_parser("doctor", help="print the setup checklist").set_defaults(func=cmd_doctor)
    args = parser.parse_args(argv)
    if not args.command:
        return gui_page("capture")
    return args.func(args)
