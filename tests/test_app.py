import hashlib
import io
import json
import wave
from pathlib import Path

import pytest

from asr_eval import create_app
from asr_eval.database import add_user, database


def audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 32000)
    output.seek(0)
    return output


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_PROVIDERS", str(tmp_path / "no-providers.json"))
    app = create_app(tmp_path, testing=True)
    add_user(app, "beta", "beta-password", "beta")
    add_user(app, "other", "other-password", "beta")
    add_user(app, "dev", "dev-password", "research")
    return app


def login(app, name="beta"):
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as session:
        token = session["csrf"]
    assert (
        client.post(
            "/login",
            data={"username": name, "password": name + "-password", "csrf": token},
        ).status_code
        == 302
    )
    with client.session_transaction() as session:
        token = session["csrf"]
    return client, {"X-CSRF-Token": token}


def submit(client, headers, **extra):
    data = {
        "title": "马英测试",
        "language": "ms+en",
        "models": ["demo-a", "demo-b"],
        "blind": "1",
        "file": (audio(), "sample.wav"),
    }
    data.update(extra)
    response = client.post("/api/tests", data=data, headers=headers)
    assert response.status_code == 201, response.json
    return response.json["id"]


def test_history_blind_and_isolation(platform):
    client, headers = login(platform)
    test_id = submit(client, headers)
    detail = client.get(f"/api/tests/{test_id}").json
    assert detail["status"] == "completed"
    assert all(
        "provider" not in result and "snapshot" not in result
        for result in detail["results"]
    )
    assert len(client.get("/api/tests").json) == 1
    vote = client.post(
        f"/api/tests/{test_id}/vote", json={"choice": "both_bad"}, headers=headers
    )
    assert vote.status_code == 200
    assert "provider" in client.get(f"/api/tests/{test_id}").json["results"][0]
    other, other_headers = login(platform, "other")
    assert other.get(f"/api/tests/{test_id}").status_code == 404
    assert other.get(f"/api/tests/{test_id}/audio").status_code == 404
    assert (
        other.post(f"/api/tests/{test_id}/rerun", headers=other_headers).status_code
        == 404
    )
    assert other.get("/api/tests").json == []
    assert client.post(f"/api/tests/{test_id}/rerun").status_code == 400


def test_case_review_conflict_and_demo_exclusion(platform):
    beta, headers = login(platform)
    test_id = submit(beta, headers)
    payload = {
        "types": ["数字时间"],
        "start": 0,
        "end": 1,
        "reference": "pukul dua",
        "selected_text": "tiga",
    }
    response = beta.post(f"/api/tests/{test_id}/cases", json=payload, headers=headers)
    assert response.status_code == 201
    case_id = response.json["id"]
    assert (
        beta.patch(f"/api/cases/{case_id}", json={}, headers=headers).status_code == 403
    )
    dev, dev_headers = login(platform, "dev")
    review = {
        "revision": 0,
        "status": "已确认",
        "owner": "语音研发",
        "reference_reviewed": "pukul dua",
        "root_cause": "ITN",
    }
    assert (
        dev.patch(f"/api/cases/{case_id}", json=review, headers=dev_headers).status_code
        == 200
    )
    assert (
        dev.patch(f"/api/cases/{case_id}", json=review, headers=dev_headers).status_code
        == 409
    )
    assert len(dev.get("/api/cases").json[0]["events"]) == 1
    assert dev.get("/api/regression").json == []
    assert beta.get("/api/regression").status_code == 403
    assert dev.get("/api/stats").json["real_tests"] == 0
    invalid = dict(payload, end=99)
    assert (
        beta.post(
            f"/api/tests/{test_id}/cases", json=invalid, headers=headers
        ).status_code
        == 400
    )


