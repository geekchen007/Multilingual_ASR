"""Run all providers against the same persisted audio clip."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask

from .database import database
from .providers import transcribe


def run_test(app: Flask, test_id: str) -> None:
    """Persist independent provider results and the aggregate test status."""
    with database(app) as db:
        test = dict(db.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone())
        results = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM results WHERE test_id=? ORDER BY slot", (test_id,)
            )
        ]
        db.execute("UPDATE tests SET status='running' WHERE id=?", (test_id,))

    def run_result(result):
        started = time.monotonic()
        with database(app) as db:
            db.execute(
                "UPDATE results SET status='running' WHERE id=?", (result["id"],)
            )
        try:
            text = transcribe(
                json.loads(result["snapshot"]),
                app.config["DATA"] / test["audio"],
                test["language"],
            )
            status, error = "completed", ""
        except Exception:
            app.logger.warning("Transcription failed for result %s", result["id"])
            text, status, error = (
                "",
                "failed",
                "模型调用失败，请检查服务器配置、网络或配额后重测",
            )
        with database(app) as db:
            db.execute(
                "UPDATE results SET text=?,status=?,error=?,elapsed=? WHERE id=?",
                (
                    text,
                    status,
                    error,
                    round(time.monotonic() - started, 3),
                    result["id"],
                ),
            )

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run_result, results))
    with database(app) as db:
        completed = db.execute(
            "SELECT count(*) FROM results WHERE test_id=? AND status='completed'",
            (test_id,),
        ).fetchone()[0]
        status = (
            "completed"
            if completed == len(results)
            else "partial"
            if completed
            else "failed"
        )
        db.execute("UPDATE tests SET status=? WHERE id=?", (status, test_id))
