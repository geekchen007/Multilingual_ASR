"""Flask application factory, authentication and evaluation routes."""

import json
import math
import os
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
)
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .audio import normalize_audio
from .constants import (
    CONDITIONS,
    FEATURES,
    IMPACTS,
    LANGUAGES,
    PROJECT_ROOT,
    SCENES,
    STATUSES,
    TYPES,
)
from .database import database, initialize_database
from .evaluation import run_test
from .providers import DEMO_PROVIDERS


def now() -> str:
    """Return an ISO-formatted UTC timestamp for persisted events."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def number(value, default=0) -> float:
    """Parse nonnegative finite seconds or reject the request."""
    try:
        result = float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        abort(400, "时间必须为秒数")
    if not math.isfinite(result) or result < 0:
        abort(400, "时间必须为有限非负数")
    return result


def create_app(
    data_dir: str | Path | None = None, testing: bool = False, recover: bool = True
) -> Flask:
    """Create the Flask application without starting a server."""
    app = Flask(__name__)
    data = Path(
        data_dir or os.environ.get("ASR_DATA_DIR", PROJECT_ROOT / "data")
    ).resolve()
    data.mkdir(parents=True, exist_ok=True)
    secret = data / "session.key"
    if not secret.exists():
        secret.write_text(secrets.token_hex(32))
    app.config.update(
        DATA=data,
        DB=str(data / "platform.sqlite"),
        SECRET_KEY=secret.read_text(),
        TESTING=testing,
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("ASR_HTTPS") == "1",
    )
    config_path = Path(
        os.environ.get("ASR_PROVIDERS", PROJECT_ROOT / "config" / "providers.json")
    )
    providers = (
        json.loads(config_path.read_text("utf-8"))
        if config_path.exists()
        else DEMO_PROVIDERS
    )
    app.config["PROVIDERS"] = {item["id"]: item for item in providers}
    samples_dir = PROJECT_ROOT / "samples"
    samples = json.loads((samples_dir / "manifest.json").read_text("utf-8"))
    sample_by_id = {sample["id"]: sample for sample in samples}
    app.extensions["jobs"] = ThreadPoolExecutor(max_workers=4)
    app.extensions["submit_lock"] = threading.Lock()
    initialize_database(app, recover)

    @app.before_request
    def authenticate():
        session.setdefault("csrf", secrets.token_hex(24))
        with database(app) as db:
            g.user = db.execute(
                "SELECT id,name,role FROM users WHERE id=?", (session.get("uid"),)
            ).fetchone()
        if request.method in ("POST", "PATCH", "DELETE"):
            token = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
            if not secrets.compare_digest(str(token), session["csrf"]):
                abort(400, "页面已过期，请刷新后重试")
        if request.endpoint not in ("login", "static") and not g.user:
            if request.path.startswith("/api/"):
                abort(401, "请先登录")
            return redirect("/login")

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def error_response(error):
        return jsonify(error=error.description), error.code

    def research():
        if g.user["role"] != "research":
            abort(403, "需要研发权限")

    def json_object():
        body = request.get_json()
        if not isinstance(body, dict):
            abort(400, "请求内容必须为 JSON 对象")
        return body

    def owned_test(test_id):
        with database(app) as db:
            row = db.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
        if row is None or (
            g.user["role"] != "research" and row["user_id"] != g.user["id"]
        ):
            abort(404, "测试不存在")
        return dict(row)

    def enqueue(test_id):
        if testing:
            run_test(app, test_id)
        else:
            app.extensions["jobs"].submit(run_test, app, test_id)

    def check_capacity(db):
        if (
            db.execute(
                "SELECT count(*) FROM tests WHERE status IN ('queued','running')"
            ).fetchone()[0]
            >= 40
        ):
            abort(429, "任务较多，请稍后再试")

    def create_test(values, snapshots):
        test_id = uuid.uuid4().hex[:12]
        with app.extensions["submit_lock"]:
            with database(app) as db:
                check_capacity(db)
                values.update(id=test_id, user_id=g.user["id"], created=now())
                columns = ",".join(values)
                db.execute(
                    f"INSERT INTO tests({columns}) VALUES({','.join('?' for _ in values)})",
                    tuple(values.values()),
                )
                secrets.SystemRandom().shuffle(snapshots)
                for slot, snapshot in enumerate(snapshots):
                    db.execute(
                        (
                            "INSERT INTO "
                            "results(id,test_id,slot,provider,snapshot,demo,status) "
                            "VALUES(?,?,?,?,?,?,?)"
                        ),
                        (
                            uuid.uuid4().hex,
                            test_id,
                            slot,
                            snapshot["name"],
                            json.dumps(snapshot, ensure_ascii=False),
                            int(snapshot["kind"] == "demo"),
                            "queued" if values.get("audio") else "awaiting_audio",
                        ),
                    )
        if values.get("audio"):
            enqueue(test_id)
        return test_id

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            with database(app) as db:
                user = db.execute(
                    "SELECT * FROM users WHERE name=?",
                    (request.form.get("username", ""),),
                ).fetchone()
            if user and check_password_hash(
                user["password"], request.form.get("password", "")
            ):
                session.clear()
                session.update(uid=user["id"], csrf=secrets.token_hex(24))
                return redirect("/")
            error = "用户名或密码错误"
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    def index():
        return render_template("index.html", user=dict(g.user))

    @app.get("/api/config")
    def configuration():
        return jsonify(
            types=TYPES,
            features=FEATURES,
            conditions=CONDITIONS,
            impacts=IMPACTS,
            statuses=STATUSES,
            languages=LANGUAGES,
            scenes=SCENES,
            samples=samples,
            models=[
                {"id": p["id"], "name": p["name"], "demo": p["kind"] == "demo"}
                for p in providers
            ],
        )

    @app.get("/api/samples/<sample_id>/audio")
    def sample_audio(sample_id):
        if sample_id not in sample_by_id:
            abort(404, "示例音频不存在")
        return send_file(
            samples_dir / "audio" / f"{sample_id}.wav",
            mimetype="audio/wav",
            conditional=True,
        )

    @app.route("/api/tests", methods=["GET", "POST"])
    def tests():
        if request.method == "GET":
            clauses, params = [], []
            if g.user["role"] != "research":
                clauses.append("t.user_id=?")
                params.append(g.user["id"])
            for key in ("language", "status"):
                if request.args.get(key):
                    clauses.append(f"t.{key}=?")
                    params.append(request.args[key])
            if request.args.get("q"):
                clauses.append("(t.title LIKE ? OR t.id LIKE ?)")
                params.extend(["%" + request.args["q"] + "%"] * 2)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            with database(app) as db:
                rows = db.execute(
                    (
                        "SELECT "
                        "t.id,t.title,t.language,t.status,t.created,t.url,t.blind,t.parent_id,t.sample_id,u.name"
                        " username,(SELECT count(*) FROM cases c WHERE "
                        "c.test_id=t.id) annotations,(SELECT max(demo) FROM results r"
                        " WHERE r.test_id=t.id) demo FROM tests t JOIN users u ON "
                        "u.id=t.user_id"
                    )
                    + where
                    + " ORDER BY t.created DESC,t.rowid DESC",
                    params,
                ).fetchall()
            return jsonify([dict(row) for row in rows])
        selected = request.form.getlist("models")
        if (
            not 1 <= len(selected) <= 3
            or len(set(selected)) != len(selected)
            or any(model not in app.config["PROVIDERS"] for model in selected)
        ):
            abort(400, "请选择 1—3 个可用模型")
        sample_id = request.form.get("sample_id", "")
        sample = sample_by_id.get(sample_id)
        if sample_id and not sample:
            abort(400, "请选择一个有效的公开示例")
        if sample and (request.files.get("file") or request.form.get("url")):
            abort(400, "公开示例、上传文件和视频链接只能选择一种来源")
        language = request.form.get(
            "language", sample["language"] if sample else "auto"
        )
        scene = request.form.get("scene", "未指定")
        if language not in LANGUAGES or scene not in SCENES:
            abort(400, "语言或场景不正确")
        start = number(request.form.get("start"))
        end = number(request.form.get("end")) if request.form.get("end") else None
        if end is not None and (end <= start or end - start > 120):
            abort(400, "选段结束时间应大于起点，长度不超过 120 秒")
        url = request.form.get("url", "").strip()
        if url:
            parsed = urlsplit(url)
            if (
                len(url) > 2000
                or parsed.scheme not in ("https", "http")
                or parsed.hostname
                not in (
                    "bilibili.com",
                    "www.bilibili.com",
                    "b23.tv",
                    "youtube.com",
                    "www.youtube.com",
                    "m.youtube.com",
                    "youtu.be",
                )
                or parsed.username
            ):
                abort(400, "请使用 B 站或 YouTube 视频链接")
        audio, duration, sha256 = None, 0, ""
        if sample:
            sample_path = samples_dir / "audio" / f"{sample_id}.wav"
            with sample_path.open("rb") as stream:
                upload = FileStorage(stream, filename=sample_path.name)
                audio, duration, sha256 = normalize_audio(app, upload, start, end)
        elif request.files.get("file"):
            audio, duration, sha256 = normalize_audio(
                app, request.files["file"], start, end
            )
        elif not url:
            abort(400, "请选择公开示例、上传文件、录音或提供视频链接")
        default_title = f"公开示例 · {sample['title']}" if sample else "未命名测试"
        values = dict(
            title=request.form.get("title", "").strip()[:160] or default_title,
            url=url,
            language=language,
            scene=scene,
            start=start,
            end=end,
            audio=audio,
            duration=duration,
            sha256=sha256,
            status="queued" if audio else "awaiting_audio",
            blind=int(request.form.get("blind") == "1"),
            sample_id=sample_id,
        )
        try:
            test_id = create_test(
                values, [dict(app.config["PROVIDERS"][key]) for key in selected]
            )
        except Exception:
            if audio:
                (data / audio).unlink(missing_ok=True)
            raise
        return jsonify(id=test_id), 201

    @app.get("/api/tests/<test_id>")
    def detail(test_id):
        item = owned_test(test_id)
        with database(app) as db:
            vote = db.execute(
                "SELECT choice FROM votes WHERE test_id=? AND user_id=?",
                (test_id, g.user["id"]),
            ).fetchone()
            results = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM results WHERE test_id=? ORDER BY slot", (test_id,)
                )
            ]
        revealed = not item["blind"] or bool(vote) or g.user["role"] == "research"
        for result in results:
            result["label"] = chr(65 + result["slot"])
            if revealed:
                snapshot = json.loads(result["snapshot"])
                result["snapshot"] = {
                    key: snapshot[key]
                    for key in ("model", "kind", "params", "send_language")
                    if key in snapshot
                }
            else:
                result.pop("provider")
                result.pop("snapshot")
        item.pop("audio")
        return jsonify(
            **item,
            sample=sample_by_id.get(item["sample_id"]),
            results=results,
            revealed=revealed,
            vote=vote["choice"] if vote else None,
        )

    @app.route("/api/tests/<test_id>/audio", methods=["GET", "POST"])
    def audio_route(test_id):
        item = owned_test(test_id)
        if request.method == "GET":
            if not item["audio"]:
                abort(404, "待补充音频")
            return send_file(
                data / item["audio"], mimetype="audio/wav", conditional=True
            )
        if item["status"] != "awaiting_audio":
            abort(409, "已有音频，请通过重测创建新记录")
        audio, duration, digest = normalize_audio(
            app, request.files.get("file"), item["start"], item["end"]
        )
        try:
            with app.extensions["submit_lock"]:
                with database(app) as db:
                    check_capacity(db)
                    changed = db.execute(
                        (
                            "UPDATE tests SET "
                            "audio=?,duration=?,sha256=?,status='queued' WHERE id=? "
                            "AND status='awaiting_audio'"
                        ),
                        (audio, duration, digest, test_id),
                    ).rowcount
                    if not changed:
                        abort(409, "此记录已补充音频")
                    db.execute(
                        "UPDATE results SET status='queued' WHERE test_id=?", (test_id,)
                    )
        except Exception:
            (data / audio).unlink(missing_ok=True)
            raise
        enqueue(test_id)
        return jsonify(ok=True)

    @app.post("/api/tests/<test_id>/rerun")
    def rerun(test_id):
        item = owned_test(test_id)
        if not item["audio"]:
            abort(400, "请先补充音频")
        with database(app) as db:
            old = [
                json.loads(row["snapshot"])
                for row in db.execute(
                    "SELECT snapshot FROM results WHERE test_id=?", (test_id,)
                )
            ]
        snapshots = []
        for previous in old:
            if previous["id"] not in app.config["PROVIDERS"]:
                abort(400, "原模型已下线，请在在线测评重新选择")
            snapshots.append(dict(app.config["PROVIDERS"][previous["id"]]))
        values = {
            key: item[key]
            for key in (
                "title",
                "url",
                "language",
                "scene",
                "start",
                "end",
                "audio",
                "duration",
                "sha256",
                "blind",
                "sample_id",
            )
        }
        values.update(parent_id=test_id, status="queued")
        return jsonify(id=create_test(values, snapshots)), 201

    @app.post("/api/tests/<test_id>/vote")
    def vote(test_id):
        item = owned_test(test_id)
        if item["status"] not in ("completed", "partial"):
            abort(400, "请等待识别完成")
        choice = json_object().get("choice")
        with database(app) as db:
            valid = [
                chr(65 + r["slot"])
                for r in db.execute(
                    "SELECT slot FROM results WHERE test_id=? AND status='completed'",
                    (test_id,),
                )
            ]
            if choice not in valid + ["both_good", "both_bad", "skip"]:
                abort(400, "投票选项不正确")
            db.execute(
                (
                    "INSERT INTO votes VALUES(?,?,?,?) ON CONFLICT(test_id,user_id) "
                    "DO UPDATE SET choice=excluded.choice,created=excluded.created"
                ),
                (test_id, g.user["id"], choice, now()),
            )
        return jsonify(ok=True)

    @app.post("/api/tests/<test_id>/cases")
    def annotate(test_id):
        item = owned_test(test_id)
        body = json_object()
        types = body.get("types", [])
        if (
            not isinstance(types, list)
            or not types
            or any(t not in TYPES for t in types)
        ):
            abort(400, "请至少选择一个问题类型")
        if not item["audio"]:
            abort(400, "请先补充音频")
        start, end = (
            number(body.get("start")),
            number(body.get("end"), item["duration"]),
        )
        if end <= start or end > item["duration"] + 0.01:
            abort(400, "标注位置超出片段范围")
        for field, options in [
            ("feature", FEATURES),
            ("condition", CONDITIONS),
            ("impact", IMPACTS),
        ]:
            if body.get(field, "未知") not in options:
                abort(400, "分类选项不正确")
        case_id = uuid.uuid4().hex[:12]
        with database(app) as db:
            result_id = body.get("result_id") or None
            if (
                result_id
                and not db.execute(
                    "SELECT 1 FROM results WHERE id=? AND test_id=?",
                    (result_id, test_id),
                ).fetchone()
            ):
                abort(400, "模型结果与测试不匹配")
            db.execute(
                (
                    "INSERT INTO "
                    "cases(id,test_id,user_id,result_id,start,end,selected_text,reference,types,feature,condition,impact,note,created)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    case_id,
                    test_id,
                    g.user["id"],
                    result_id,
                    start,
                    end,
                    str(body.get("selected_text", ""))[:5000],
                    str(body.get("reference", ""))[:5000],
                    json.dumps(list(dict.fromkeys(types)), ensure_ascii=False),
                    body.get("feature", "未知"),
                    body.get("condition", "未知"),
                    body.get("impact", "未知"),
                    str(body.get("note", ""))[:2000],
                    now(),
                ),
            )
        return jsonify(id=case_id), 201

    def case_rows():
        with database(app) as db:
            rows = db.execute(
                (
                    "SELECT c.*,t.title,t.language,t.scene,t.url,(SELECT max(demo) "
                    "FROM results WHERE test_id=t.id) demo FROM cases c JOIN tests t "
                    "ON t.id=c.test_id"
                )
                + (" WHERE c.user_id=?" if g.user["role"] != "research" else "")
                + " ORDER BY c.created DESC,c.rowid DESC",
                (() if g.user["role"] == "research" else (g.user["id"],)),
            ).fetchall()
            output = []
            for row in rows:
                item = dict(row)
                item["types"] = json.loads(item["types"])
                item["events"] = [
                    dict(e)
                    for e in db.execute(
                        (
                            "SELECT e.body,e.created,u.name FROM events e JOIN users u ON"
                            " e.user_id=u.id WHERE case_id=? ORDER BY e.id"
                        ),
                        (item["id"],),
                    )
                ]
                output.append(item)
            return output

    @app.get("/api/cases")
    def cases():
        rows = case_rows()
        for key in ("language", "status", "feature", "impact"):
            if request.args.get(key):
                rows = [r for r in rows if r[key] == request.args[key]]
        if request.args.get("type"):
            rows = [r for r in rows if request.args["type"] in r["types"]]
        if request.args.get("q"):
            query = request.args["q"].lower()
            rows = [
                r for r in rows if query in json.dumps(r, ensure_ascii=False).lower()
            ]
        return jsonify(rows)

    @app.patch("/api/cases/<case_id>")
    def review(case_id):
        research()
        body = json_object()
        with database(app) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                abort(404, "Case 不存在")
            item = dict(row)
            if body.get("revision") != item["revision"]:
                abort(409, "此 Case 已被其他人修改，请刷新后重试")
            for key in (
                "status",
                "owner",
                "root_cause",
                "reference_reviewed",
                "duplicate_of",
            ):
                if key in body:
                    item[key] = str(body[key]).strip()[:5000]
            if item["status"] not in STATUSES:
                abort(400, "状态不正确")
            if item["status"] == "重复":
                target = db.execute(
                    "SELECT status FROM cases WHERE id=?", (item["duplicate_of"],)
                ).fetchone()
                if (
                    item["duplicate_of"] == case_id
                    or not target
                    or target["status"] == "重复"
                ):
                    abort(400, "请选择一个有效的主 Case")
                if db.execute(
                    "SELECT 1 FROM cases WHERE duplicate_of=? AND status=?",
                    (case_id, "重复"),
                ).fetchone():
                    abort(400, "此 Case 已是其他记录的主 Case，请先调整关联")
            else:
                item["duplicate_of"] = ""
            item["regression"] = int(bool(body.get("regression", item["regression"])))
            if item["regression"]:
                demo = db.execute(
                    "SELECT max(demo) FROM results WHERE test_id=?", (item["test_id"],)
                ).fetchone()[0]
                success = db.execute(
                    "SELECT 1 FROM results WHERE test_id=? AND status='completed' AND demo=0",
                    (item["test_id"],),
                ).fetchone()
                if (
                    item["status"] not in ("已确认", "处理中", "待验证", "已解决")
                    or not item["reference_reviewed"]
                    or demo
                    or not success
                ):
                    abort(400, "正式回归需要已确认的真实测试和研发参考文本")
            db.execute(
                (
                    "UPDATE cases SET "
                    "status=?,owner=?,root_cause=?,reference_reviewed=?,regression=?,duplicate_of=?,revision=revision+1"
                    " WHERE id=?"
                ),
                tuple(
                    item[k]
                    for k in (
                        "status",
                        "owner",
                        "root_cause",
                        "reference_reviewed",
                        "regression",
                        "duplicate_of",
                    )
                )
                + (case_id,),
            )
            audit = {
                key: {"from": row[key], "to": item[key]}
                for key in (
                    "status",
                    "owner",
                    "root_cause",
                    "reference_reviewed",
                    "regression",
                    "duplicate_of",
                )
                if row[key] != item[key]
            }
            db.execute(
                "INSERT INTO events(case_id,user_id,body,created) VALUES(?,?,?,?)",
                (case_id, g.user["id"], json.dumps(audit, ensure_ascii=False), now()),
            )
        return jsonify(ok=True)

    @app.get("/api/regression")
    def regression():
        research()
        rows = [r for r in case_rows() if r["regression"] and not r["demo"]]
        for item in rows:
            item["audio_url"] = f"/api/tests/{item['test_id']}/audio"
        response = jsonify(rows)
        response.headers["Content-Disposition"] = "attachment; filename=regression.json"
        return response

    @app.get("/api/stats")
    def stats():
        where = "" if g.user["role"] == "research" else " WHERE t.user_id=?"
        params = () if not where else (g.user["id"],)
        with database(app) as db:
            tests = [
                dict(r)
                for r in db.execute(
                    "SELECT t.*, (SELECT max(demo) FROM results WHERE test_id=t.id) demo FROM tests t"
                    + where,
                    params,
                )
            ]
            votes = [
                dict(r)
                for r in db.execute(
                    "SELECT v.choice,count(*) count FROM votes v JOIN tests t ON t.id=v.test_id"
                    + where
                    + " GROUP BY v.choice",
                    params,
                )
            ]
        cases = case_rows()
        language_counts = {
            LANGUAGES.get(lang, lang): sum(t["language"] == lang for t in tests)
            for lang in dict.fromkeys(t["language"] for t in tests)
        }
        return jsonify(
            tests=len(tests),
            real_tests=sum(not t["demo"] and bool(t["audio"]) for t in tests),
            demo_tests=sum(bool(t["demo"]) for t in tests),
            cases=len(cases),
            pending=sum(c["status"] == "待复核" for c in cases),
            regression=sum(c["regression"] for c in cases),
            languages=language_counts,
            types={kind: sum(kind in c["types"] for c in cases) for kind in TYPES},
            votes=votes,
        )

    return app
