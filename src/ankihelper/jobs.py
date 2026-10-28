"""Apply a personal rule to cards already in Anki, in the background, a few cards at a time.

A job is a frozen list of note ids plus a cursor, saved after every batch, so it resumes exactly where it
stopped. Every card it changes is backed up first so one card or the whole job can be undone. When the
learner pushes back on a card a job changed, the rule is refined and the cards already changed are
queued again to be rechecked against the new wording.
"""

import json
import uuid
from datetime import datetime

from filelock import FileLock, Timeout

from . import agents, config, review
from .config import Config

BATCH = 10
"""Cards per agent call: small enough that the agent judges each card on its own."""
RUNNING, PAUSED, DONE = "running", "paused", "done"
SCOPES = {
    "ankihelper": ("Cards AnkiHelper made", "tag:manual_voice"),
    "manual": ("Everything in my root deck", None),
    "all": ("All my cards", "deck:*"),
}


def _path():
    return config.data_dir() / "jobs.json"


def _backups_path():
    return config.data_dir() / "backups.jsonl"


def _lock() -> FileLock:
    return FileLock(str(config.data_dir() / "jobs.lock"))


def all_jobs() -> list[dict]:
    path = _path()
    return json.loads(path.read_text()) if path.exists() else []


def _save(jobs: list[dict]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    tmp.replace(_path())


def _update(job_id: str, change) -> dict | None:
    with _lock():
        jobs = all_jobs()
        for job in jobs:
            if job["id"] == job_id:
                change(job)
                _save(jobs)
                return job
    return None


def query_for(cfg: Config, scope: str) -> str:
    label, query = SCOPES[scope]
    return query or f'"deck:{cfg.root_deck}"'


def start(cfg: Config, anki, rule: str, scope: str) -> dict:
    """Queue every matching note for the rule. Nothing changes in Anki until the worker runs."""
    note_ids = sorted(anki.invoke("findNotes", query=query_for(cfg, scope)))
    job = {
        "id": uuid.uuid4().hex[:8],
        "rule": rule,
        "version": 1,
        "scope": scope,
        "status": RUNNING if note_ids else DONE,
        "queue": note_ids,
        "next": 0,
        "changed": [],
        "skipped": 0,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock():
        _save(all_jobs() + [job])
    return job


def pause(job_id: str) -> None:
    _update(job_id, lambda j: j.update(status=PAUSED) if j["status"] == RUNNING else None)


def resume(job_id: str) -> None:
    _update(job_id, lambda j: j.update(status=RUNNING) if j["status"] == PAUSED else None)


def active() -> list[dict]:
    return [j for j in all_jobs() if j["status"] == RUNNING]


def _rewritable(anki, info: dict, models: dict) -> bool:
    if not info or len(info.get("fields") or {}) != 2:
        return False
    name = info["modelName"]
    if name not in models:
        [model] = anki.invoke("findModelsByName", modelNames=[name])
        models[name] = model.get("type") != 1
    return models[name]


def _backup(job: dict, note_id: int, fields: dict) -> None:
    line = {"job": job["id"], "version": job["version"], "note_id": note_id, "fields": fields, "time": datetime.now().isoformat(timespec="seconds")}
    with _backups_path().open("a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _batch_prompt(cfg: Config, job: dict, cards: list[dict]) -> str:
    return agents.prompt(
        "apply_rule",
        rule=job["rule"],
        language=cfg.language,
        rules=config.personal_rules() or "(none yet)",
        cards="\n".join(json.dumps(c, ensure_ascii=False) for c in cards),
    )


def run_batch(cfg: Config, anki) -> dict | None:
    """Advance the oldest running job by one batch. Returns what happened, or None when nothing is running.

    Only one worker runs at a time; a second call while one is busy returns None immediately."""
    from . import bridge, render

    worker = FileLock(str(config.data_dir() / "jobs-worker.lock"))
    try:
        worker.acquire(timeout=0)
    except Timeout:
        return None
    try:
        jobs = active()
        if not jobs:
            return None
        job = jobs[0]
        ids = job["queue"][job["next"] : job["next"] + BATCH]
        if not ids:
            _update(job["id"], lambda j: j.update(status=DONE))
            return {"job": job["id"], "done": True}
        infos = anki.notes_info(ids)
        models: dict = {}
        cards, fields_by_id = [], {}
        for note_id, info in zip(ids, infos):
            if not _rewritable(anki, info, models):
                continue
            (q_name, q), (a_name, a) = sorted(info["fields"].items(), key=lambda kv: kv[1]["order"])
            fields_by_id[note_id] = (q_name, q["value"], a_name, a["value"])
            cards.append({"note_id": note_id, "question": bridge.text_of(q["value"]), "answer": bridge.text_of(a["value"])})
        changed = []
        if cards:
            reply = agents.extract_json(agents.ask(cfg.agent, _batch_prompt(cfg, job, cards)))
            for raw in reply.get("cards") or []:
                note_id = raw.get("note_id") if isinstance(raw, dict) else None
                if note_id not in fields_by_id or not raw.get("changed"):
                    continue
                q_name, q_html, a_name, a_html = fields_by_id[note_id]
                question, answer = str(raw.get("question") or "").strip(), str(raw.get("answer") or "").strip()
                if not question or not answer:
                    continue
                _backup(job, note_id, {q_name: q_html, a_name: a_html})
                bridge.note_written(note_id)
                anki.update_fields(
                    note_id,
                    {
                        q_name: render.question_html(question) + bridge._images_in(q_html),
                        a_name: render.to_html(answer) + bridge._images_in(a_html),
                    },
                )
                anki.add_tags([note_id], [f"ah::rule::{job['id']}"])
                changed.append(note_id)

        def advance(j: dict) -> None:
            j["next"] += len(ids)
            j["changed"] = sorted(set(j["changed"]) | set(changed))
            j["skipped"] += len(ids) - len(changed)
            if j["next"] >= len(j["queue"]):
                j["status"] = DONE

        _update(job["id"], advance)
        return {"job": job["id"], "checked": len(ids), "changed": len(changed)}
    finally:
        worker.release()


def job_for_note(tags: list[str]) -> dict | None:
    ids = {t.split("::")[-1] for t in tags if t.startswith("ah::rule::")}
    found = [j for j in all_jobs() if j["id"] in ids]
    return found[-1] if found else None


def refine(cfg: Config, job: dict, card_before: dict, card_after_job: dict, feedback: str) -> str | None:
    """The learner pushed back on a card this job changed: reword the rule from their reasoning.

    Returns the new rule, or None when the feedback was about that card only."""
    text = agents.prompt(
        "refine_rule",
        rule=job["rule"],
        before=json.dumps(card_before, ensure_ascii=False),
        after=json.dumps(card_after_job, ensure_ascii=False),
        feedback=feedback,
    )
    reply = agents.ask(cfg.agent, text, timeout=300).strip()
    new_rule = reply.splitlines()[-1].strip().strip('"') if reply else ""
    if not new_rule or new_rule.upper() == "SAME" or new_rule == job["rule"]:
        return None
    _replace_rule(job["rule"], new_rule)

    def requeue(j: dict) -> None:
        j["rule"], j["version"] = new_rule, j["version"] + 1
        j["queue"] = j["queue"] + [n for n in j["changed"] if n not in j["queue"][j["next"] :]]
        j["status"] = RUNNING

    _update(job["id"], requeue)
    return new_rule


def _replace_rule(old: str, new: str) -> None:
    path = config.rules_path()
    lines = path.read_text().splitlines() if path.exists() else []
    replaced = [f"- {new}" if line.strip().lstrip("- ").strip() == old else line for line in lines]
    if replaced == lines:
        review.save_rule(new)
    else:
        path.write_text("\n".join(replaced) + "\n")


def undo(cfg: Config, anki, job_id: str) -> int:
    """Put back every card this job changed, from the oldest backup of each. Returns how many."""
    path = _backups_path()
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    first: dict[int, dict] = {}
    for line in lines:
        if line["job"] == job_id and line["note_id"] not in first:
            first[line["note_id"]] = line["fields"]
    from . import bridge

    for note_id, fields in first.items():
        bridge.note_written(note_id)
        anki.update_fields(note_id, fields)
        anki.invoke("removeTags", notes=[note_id], tags=f"ah::rule::{job_id}")
    _update(job_id, lambda j: j.update(status=DONE, undone=True))
    return len(first)
