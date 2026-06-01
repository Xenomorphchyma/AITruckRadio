# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config.json"
VOICES_DIR = BASE_DIR / "voices"
CACHE_DIR = BASE_DIR / "cache"

# Две русские модели Piper: мужская для Максима и женская для Ирины.
# Все ставится локально в папку проекта, без установки в Windows.
VOICES = {
    "ru_RU-ruslan-medium": {
        "folder": "ruslan",
        "host": "Максим",
    },
    "ru_RU-irina-medium": {
        "folder": "irina",
        "host": "Ирина",
    },
}
HF_ROOT = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU"


def log(msg: str) -> None:
    print(msg, flush=True)


def run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(BASE_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def download(url: str, target: Path) -> None:
    log(f"Downloading {target.name}...")
    with urllib.request.urlopen(url, timeout=180) as r:
        data = r.read()
    target.write_bytes(data)
    if target.stat().st_size < 1024:
        raise RuntimeError(f"Downloaded file looks too small: {target}")


def ensure_voice(voice: str, folder: str) -> None:
    VOICES_DIR.mkdir(exist_ok=True)
    onnx_name = f"{voice}.onnx"
    json_name = f"{voice}.onnx.json"
    onnx = VOICES_DIR / onnx_name
    meta = VOICES_DIR / json_name
    if onnx.exists() and meta.exists():
        log(f"{voice} is already present.")
        return

    log(f"Trying Piper built-in downloader for {voice}...")
    res = run([sys.executable, "-m", "piper.download_voices", voice, "--data-dir", str(VOICES_DIR)], timeout=600)
    if res.returncode == 0 and onnx.exists() and meta.exists():
        log(f"{voice} downloaded by piper.download_voices.")
        return

    if res.stdout.strip():
        log(res.stdout.strip())
    if res.stderr.strip():
        log(res.stderr.strip())
    log(f"Built-in downloader did not finish; using direct Hugging Face fallback for {voice}...")
    base_url = f"{HF_ROOT}/{folder}/medium"
    download(f"{base_url}/{onnx_name}?download=true", onnx)
    download(f"{base_url}/{json_name}?download=true", meta)


def ensure_voices() -> None:
    for voice, info in VOICES.items():
        ensure_voice(voice, info["folder"])


def patch_config() -> None:
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        cfg = {}
    cfg.update({
        "tts_backend": "piper",
        "piper_python": ".venv\\Scripts\\python.exe",
        "piper_voice": "ru_RU-ruslan-medium",
        "piper_data_dir": "voices",
        "piper_model": "voices/ru_RU-ruslan-medium.onnx",
        "piper_extra_args": [],
        "tts_dialogue_split_hosts": True,
        "tts_speak_host_names": False,
    })

    default_hosts = [
        {
            "name": "Максим",
            "aliases": ["Макс"],
            "persona": "спокойный дорожный ведущий, говорит тепло, уверенно и по делу, без лишней театральности",
            "piper_voice": "ru_RU-ruslan-medium",
            "piper_model": "voices/ru_RU-ruslan-medium.onnx",
            "silero_speaker": "aidar",
        },
        {
            "name": "Ирина",
            "aliases": ["Лина", "Ира"],
            "persona": "живая соведущая, добавляет лёгкий юмор, атмосферу дороги и короткие наблюдения",
            "piper_voice": "ru_RU-irina-medium",
            "piper_model": "voices/ru_RU-irina-medium.onnx",
            "silero_speaker": "xenia",
        },
    ]
    hosts = cfg.get("hosts")
    if not isinstance(hosts, list) or len(hosts) < 2:
        cfg["hosts"] = default_hosts
    else:
        for i, defaults in enumerate(default_hosts):
            if i < len(hosts) and isinstance(hosts[i], dict):
                if hosts[i].get("name") == "Макс":
                    hosts[i]["name"] = "Максим"
                if hosts[i].get("name") == "Лина":
                    hosts[i]["name"] = "Ирина"
                hosts[i].setdefault("name", defaults["name"])
                hosts[i].setdefault("aliases", defaults.get("aliases", []))
                hosts[i].setdefault("persona", defaults["persona"])
                hosts[i]["piper_voice"] = defaults["piper_voice"]
                hosts[i]["piper_model"] = defaults["piper_model"]
        cfg["hosts"] = hosts

    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    log("config.json switched to Piper with separate host voices.")


def test_voice(voice: str, text: str) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    out_wav = CACHE_DIR / f"piper_test_{voice}.wav"
    res = run([sys.executable, "-m", "piper", "-m", voice, "--data-dir", str(VOICES_DIR), "-f", str(out_wav), "--", text], timeout=180)
    if res.returncode != 0 or not out_wav.exists():
        if res.stdout.strip():
            log(res.stdout.strip())
        if res.stderr.strip():
            log(res.stderr.strip())
        raise RuntimeError(f"Piper test synthesis failed for {voice}.")
    log(f"Test WAV created: {out_wav}")


def test_piper() -> None:
    test_voice("ru_RU-ruslan-medium", "Проверка голоса Максима. В эфире AI Дальнобой FM.")
    test_voice("ru_RU-irina-medium", "Проверка голоса Ирины. Следующий трек уже выходит на трассу.")


def main() -> int:
    try:
        ensure_voices()
        patch_config()
        test_piper()
        log("Piper is ready.")
        return 0
    except Exception as e:
        log(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