def test_link_attach_crop_and_rerun(platform):
    client, headers = login(platform)
    response = client.post(
        "/api/tests",
        data={
            "url": "https://www.bilibili.com/video/BV123",
            "start": "0.5",
            "end": "1.5",
            "models": ["demo-a"],
        },
        headers=headers,
    )
    assert response.status_code == 201
    test_id = response.json["id"]
    assert client.get(f"/api/tests/{test_id}").json["status"] == "awaiting_audio"
    attach = client.post(
        f"/api/tests/{test_id}/audio",
        data={"file": (audio(), "sample.wav")},
        headers=headers,
    )
    assert attach.status_code == 200
    detail = client.get(f"/api/tests/{test_id}").json
    assert detail["duration"] == pytest.approx(1, abs=0.01)
    rerun = client.post(f"/api/tests/{test_id}/rerun", headers=headers)
    assert rerun.status_code == 201
    assert client.get(f"/api/tests/{rerun.json['id']}").json["parent_id"] == test_id
    assert (
        client.post(
            "/api/tests",
            data={
                "url": "https://bilibili.com.evil.test/video/x",
                "models": ["demo-a"],
            },
            headers=headers,
        ).status_code
        == 400
    )


def test_invalid_audio_and_invalid_models(platform):
    client, headers = login(platform)
    response = client.post(
        "/api/tests",
        data={"models": ["demo-a"], "file": (io.BytesIO(b"bad"), "bad.wav")},
        headers=headers,
    )
    assert response.status_code == 400
    assert client.get("/api/tests").json == []
    assert (
        client.post(
            "/api/tests",
            data={"models": ["unavailable"], "file": (audio(), "x.wav")},
            headers=headers,
        ).status_code
        == 400
    )


def test_partial_provider_failure(platform, monkeypatch):
    import asr_eval.evaluation as module

    original = module.transcribe

    def fail_one(snapshot, path, language):
        if snapshot["id"] == "demo-b":
            raise ValueError("failure")
        return original(snapshot, path, language)

    monkeypatch.setattr(module, "transcribe", fail_one)
    client, headers = login(platform)
    detail = client.get(f"/api/tests/{submit(client, headers)}").json
    assert detail["status"] == "partial"
    assert {r["status"] for r in detail["results"]} == {"completed", "failed"}


def test_real_regression_and_restart(platform, monkeypatch):
    import asr_eval.evaluation as module

    platform.config["PROVIDERS"]["real"] = {
        "id": "real",
        "name": "真实接口桩",
        "kind": "openai_compatible",
        "model": "test-v1",
    }
    monkeypatch.setattr(
        module, "transcribe", lambda snapshot, path, language: "reference"
    )
    client, headers = login(platform)
    test_id = submit(client, headers, models=["real"])
    response = client.post(
        f"/api/tests/{test_id}/cases",
        headers=headers,
        json={"types": ["错字"], "end": 1},
    )
    case_id = response.json["id"]
    dev, dev_headers = login(platform, "dev")
    response = dev.patch(
        f"/api/cases/{case_id}",
        headers=dev_headers,
        json={
            "revision": 0,
            "status": "已确认",
            "reference_reviewed": "reference",
            "regression": True,
        },
    )
    assert response.status_code == 200
    assert dev.get("/api/regression").json[0]["audio_url"].endswith(f"{test_id}/audio")
    from asr_eval.database import database

    with database(platform) as db:
        db.execute("UPDATE tests SET status='running' WHERE id=?", (test_id,))
        db.execute("UPDATE results SET status='running' WHERE test_id=?", (test_id,))
    administrative = create_app(platform.config["DATA"], testing=True, recover=False)
    with database(administrative) as db:
        assert (
            db.execute("SELECT status FROM tests WHERE id=?", (test_id,)).fetchone()[0]
            == "running"
        )
    restarted = create_app(platform.config["DATA"], testing=True)
    restored, _ = login(restarted)
    assert restored.get(f"/api/tests/{test_id}").json["status"] == "failed"
    assert len(restored.get("/api/tests").json) == 1


