"""Server-side transcription adapters. No credentials are serialized."""

import base64
import os
from pathlib import Path

import requests

DEMO_PROVIDERS = [
    {
        "id": "demo-a",
        "name": "小艺 · 演示",
        "kind": "demo",
        "model": "demo-v1",
        "text": "Tolong book meeting room pukul tiga.",
    },
    {
        "id": "demo-b",
        "name": "对比模型 · 演示",
        "kind": "demo",
        "model": "demo-v2",
        "text": "Tolong book meeting room pukul dua.",
    },
]


def transcribe(snapshot: dict, path: Path, language: str) -> str:
    """Dispatch a normalized audio clip using its immutable provider snapshot."""
    if snapshot["kind"] == "demo":
        return snapshot["text"]
    if snapshot["kind"] == "qwen_asr":
        return transcribe_qwen(snapshot, path, language)
    if snapshot["kind"] == "fun_asr":
        return transcribe_fun(snapshot, path, language)
    if snapshot["kind"] != "openai_compatible":
        raise ValueError("unsupported provider")
    key = os.environ.get(snapshot.get("key_env", ""), "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = dict(snapshot.get("params", {}))
    data.update(model=snapshot["model"], response_format="json")
    # Mixed-language hints vary by provider; never silently force the first language.
    if (
        language != "auto"
        and "+" not in language
        and snapshot.get("send_language", True)
    ):
        data["language"] = language
    with open(path, "rb") as audio:
        response = requests.post(
            snapshot["url"],
            headers=headers,
            data=data,
            files={"file": ("clip.wav", audio, "audio/wav")},
            timeout=(10, 150),
            allow_redirects=False,
        )
    response.raise_for_status()
    text = response.json().get("text")
    if not isinstance(text, str):
        raise ValueError("provider returned no text")
    return text


def transcribe_qwen(snapshot: dict, path: Path, language: str) -> str:
    """Transcribe normalized WAV audio through Qwen's chat completions API."""
    key_env = snapshot.get("key_env", "DASHSCOPE_API_KEY")
    key = os.environ.get(key_env, "")
    if not key:
        raise ValueError(f"请在服务端配置环境变量 {key_env} 后重启服务")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    payload = dict(snapshot.get("params", {}))
    options = dict(payload.get("asr_options", {}))
    options.pop("language", None)
    if (
        language != "auto"
        and "+" not in language
        and snapshot.get("send_language", True)
    ):
        options["language"] = "fil" if language == "tl" else language
    payload.update(
        model=snapshot["model"],
        stream=False,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": f"data:audio/wav;base64,{encoded}"},
                    }
                ],
            }
        ],
        asr_options=options,
    )
    response = requests.post(
        snapshot["url"],
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=(10, 150),
        allow_redirects=False,
    )
    response.raise_for_status()
    try:
        text = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("provider returned no text") from error
    if not isinstance(text, str):
        raise ValueError("provider returned no text")
    return text


def transcribe_fun(snapshot: dict, path: Path, language: str) -> str:
    """Transcribe normalized WAV audio using the Fun-ASR DashScope protocol."""
    key_env = snapshot.get("key_env", "DASHSCOPE_API_KEY")
    key = os.environ.get(key_env, "")
    if not key:
        raise ValueError(f"请在服务端配置环境变量 {key_env} 后重启服务")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    parameters = dict(snapshot.get("params", {}))
    parameters.pop("language_hints", None)
    parameters.update(format="wav", sample_rate="16000")
    if (
        language != "auto"
        and "+" not in language
        and snapshot.get("send_language", True)
    ):
        parameters["language_hints"] = [language]
    response = requests.post(
        snapshot["url"],
        headers={"Authorization": f"Bearer {key}", "X-DashScope-SSE": "disable"},
        json={
            "model": snapshot["model"],
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": f"data:audio/wav;base64,{encoded}"
                                },
                            }
                        ],
                    }
                ]
            },
            "parameters": parameters,
        },
        timeout=(10, 150),
        allow_redirects=False,
    )
    response.raise_for_status()
    try:
        text = response.json()["output"]["text"]
    except (KeyError, TypeError) as error:
        raise ValueError("provider returned no text") from error
    if not isinstance(text, str):
        raise ValueError("provider returned no text")
    return text