def test_duplicate_case_and_validation(platform):
    client, headers = login(platform)
    test_id = submit(client, headers)
    ids = [
        client.post(
            f"/api/tests/{test_id}/cases",
            headers=headers,
            json={"types": ["错字"], "end": 1},
        ).json["id"]
        for _ in range(2)
    ]
    dev, dh = login(platform, "dev")
    assert (
        dev.patch(
            "/api/cases/" + ids[1],
            headers=dh,
            json={"revision": 0, "status": "重复", "duplicate_of": ids[0]},
        ).status_code
        == 200
    )
    assert (
        dev.patch(
            "/api/cases/" + ids[0],
            headers=dh,
            json={"revision": 0, "status": "重复", "duplicate_of": ids[1]},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/tests/{test_id}/cases",
            headers=headers,
            json={"types": ["未知类型"], "end": 1},
        ).status_code
        == 400
    )


def test_provider_protocol_and_same_audio(platform, monkeypatch):
    import asr_eval.providers as providers
    from asr_eval.providers import transcribe

    payloads = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "recognized"}

    def post(url, **kwargs):
        payloads.append((kwargs["files"]["file"][1].read(), kwargs["data"]))
        return Response()

    monkeypatch.setattr(providers.requests, "post", post)
    path = platform.config["DATA"] / "test.wav"
    path.write_bytes(audio().read())
    snapshot = {
        "kind": "openai_compatible",
        "model": "test",
        "url": "https://example.test/transcribe",
    }
    assert transcribe(snapshot, path, "ms+en") == "recognized"
    assert transcribe(snapshot, path, "en") == "recognized"
    assert payloads[0][0] == payloads[1][0]
    assert "language" not in payloads[0][1]
    assert payloads[1][1]["language"] == "en"


def test_invalid_json_body_returns_client_error(platform):
    client, headers = login(platform)
    test_id = submit(client, headers)
    for endpoint in ("vote", "cases"):
        response = client.post(
            f"/api/tests/{test_id}/{endpoint}", json=[], headers=headers
        )
        assert response.status_code == 400
    dev, dh = login(platform, "dev")
    assert dev.patch("/api/cases/unknown", json=[], headers=dh).status_code == 400


def test_public_sample_preview_submit_rerun_and_isolation(platform):
    client, headers = login(platform)
    samples = client.get("/api/config").json["samples"]
    assert len({sample["dataset"] for sample in samples}) >= 3
    sample = samples[0]
    preview = client.get(f"/api/samples/{sample['id']}/audio")
    assert preview.status_code == 200
    assert preview.mimetype == "audio/wav"
    assert preview.data[:4] == b"RIFF"
    response = client.post(
        "/api/tests",
        data={
            "sample_id": sample["id"],
            "models": ["demo-a"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.json
    test_id = response.json["id"]
    detail = client.get(f"/api/tests/{test_id}").json
    assert detail["status"] == "completed"
    assert detail["sample_id"] == sample["id"]
    assert detail["sample"]["reference"] == sample["reference"]
    assert detail["language"] == sample["language"]
    assert detail["duration"] == pytest.approx(sample["duration"], abs=0.02)
    rerun = client.post(f"/api/tests/{test_id}/rerun", headers=headers)
    assert rerun.status_code == 201
    repeated = client.get(f"/api/tests/{rerun.json['id']}").json
    assert repeated["sample_id"] == sample["id"]
    assert repeated["parent_id"] == test_id
    other, _ = login(platform, "other")
    assert other.get(f"/api/tests/{test_id}").status_code == 404
    assert other.get("/api/tests").json == []
    assert other.get(f"/api/samples/{sample['id']}/audio").status_code == 200
    assert (
        platform.test_client().get(f"/api/samples/{sample['id']}/audio").status_code
        == 401
    )


def test_public_sample_validation(platform):
    client, headers = login(platform)
    sample = client.get("/api/config").json["samples"][0]
    for sample_id in ("unknown", "../../data/session.key"):
        response = client.post(
            "/api/tests",
            data={
                "sample_id": sample_id,
                "models": ["demo-a"],
            },
            headers=headers,
        )
        assert response.status_code == 400
    assert client.get("/api/samples/unknown/audio").status_code == 404
    for extra in (
        {"file": (audio(), "sample.wav")},
        {"url": "https://www.youtube.com/watch?v=test"},
    ):
        response = client.post(
            "/api/tests",
            data={
                "sample_id": sample["id"],
                "models": ["demo-a"],
                **extra,
            },
            headers=headers,
        )
        assert response.status_code == 400
    assert client.get("/api/tests").json == []


def test_bundled_samples_integrity():
    root = Path(__file__).resolve().parents[1] / "samples"
    samples = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert {"zh", "en", "ja", "ms"} <= {row["language"] for row in samples}
    assert len({row["id"] for row in samples}) == len(samples)
    for row in samples:
        path = root / "audio" / f"{row['id']}.wav"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        assert row["reference"] and row["attribution"] and row["source_id"]
        assert row["license_url"].startswith("https://")
        with wave.open(str(path), "rb") as stream:
            assert stream.getnchannels() == 1
            assert stream.getframerate() == 16000
            assert stream.getsampwidth() == 2
            assert stream.getnframes() / 16000 == pytest.approx(
                row["duration"],
                abs=0.01,
            )


def test_public_sample_crops_and_calls_provider(platform, monkeypatch):
    calls = []

    def recognize(snapshot, path, language):
        with wave.open(str(path), "rb") as stream:
            calls.append((language, stream.getnframes() / stream.getframerate()))
        return "recognized from audio"

    monkeypatch.setattr("asr_eval.evaluation.transcribe", recognize)
    client, headers = login(platform)
    sample = client.get("/api/config").json["samples"][0]
    response = client.post(
        "/api/tests",
        data={
            "sample_id": sample["id"],
            "models": ["demo-a"],
            "start": "0.5",
            "end": "1.5",
            "language": "auto",
        },
        headers=headers,
    )
    assert response.status_code == 201
    detail = client.get(f"/api/tests/{response.json['id']}").json
    assert calls == [("auto", 1.0)]
    assert detail["results"][0]["text"] == "recognized from audio"
    assert detail["sample"]["reference"] == sample["reference"]


def test_sample_column_migrates_existing_database(platform):
    client, headers = login(platform)
    test_id = submit(client, headers)
    with database(platform) as db:
        db.execute("ALTER TABLE tests DROP COLUMN sample_id")
    reopened = create_app(platform.config["DATA"], testing=True, recover=False)
    restored, _ = login(reopened)
    detail = restored.get(f"/api/tests/{test_id}").json
    assert detail["sample_id"] == ""
    assert detail["sample"] is None
    assert detail["status"] == "completed"
    assert restored.get(f"/api/tests/{test_id}/audio").status_code == 200


@pytest.mark.parametrize("fail_second", [False, True])
def test_two_asr_models_receive_identical_sample(platform, monkeypatch, fail_second):
    for provider_id, kind in (("qwen-asr", "qwen_asr"), ("fun-asr", "fun_asr")):
        platform.config["PROVIDERS"][provider_id] = {
            "id": provider_id,
            "name": provider_id,
            "kind": kind,
            "model": provider_id,
        }
    calls = []

    def recognize(snapshot, path, language):
        calls.append((snapshot["id"], hashlib.sha256(path.read_bytes()).hexdigest()))
        if fail_second and snapshot["id"] == "fun-asr":
            raise ValueError("provider unavailable")
        return snapshot["id"] + " recognition"

    monkeypatch.setattr("asr_eval.evaluation.transcribe", recognize)
    client, headers = login(platform)
    sample = client.get("/api/config").json["samples"][0]
    response = client.post(
        "/api/tests",
        data={
            "sample_id": sample["id"],
            "models": ["qwen-asr", "fun-asr"],
        },
        headers=headers,
    )
    assert response.status_code == 201
    detail = client.get(f"/api/tests/{response.json['id']}").json
    assert detail["status"] == ("partial" if fail_second else "completed")
    assert len(detail["results"]) == 2
    assert {provider_id for provider_id, digest in calls} == {"qwen-asr", "fun-asr"}
    assert {digest for provider_id, digest in calls} == {detail["sha256"]}
    assert any(result["text"] == "qwen-asr recognition" for result in detail["results"])
