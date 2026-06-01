# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_truck_radio_app.config import (
    BASE_DIR,
    executable_exists,
    log,
    rel_path,
    run_subprocess,
)
from ai_truck_radio_app.text_processing import (
    host_aliases,
    parse_dialogue_segments,
    strip_spoken_host_names,
    trim_to_complete_sentence,
)


def host_name_or_empty(host_name: Optional[str]) -> str:
    return "" if host_name is None else str(host_name)


class Qwen3TTSWorkerClient:
    """Держит Qwen3-TTS загруженным одним процессом, чтобы не грузить модель заново на каждую реплику."""
    def __init__(self, owner: "TTS"):
        self.owner = owner
        self.proc: Optional[subprocess.Popen] = None
        self.stdout_q: "queue.Queue[str]" = queue.Queue()
        self.stderr_q: "queue.Queue[str]" = queue.Queue()
        self.lock = threading.RLock()
        self.started_key = ""
        self.ready_info: Dict[str, Any] = {}

    def _python_path(self, voice_cfg: Dict[str, Any]) -> Optional[Path]:
        py = str(voice_cfg.get("qwen3_tts_python", ".venv_qwen3_tts\\Scripts\\python.exe")).strip() or sys.executable
        py_path = Path(py)
        if not py_path.is_absolute():
            py_path = BASE_DIR / py_path
        if not executable_exists(str(py_path)):
            log("Не найден Python окружения Qwen3-TTS. Запусти install_qwen3_tts_windows.bat или укажи qwen3_tts_python в config.json.")
            return None
        return py_path

    def _start_key(self, voice_cfg: Dict[str, Any]) -> str:
        return json.dumps({
            "py": str(self._python_path(voice_cfg) or ""),
            "model": str(voice_cfg.get("qwen3_tts_model_id", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")),
            "device": str(voice_cfg.get("qwen3_tts_device_map", "auto")),
            "dtype": str(voice_cfg.get("qwen3_tts_dtype", "auto")),
            "attn": str(voice_cfg.get("qwen3_tts_attn_implementation", "sdpa")),
            "gpu_gb": str(voice_cfg.get("qwen3_tts_gpu_memory_limit_gb", "")),
            "cpu_gb": str(voice_cfg.get("qwen3_tts_cpu_memory_limit_gb", "")),
        }, ensure_ascii=False, sort_keys=True)

    def _reader(self, pipe, q: "queue.Queue[str]", kind: str) -> None:
        try:
            for line in iter(pipe.readline, ""):
                if not line:
                    break
                text = line.rstrip("\r\n")
                q.put(text)
                if kind == "stderr" and text.strip() and self.owner.cfg.get("tts_debug_log", True):
                    # Не спамим прогресс-баром HF и известными необязательными предупреждениями Qwen3-TTS.
                    if "Fetching " in text or "it/s" in text:
                        continue
                    if self.owner.cfg.get("qwen3_tts_hide_known_warnings", True):
                        noisy_bits = [
                            "'sox' is not recognized",
                            "SoX could not be found",
                            "If you do not have SoX",
                            "http://sox.sourceforge.net",
                            "double-check your",
                            "path variables",
                            "operable program or batch file",
                            "flash-attn is not installed",
                            "Will only run the manual PyTorch version",
                            "********",
                            "generation flags are not valid",
                            "Set `pad_token_id`",
                            "Xet Storage is enabled",
                            "hf_xet",
                        ]
                        if any(bit in text for bit in noisy_bits):
                            continue
                    log("Qwen3-TTS worker: " + text[-700:])
        except Exception:
            pass

    def _drain_stdout_stale(self) -> None:
        while True:
            try:
                self.stdout_q.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        with self.lock:
            proc = self.proc
            self.proc = None
            self.started_key = ""
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(json.dumps({"cmd": "shutdown"}, ensure_ascii=False) + "\n")
                    proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def ensure_started(self, voice_cfg: Dict[str, Any]) -> bool:
        with self.lock:
            key = self._start_key(voice_cfg)
            if self.proc and self.proc.poll() is None and self.started_key == key:
                return True
            self.stop()
            py_path = self._python_path(voice_cfg)
            if not py_path:
                return False
            helper = BASE_DIR / "tools" / "qwen3_tts_worker.py"
            if not helper.exists():
                log("Не найден tools\\qwen3_tts_worker.py, fallback на обычный Qwen3-TTS subprocess.")
                return False
            cmd = [
                str(py_path), str(helper),
                "--model-id", str(voice_cfg.get("qwen3_tts_model_id", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")),
                "--device-map", str(voice_cfg.get("qwen3_tts_device_map", "auto")),
                "--dtype", str(voice_cfg.get("qwen3_tts_dtype", "auto")),
                "--attn", str(voice_cfg.get("qwen3_tts_attn_implementation", "sdpa")),
                "--gpu-memory-gb", str(voice_cfg.get("qwen3_tts_gpu_memory_limit_gb", 0) or 0),
                "--cpu-memory-gb", str(voice_cfg.get("qwen3_tts_cpu_memory_limit_gb", 0) or 0),
            ]
            env = os.environ.copy()
            env.setdefault("HF_HOME", str((BASE_DIR / ".hf_cache").resolve()))
            env.setdefault("TORCH_HOME", str((BASE_DIR / ".torch_cache").resolve()))
            env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            env.setdefault("TRANSFORMERS_VERBOSITY", "error")
            log("Qwen3-TTS worker: загружаю модель один раз и оставляю в фоне...")
            self._drain_stdout_stale()
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(BASE_DIR),
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                assert self.proc.stdout is not None and self.proc.stderr is not None
                threading.Thread(target=self._reader, args=(self.proc.stdout, self.stdout_q, "stdout"), name="Qwen3TTSStdout", daemon=True).start()
                threading.Thread(target=self._reader, args=(self.proc.stderr, self.stderr_q, "stderr"), name="Qwen3TTSStderr", daemon=True).start()
            except Exception as e:
                log(f"Qwen3-TTS worker не стартовал: {e}")
                self.proc = None
                return False
            timeout = int(voice_cfg.get("qwen3_tts_worker_start_timeout_sec", 420))
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    log(f"Qwen3-TTS worker завершился при загрузке, код {self.proc.returncode}")
                    self.proc = None
                    return False
                try:
                    line = self.stdout_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    log("Qwen3-TTS worker stdout: " + line[-700:])
                    continue
                if data.get("ok") and data.get("stage") == "ready":
                    self.started_key = key
                    self.ready_info = data
                    log(f"Qwen3-TTS worker готов: device={data.get('device_map')} dtype={data.get('dtype')} cuda={data.get('cuda_available')} max_memory={data.get('max_memory')}")
                    return True
                log("Qwen3-TTS worker не загрузился: " + json.dumps(data, ensure_ascii=False)[-1200:])
                self.stop()
                return False
            log("Qwen3-TTS worker: таймаут загрузки модели")
            self.stop()
            return False

    def render(self, text: str, wav_path: Path, voice_cfg: Dict[str, Any]) -> bool:
        with self.lock:
            if not self.ensure_started(voice_cfg):
                return False
            if not self.proc or self.proc.poll() is not None or not self.proc.stdin:
                return False
            job = {
                "text": text,
                "out": str(wav_path),
                "mode": str(voice_cfg.get("qwen3_tts_mode", "voice_design")),
                "language": str(voice_cfg.get("qwen3_tts_language", "Russian")),
                "speaker": str(voice_cfg.get("qwen3_tts_speaker", "Ryan")),
                "instruct": str(voice_cfg.get("qwen3_tts_instruct", "")),
                "max_new_tokens": int(voice_cfg.get("qwen3_tts_max_new_tokens", 1024)),
                "do_sample": bool(voice_cfg.get("qwen3_tts_do_sample", False)),
            }
            try:
                self.proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                log(f"Qwen3-TTS worker: не смог отправить задачу: {e}")
                self.stop()
                return False
            timeout = int(voice_cfg.get("qwen3_tts_worker_job_timeout_sec", 420))
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    log(f"Qwen3-TTS worker умер во время синтеза, код {self.proc.returncode}")
                    self.proc = None
                    return False
                try:
                    line = self.stdout_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    log("Qwen3-TTS worker stdout: " + line[-700:])
                    continue
                if data.get("ok") and data.get("stage") == "render":
                    return wav_path.exists() and wav_path.stat().st_size > 1000
                packed = json.dumps(data, ensure_ascii=False)
                log("Qwen3-TTS worker render failed: " + packed[-1600:])
                low = packed.lower()
                meta_or_offload = ("meta tensors" in low) or ("meta tensor" in low) or ("meta device" in low)
                already_retry = bool(voice_cfg.get("_qwen3_tts_stable_retry_done", False))
                gpu_cap = float(voice_cfg.get("qwen3_tts_gpu_memory_limit_gb", 0) or 0)
                dev = str(voice_cfg.get("qwen3_tts_device_map", "auto")).lower().strip()
                if meta_or_offload and not already_retry:
                    stable_cfg = dict(voice_cfg)
                    stable_cfg["_qwen3_tts_stable_retry_done"] = True
                    if self.owner.cfg.get("qwen3_tts_auto_retry_stable_gpu", True) and (dev == "auto" or gpu_cap > 0):
                        log("Qwen3-TTS: ошибка offload/meta tensors. Лимит VRAM слишком жёсткий для этой модели; перезапускаю worker в стабильном GPU-режиме cuda:0 без max_memory.")
                        stable_cfg["qwen3_tts_device_map"] = "cuda:0"
                        stable_cfg["qwen3_tts_gpu_memory_limit_gb"] = 0
                        stable_cfg["qwen3_tts_dtype"] = stable_cfg.get("qwen3_tts_dtype") or "auto"
                    else:
                        log("Qwen3-TTS: ошибка offload/meta tensors. Перезапускаю worker в CPU-safe режиме, чтобы не использовать VRAM.")
                        stable_cfg["qwen3_tts_device_map"] = "cpu"
                        stable_cfg["qwen3_tts_gpu_memory_limit_gb"] = 0
                        stable_cfg["qwen3_tts_dtype"] = "float32"
                    self.stop()
                    return self.render(text, wav_path, stable_cfg)
                return False
            log("Qwen3-TTS worker: таймаут синтеза")
            return False


class OmniVoiceWorkerClient:
    def __init__(self, owner: "TTS"):
        self.owner = owner
        self.proc: Optional[subprocess.Popen] = None
        self.stdout_q: "queue.Queue[str]" = queue.Queue()
        self.stderr_q: "queue.Queue[str]" = queue.Queue()

    def _pump(self, stream, q: "queue.Queue[str]", prefix: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                line = line.rstrip("\r\n")
                if line:
                    q.put(line)
        except Exception:
            pass

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
        except Exception:
            pass
        self.proc = None

    def _start(self, voice_cfg: Dict[str, Any]) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            if self.owner.cfg.get("tts_debug_log", True):
                log("OmniVoice worker уже загружен — использую без перезапуска")
            return True
        py = str(voice_cfg.get("omnivoice_python", ".venv_omnivoice\\Scripts\\python.exe")).strip() or sys.executable
        py_path = Path(py)
        if not py_path.is_absolute():
            py_path = BASE_DIR / py_path
        if not executable_exists(str(py_path)):
            log("Не найдено окружение OmniVoice. Запусти install_omnivoice_windows.bat или укажи omnivoice_python в config.json.")
            return False
        helper = BASE_DIR / "tools" / "omnivoice_worker.py"
        if not helper.exists():
            log(f"Не найден tools\\omnivoice_worker.py: {helper}")
            return False
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")

        def _cfg_path_env(key: str, default_rel: str) -> str:
            raw = str(voice_cfg.get(key, default_rel) or default_rel).strip()
            pp = Path(raw)
            if not pp.is_absolute():
                pp = BASE_DIR / pp
            return str(pp)

        env["HF_HOME"] = _cfg_path_env("omnivoice_hf_home", ".hf_cache")
        env["HF_HUB_CACHE"] = _cfg_path_env("omnivoice_hf_hub_cache", ".hf_cache/hub")
        env["HF_XET_CACHE"] = _cfg_path_env("omnivoice_hf_xet_cache", ".hf_cache/xet")
        env["TORCH_HOME"] = _cfg_path_env("omnivoice_torch_home", ".torch_cache")
        env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        env.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
        ffmpeg = str(self.owner.cfg.get("ffmpeg_path", "") or "").strip()
        if ffmpeg:
            env.setdefault("AI_TRUCK_RADIO_FFMPEG", ffmpeg)
        cmd = [
            str(py_path), str(helper),
            "--model", str(voice_cfg.get("omnivoice_model", "k2-fsa/OmniVoice")),
            "--device", str(voice_cfg.get("omnivoice_device", "cuda:0")),
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(BASE_DIR),
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            log(f"OmniVoice worker: не смог запуститься: {e}")
            self.proc = None
            return False
        threading.Thread(target=self._pump, args=(self.proc.stdout, self.stdout_q, "stdout"), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, self.stderr_q, "stderr"), daemon=True).start()
        log("OmniVoice worker: загружаю модель один раз и оставляю в фоне...")
        deadline = time.time() + int(voice_cfg.get("omnivoice_worker_start_timeout_sec", 420) or 420)
        last_log = 0.0
        while time.time() < deadline:
            if self.proc.poll() is not None:
                log(f"OmniVoice worker умер при старте, код {self.proc.returncode}")
                self._flush_stderr()
                self.proc = None
                return False
            self._flush_stderr(throttle=True, last_log_ref=[last_log])
            try:
                line = self.stdout_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                data = json.loads(line)
            except Exception:
                if line.strip():
                    log("OmniVoice worker stdout: " + line[-700:])
                continue
            if data.get("ok") and data.get("stage") == "ready":
                log(f"OmniVoice worker готов: device={data.get('device')} dtype={data.get('dtype')} cuda={data.get('cuda_available')} gpu={data.get('gpu') or 'none'}")
                return True
            if not data.get("ok"):
                log("OmniVoice worker стартовая ошибка: " + json.dumps(data, ensure_ascii=False)[-1600:])
                self.stop()
                return False
        log("OmniVoice worker: таймаут загрузки модели")
        self.stop()
        return False

    def _flush_stderr(self, throttle: bool = False, last_log_ref: Optional[List[float]] = None) -> None:
        # stderr contains progress bars/warnings; show only useful compact lines.
        now = time.time()
        shown = 0
        while True:
            try:
                line = self.stderr_q.get_nowait()
            except queue.Empty:
                break
            low = line.lower()
            if not line.strip():
                continue
            if "loading weights" in low or "fetching" in low or "download" in low:
                if throttle and last_log_ref is not None and now - last_log_ref[0] < 5:
                    continue
                if last_log_ref is not None:
                    last_log_ref[0] = now
            if shown < 4:
                log("OmniVoice worker: " + line[-700:])
                shown += 1

    def render(self, text: str, wav_path: Path, voice_cfg: Dict[str, Any]) -> bool:
        if not self._start(voice_cfg):
            return False
        job = {
            "text": text,
            "out": str(wav_path),
            "mode": str(voice_cfg.get("omnivoice_mode", "clone")),
            "ref_audio": str(voice_cfg.get("omnivoice_ref_audio", "")),
            "ref_text": str(voice_cfg.get("omnivoice_ref_text", "")),
            "instruct": str(voice_cfg.get("omnivoice_instruct", "")),
            "steps": int(voice_cfg.get("omnivoice_steps", 16) or 16),
            "speed": float(voice_cfg.get("omnivoice_speed", 1.0) or 1.0),
            "tail_silence_ms": int(voice_cfg.get("omnivoice_tail_silence_ms", 260) or 260),
            "pronunciation_file": str(voice_cfg.get("omnivoice_pronunciation_file", "prompts/pronunciation_ru.tsv")),
            "normalize_ru": bool(voice_cfg.get("omnivoice_normalize_ru", True)),
        }
        try:
            self.proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            log(f"OmniVoice worker: не смог отправить задачу: {e}")
            self.stop()
            return False
        deadline = time.time() + int(voice_cfg.get("omnivoice_worker_job_timeout_sec", 420) or 420)
        while time.time() < deadline:
            if self.proc.poll() is not None:
                log(f"OmniVoice worker умер во время синтеза, код {self.proc.returncode}")
                self._flush_stderr()
                self.proc = None
                return False
            self._flush_stderr(throttle=True, last_log_ref=[0])
            try:
                line = self.stdout_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                data = json.loads(line)
            except Exception:
                if line.strip():
                    log("OmniVoice worker stdout: " + line[-700:])
                continue
            if data.get("ok") and data.get("stage") == "render":
                if data.get("normalized_text") and self.owner.cfg.get("tts_debug_log", True):
                    log("OmniVoice normalized: " + str(data.get("normalized_text"))[:220])
                return wav_path.exists() and wav_path.stat().st_size > 1000
            log("OmniVoice worker render failed: " + json.dumps(data, ensure_ascii=False)[-1600:])
            return False
        log("OmniVoice worker: таймаут синтеза")
        return False


class TTS:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.cache_dir = rel_path(cfg, "cache_dir") / "spoken"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = rel_path(cfg, "cache_dir") / "tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.qwen3_worker: Optional[Qwen3TTSWorkerClient] = None
        self.omnivoice_worker: Optional[OmniVoiceWorkerClient] = None

    def close(self) -> None:
        if self.qwen3_worker is not None:
            try:
                self.qwen3_worker.stop()
            except Exception:
                pass
            self.qwen3_worker = None
        if self.omnivoice_worker is not None:
            try:
                self.omnivoice_worker.stop()
            except Exception:
                pass
            self.omnivoice_worker = None

    def text_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]

    def _voice_cfg_for_host(self, host_name: Optional[str], host_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = dict(self.cfg)

        def apply_host_voice(host: Dict[str, Any]) -> None:
            for key in ["piper_voice", "piper_model", "piper_extra_args", "sapi_voice_contains", "sapi_rate", "sapi_volume", "silero_speaker", "silero_model", "silero_language", "silero_sample_rate", "silero_device", "silero_put_accent", "silero_put_yo", "qwen3_tts_mode", "qwen3_tts_instruct", "qwen3_tts_instruct_variants", "qwen3_tts_speaker", "qwen3_tts_language", "f5_tts_ref_audio", "f5_tts_ref_text", "omnivoice_ref_audio", "omnivoice_ref_text", "omnivoice_instruct", "omnivoice_mode", "omnivoice_device", "omnivoice_steps", "omnivoice_speed"]:
                if key in host and host[key] not in [None, ""]:
                    cfg[key] = host[key]

        if host_name:
            for host in self.cfg.get("hosts") or []:
                if isinstance(host, dict) and str(host.get("name", "")).lower() == str(host_name).lower():
                    apply_host_voice(host)
                    break
        if isinstance(host_override, dict):
            apply_host_voice(host_override)
        variants = cfg.get("qwen3_tts_instruct_variants")
        if cfg.get("qwen3_tts_instruct_variants_enabled", True) and isinstance(variants, list):
            clean = [str(v).strip() for v in variants if str(v).strip()]
            if clean:
                cfg["qwen3_tts_instruct"] = random.choice(clean)
        return cfg

    def prewarm_omnivoice_worker(self, hosts: Optional[List[Dict[str, Any]]] = None) -> None:
        """Load OmniVoice worker before the first generated phrase."""
        backend = str(self.cfg.get("tts_backend", "")).lower().strip()
        if backend not in {"omnivoice", "omnivoice_tts", "omni", "omni_voice"}:
            return
        if not bool(self.cfg.get("omnivoice_persistent_worker", True)):
            return
        if not bool(self.cfg.get("omnivoice_prewarm_on_radio_start", True)):
            return
        try:
            host_name = None
            for h in hosts or self.cfg.get("hosts") or []:
                if isinstance(h, dict) and h.get("enabled", True) is not False and str(h.get("name", "")).strip():
                    host_name = str(h.get("name")).strip()
                    break
            voice_cfg = self._voice_cfg_for_host(host_name)
            if self.omnivoice_worker is None:
                self.omnivoice_worker = OmniVoiceWorkerClient(self)
            log(f"OmniVoice prewarm: заранее загружаю worker для {host_name or 'первого доступного голоса'}")
            if self.omnivoice_worker._start(voice_cfg):
                log("OmniVoice prewarm: worker готов до первой реплики")
        except Exception as e:
            log(f"OmniVoice prewarm не удался, продолжу обычным запуском при TTS: {e}")

    def get_or_create_dialogue_mp3(self, text: str, hosts: List[Dict[str, Any]]) -> Optional[Path]:
        if not self.cfg.get("tts_dialogue_split_hosts", True):
            return self.get_or_create_mp3(strip_spoken_host_names(text, [str(h.get("name", "")) for h in hosts if isinstance(h, dict)]))
        segments = parse_dialogue_segments(text, hosts)
        if self.cfg.get("tts_debug_log", True):
            pretty = "; ".join(f"{host or 'без имени'}={len(spoken)}симв" for host, spoken in segments)
            log(f"TTS: разобрал реплики: {pretty or 'нет реплик'}")
        if self.cfg.get("tts_parse_validation_enabled", True):
            aliases = host_aliases(hosts)
            src_plain = re.sub(r"\s+", " ", strip_spoken_host_names(text, aliases)).strip()
            spoken_plain = re.sub(r"\s+", " ", " ".join(spoken for _host, spoken in segments)).strip()
            src_len = len(src_plain)
            out_len = len(spoken_plain)
            ratio = (out_len / src_len) if src_len else 1.0
            if self.cfg.get("tts_debug_log", True):
                log(f"TTS: контроль текста — исходник {src_len} симв, в озвучку {out_len} симв, ratio={ratio:.2f}")
            min_ratio = float(self.cfg.get("tts_parse_validation_min_ratio", 0.86) or 0.86)
            if src_len > 40 and ratio < min_ratio:
                log("TTS: предупреждение — парсер мог потерять часть слов; отдаю весь текст одному голосу, чтобы ничего не пропало")
                fallback_host = segments[0][0] if segments else None
                segments = [(fallback_host, trim_to_complete_sentence(src_plain or text))]
        host_cfg_by_name = {
            str(hst.get("name", "")).strip().lower(): hst
            for hst in hosts
            if isinstance(hst, dict) and str(hst.get("name", "")).strip()
        }
        if len(segments) <= 1:
            host, spoken = segments[0] if segments else (None, text)
            host_cfg = host_cfg_by_name.get(str(host or "").strip().lower())
            return self.get_or_create_mp3(spoken, host, host_cfg)
        voice_sig = json.dumps([{
            "name": hst.get("name", ""),
            "voice_ver": hst.get("host_voice_profile_version", ""),
            "qwen3_speaker": hst.get("qwen3_tts_speaker", ""),
            "qwen3_instruct": hst.get("qwen3_tts_instruct", ""),
            "silero": hst.get("silero_speaker", ""),
            "piper": hst.get("piper_voice", ""),
            "f5_ref": hst.get("f5_tts_ref_audio", ""),
            "f5_ref_text": hst.get("f5_tts_ref_text", ""),
            "omni_ref": hst.get("omnivoice_ref_audio", ""),
            "omni_ref_text": hst.get("omnivoice_ref_text", ""),
            "omni_instruct": hst.get("omnivoice_instruct", ""),
        } for hst in hosts if isinstance(hst, dict)], ensure_ascii=False, sort_keys=True)
        h = self.text_hash("|dialogue|" + json.dumps(segments, ensure_ascii=False) + "|" + str(self.cfg.get("tts_backend", "")) + "|" + voice_sig)
        out_mp3 = self.cache_dir / f"dialogue_{h}.mp3"
        if out_mp3.exists() and out_mp3.stat().st_size > 1024:
            if self.cfg.get("tts_debug_log", True):
                log(f"TTS: готовый кэш диалога: {out_mp3.name}")
            return out_mp3
        part_files: List[Path] = []
        for idx, (host, spoken) in enumerate(segments):
            spoken = trim_to_complete_sentence(spoken)
            if self.cfg.get("tts_debug_log", True):
                log(f"TTS: озвучиваю реплику {idx+1}/{len(segments)} голосом {host or 'по умолчанию'}: {' '.join(spoken.split())[:180]}")
            host_cfg = host_cfg_by_name.get(str(host or "").strip().lower())
            part = self.get_or_create_mp3(spoken, host, host_cfg)
            if part and part.exists():
                part_files.append(part)
            else:
                log(f"TTS: реплика {idx+1} не была озвучена")
        if not part_files:
            return None
        if len(part_files) == 1:
            return part_files[0]
        return self._concat_mp3_files(part_files, out_mp3)
    def _concat_mp3_files(self, files: List[Path], out_mp3: Path) -> Optional[Path]:
        ffmpeg = str(self.cfg.get("ffmpeg_path", "ffmpeg"))
        if not executable_exists(ffmpeg):
            return files[0] if files else None
        list_file = self.tmp_dir / f"concat_{self.text_hash('|'.join(str(p) for p in files))}.txt"
        lines = []
        for p in files:
            safe = str(p.resolve()).replace("'", "'\''")
            lines.append(f"file '{safe}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", f"{int(self.cfg.get('bitrate_kbps', 128))}k",
            str(out_mp3),
        ]
        res = run_subprocess(cmd, timeout=120)
        if res.returncode != 0:
            log("FFmpeg не смог склеить реплики ведущих:")
            log(res.stderr.strip() or res.stdout.strip())
            return files[0]
        return out_mp3 if out_mp3.exists() and out_mp3.stat().st_size > 1024 else files[0]

    def get_or_create_mp3(self, text: str, host_name: Optional[str] = None, host_cfg: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        primary_backend = str(self.cfg.get("tts_backend", "sapi")).lower().strip()
        if primary_backend == "none":
            return None
        backends = [primary_backend]
        if self.cfg.get("tts_fallback_enabled", True):
            for b in self.cfg.get("tts_fallback_chain", []) or []:
                b = str(b).lower().strip()
                if b and b not in backends and b != "none":
                    backends.append(b)

        last_error = ""
        for backend in backends:
            voice_cfg = self._voice_cfg_for_host(host_name, host_cfg)
            h = self.text_hash(text + "|" + backend + "|" + host_name_or_empty(host_name) + "|" + str(voice_cfg.get("piper_voice", "")) + "|" + str(voice_cfg.get("silero_speaker", "")) + "|" + str(voice_cfg.get("qwen3_tts_model_id", "")) + "|" + str(voice_cfg.get("qwen3_tts_instruct", "")) + "|" + str(voice_cfg.get("qwen3_tts_speaker", "")) + "|" + str(voice_cfg.get("sapi_voice_contains", "")) + "|" + str(voice_cfg.get("lmstudio_tts_model", self.cfg.get("lmstudio_tts_model", ""))) + "|" + str(voice_cfg.get("lmstudio_tts_voice", self.cfg.get("lmstudio_tts_voice", ""))) + "|" + str(voice_cfg.get("lmstudio_tts_response_format", self.cfg.get("lmstudio_tts_response_format", ""))) + "|" + str(voice_cfg.get("omnivoice_ref_audio", "")) + "|" + str(voice_cfg.get("omnivoice_ref_text", "")) + "|" + str(voice_cfg.get("omnivoice_instruct", "")) + "|" + str(voice_cfg.get("omnivoice_steps", "")) + "|" + str(voice_cfg.get("omnivoice_speed", "")) + "|" + str(voice_cfg.get("omnivoice_pronunciation_file", "")))
            out_mp3 = self.cache_dir / f"host_{h}.mp3"
            if out_mp3.exists() and out_mp3.stat().st_size > 1024:
                if self.cfg.get("tts_debug_log", True):
                    log(f"TTS {backend}: беру кэш {out_mp3.name} ({out_mp3.stat().st_size} байт)")
                return out_mp3
            try:
                if self.cfg.get("tts_debug_log", True):
                    log(f"TTS {backend}: старт синтеза для {host_name_or_empty(host_name) or 'голоса по умолчанию'}")
                if backend in {"lmstudio_tts", "lmstudio-tts", "lmstudio_audio"}:
                    if self._lmstudio_tts_to_mp3(text, out_mp3, voice_cfg):
                        if self.cfg.get("tts_debug_log", True):
                            log(f"TTS {backend}: готово {out_mp3.name} ({out_mp3.stat().st_size} байт)")
                        return out_mp3
                    last_error = f"{backend}: mp3 не создан"
                    log(f"TTS {backend}: mp3 не создан")
                    continue
                if backend in {"omnivoice", "omnivoice_tts", "omni", "omni_voice"}:
                    wav_path = self._omnivoice_to_wav(text, h, voice_cfg)
                elif backend == "piper":
                    wav_path = self._piper_to_wav(text, h, voice_cfg)
                elif backend == "silero":
                    wav_path = self._silero_to_wav(text, h, voice_cfg)
                elif backend in {"qwen3_tts", "qwen3-tts", "qwen3"}:
                    wav_path = self._qwen3_tts_to_wav(text, h, voice_cfg)
                elif backend in {"f5_tts", "f5-tts", "f5"}:
                    wav_path = self._f5_tts_to_wav(text, h, voice_cfg)
                else:
                    wav_path = self._sapi_to_wav(text, h, voice_cfg)
                if not wav_path or not wav_path.exists():
                    last_error = f"{backend}: wav не создан"
                    log(f"TTS {backend}: wav не создан")
                    continue
                if not self._wav_to_mp3(wav_path, out_mp3):
                    last_error = f"{backend}: mp3 не создан"
                    log(f"TTS {backend}: mp3 не создан")
                    continue
                if self.cfg.get("tts_debug_log", True):
                    log(f"TTS {backend}: готово {out_mp3.name} ({out_mp3.stat().st_size} байт)")
                return out_mp3
            except Exception as e:
                last_error = f"{backend}: {e}"
                log(f"TTS {backend} ошибка: {e}")
                log(traceback.format_exc())
            finally:
                self.cleanup_cache()
        if last_error:
            log(f"TTS: все backend'ы не смогли озвучить реплику. Последнее: {last_error}")
        return None
    def _sapi_to_wav(self, text: str, h: str, voice_cfg: Dict[str, Any]) -> Optional[Path]:
        if os.name != "nt":
            log("Windows SAPI доступен только на Windows. Поставь tts_backend=piper или запускай на Windows.")
            return None
        wav_path = self.tmp_dir / f"host_{h}.wav"
        text_file = self.tmp_dir / f"host_{h}.txt"
        ps1_file = self.tmp_dir / f"sapi_{h}.ps1"
        text_file.write_text(text, encoding="utf-8")
        voice_filter = str(voice_cfg.get("sapi_voice_contains", "")).replace("'", "''")
        rate = int(voice_cfg.get("sapi_rate", 0))
        volume = int(voice_cfg.get("sapi_volume", 100))
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$TextPath = '{str(text_file).replace("'", "''")}'
$WavPath = '{str(wav_path).replace("'", "''")}'
$VoiceFilter = '{voice_filter}'
$Text = Get-Content -LiteralPath $TextPath -Raw -Encoding UTF8
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($VoiceFilter -ne '') {{
  $voices = $synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Name -like "*$VoiceFilter*" -or $_.VoiceInfo.Culture.Name -like "*$VoiceFilter*" }}
  if ($voices.Count -gt 0) {{ $synth.SelectVoice($voices[0].VoiceInfo.Name) }}
}}
$synth.Rate = {rate}
$synth.Volume = {volume}
$synth.SetOutputToWaveFile($WavPath)
$synth.Speak($Text)
$synth.Dispose()
"""
        ps1_file.write_text(script, encoding="utf-8-sig")
        ps_cmd = shutil.which("powershell") or shutil.which("powershell.exe")
        if not ps_cmd:
            log("Не найден powershell.exe для Windows SAPI.")
            return None
        res = run_subprocess([ps_cmd, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_file)], timeout=60)
        if res.returncode != 0:
            log("PowerShell/SAPI не смог создать озвучку:")
            log(res.stderr.strip() or res.stdout.strip())
            return None
        return wav_path

    def _piper_to_wav(self, text: str, h: str, voice_cfg: Dict[str, Any]) -> Optional[Path]:
        wav_path = self.tmp_dir / f"host_{h}.wav"
        extra = voice_cfg.get("piper_extra_args") or []
        extra_args = [str(x) for x in extra] if isinstance(extra, list) else []

        piper_voice = str(voice_cfg.get("piper_voice", "")).strip()
        piper_python = str(voice_cfg.get("piper_python", ".venv\\Scripts\\python.exe")).strip()
        if piper_python:
            py_path = Path(piper_python)
            if not py_path.is_absolute():
                py_path = BASE_DIR / py_path
            piper_python = str(py_path)

        data_dir = Path(str(voice_cfg.get("piper_data_dir", "voices")))
        if not data_dir.is_absolute():
            data_dir = BASE_DIR / data_dir

        if piper_voice and executable_exists(piper_python):
            cmd = [
                piper_python,
                "-m", "piper",
                "-m", piper_voice,
                "--data-dir", str(data_dir),
                "-f", str(wav_path),
            ]
            cmd.extend(extra_args)
            cmd.extend(["--", text])
            res = run_subprocess(cmd, timeout=90)
            if res.returncode == 0 and wav_path.exists():
                return wav_path
            log("Piper через python -m piper не смог создать озвучку:")
            log((res.stderr or res.stdout).strip())

        piper_exe = str(voice_cfg.get("piper_exe", "piper"))
        model_path = Path(str(voice_cfg.get("piper_model", "voices/ru_RU-ruslan-medium.onnx")))
        if not model_path.is_absolute():
            model_path = BASE_DIR / model_path
        if not executable_exists(piper_exe):
            log("Не найден Piper. Запусти install_piper_windows.bat или укажи piper_python/piper_exe в config.json.")
            return None
        if not model_path.exists():
            log(f"Не найдена модель Piper: {model_path}")
            return None
        cmd = [piper_exe, "--model", str(model_path), "--output_file", str(wav_path)]
        cmd.extend(extra_args)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out, err = proc.communicate(text, timeout=90)
        if proc.returncode != 0:
            log("Piper не смог создать озвучку:")
            log((err or out).strip())
            return None
        return wav_path


    def _omnivoice_to_wav(self, text: str, h: str, voice_cfg: Dict[str, Any]) -> Optional[Path]:
        wav_path = self.tmp_dir / f"host_{h}_omnivoice.wav"
        # Resolve reference text from host config or sidecar .txt.
        ref_audio = str(voice_cfg.get("omnivoice_ref_audio", "") or "").strip()
        ref_path = Path(ref_audio) if ref_audio else Path()
        if ref_audio and not ref_path.is_absolute():
            ref_path = BASE_DIR / ref_path
        ref_text = str(voice_cfg.get("omnivoice_ref_text", "") or "").strip()
        if not ref_text and ref_audio:
            txt_sidecar = ref_path.with_suffix(".txt")
            if txt_sidecar.exists():
                ref_text = txt_sidecar.read_text(encoding="utf-8-sig", errors="replace").strip()
                voice_cfg = dict(voice_cfg)
                voice_cfg["omnivoice_ref_text"] = ref_text
        mode = str(voice_cfg.get("omnivoice_mode", "clone") or "clone").lower().strip()
        if mode in {"clone", "auto"}:
            if not ref_audio or not ref_path.exists():
                if mode == "clone":
                    log(f"OmniVoice: не найден reference voice: {ref_path}. Положи WAV/MP3 в references\\maxim_ref.wav / irina_ref.wav или переключи omnivoice_mode=design.")
                    return None
                voice_cfg = dict(voice_cfg)
                voice_cfg["omnivoice_mode"] = "design"
            else:
                voice_cfg = dict(voice_cfg)
                voice_cfg["omnivoice_ref_audio"] = str(ref_path)
                voice_cfg["omnivoice_ref_text"] = ref_text
        py = str(voice_cfg.get("omnivoice_python", ".venv_omnivoice\\Scripts\\python.exe")).strip() or sys.executable
        py_path = Path(py)
        if not py_path.is_absolute():
            py_path = BASE_DIR / py_path
        if not executable_exists(str(py_path)):
            log("Не найдено окружение OmniVoice. Запусти install_omnivoice_windows.bat или укажи omnivoice_python в config.json.")
            return None
        if bool(voice_cfg.get("omnivoice_persistent_worker", True)):
            if self.omnivoice_worker is None:
                self.omnivoice_worker = OmniVoiceWorkerClient(self)
            if self.omnivoice_worker.render(text, wav_path, voice_cfg):
                return wav_path
            log("OmniVoice worker не создал WAV, пробую одноразовый subprocess.")
        text_file = self.tmp_dir / f"host_{h}_omnivoice.txt"
        text_file.write_text(text, encoding="utf-8")
        helper = BASE_DIR / "tools" / "omnivoice_render.py"
        cmd = [
            str(py_path), str(helper),
            "--mode", str(voice_cfg.get("omnivoice_mode", "clone")),
            "--model", str(voice_cfg.get("omnivoice_model", "k2-fsa/OmniVoice")),
            "--text-file", str(text_file),
            "--output", str(wav_path),
            "--device", str(voice_cfg.get("omnivoice_device", "cuda:0")),
            "--steps", str(int(voice_cfg.get("omnivoice_steps", 16) or 16)),
            "--speed", str(float(voice_cfg.get("omnivoice_speed", 1.0) or 1.0)),
            "--tail-silence-ms", str(int(voice_cfg.get("omnivoice_tail_silence_ms", 260) or 260)),
            "--pronunciation-file", str(BASE_DIR / str(voice_cfg.get("omnivoice_pronunciation_file", "prompts/pronunciation_ru.tsv"))),
        ]
        if str(voice_cfg.get("omnivoice_mode", "clone")).lower().strip() != "design":
            cmd.extend(["--ref-audio", str(ref_path)])
            if ref_text:
                cmd.extend(["--ref-text", ref_text])
        instruct = str(voice_cfg.get("omnivoice_instruct", "") or "").strip()
        if instruct:
            cmd.extend(["--instruct", instruct])
        if not bool(voice_cfg.get("omnivoice_normalize_ru", True)):
            cmd.append("--no-ru-normalize")
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")

        def _cfg_path_env(key: str, default_rel: str) -> str:
            raw = str(voice_cfg.get(key, default_rel) or default_rel).strip()
            pp = Path(raw)
            if not pp.is_absolute():
                pp = BASE_DIR / pp
            return str(pp)

        env["HF_HOME"] = _cfg_path_env("omnivoice_hf_home", ".hf_cache")
        env["HF_HUB_CACHE"] = _cfg_path_env("omnivoice_hf_hub_cache", ".hf_cache/hub")
        env["HF_XET_CACHE"] = _cfg_path_env("omnivoice_hf_xet_cache", ".hf_cache/xet")
        env["TORCH_HOME"] = _cfg_path_env("omnivoice_torch_home", ".torch_cache")
        env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        env.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
        ffmpeg = str(self.cfg.get("ffmpeg_path", "") or "").strip()
        if ffmpeg:
            env.setdefault("AI_TRUCK_RADIO_FFMPEG", ffmpeg)
        timeout = int(voice_cfg.get("omnivoice_worker_job_timeout_sec", self.cfg.get("tts_subprocess_timeout_sec", 900)) or 900)
        res = run_subprocess(cmd, timeout=timeout, env=env)
        if res.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size < 1024:
            log("OmniVoice не смог создать озвучку:")
            combined = ((res.stderr or "") + "\n" + (res.stdout or "")).strip()
            log(combined[-3000:] if combined else f"returncode={res.returncode}, stdout/stderr пустые")
            return None
        return wav_path

    def _silero_to_wav(self, text: str, h: str, voice_cfg: Dict[str, Any]) -> Optional[Path]:
        wav_path = self.tmp_dir / f"host_{h}.wav"
        text_file = self.tmp_dir / f"host_{h}.txt"
        text_file.write_text(text, encoding="utf-8")
        py = str(voice_cfg.get("piper_python", ".venv\\Scripts\\python.exe")).strip() or sys.executable
        py_path = Path(py)
        if not py_path.is_absolute():
            py_path = BASE_DIR / py_path
        if not executable_exists(str(py_path)):
            py_path = Path(sys.executable)

        repo_dir = str(voice_cfg.get("silero_repo_dir", "silero-models") or "").strip()
        if repo_dir:
            repo_path = Path(repo_dir)
            if not repo_path.is_absolute():
                repo_path = BASE_DIR / repo_path
            repo_dir = str(repo_path)

        helper = BASE_DIR / "tools" / "silero_render.py"
        if not helper.exists():
            log("Silero backend скрыт/не установлен: tools\\silero_render.py отсутствует. Используй OmniVoice/Piper или верни legacy tools.")
            return None
        cmd = [
            str(py_path), str(helper),
            "--text-file", str(text_file),
            "--out", str(wav_path),
            "--repo-dir", repo_dir,
            "--language", str(voice_cfg.get("silero_language", "ru")),
            "--model", str(voice_cfg.get("silero_model", "v4_ru")),
            "--speaker", str(voice_cfg.get("silero_speaker", "aidar")),
            "--sample-rate", str(int(voice_cfg.get("silero_sample_rate", 48000))),
            "--device", str(voice_cfg.get("silero_device", "cpu")),
        ]
        if bool(voice_cfg.get("silero_put_accent", True)):
            cmd.append("--put-accent")
        if bool(voice_cfg.get("silero_put_yo", True)):
            cmd.append("--put-yo")
        res = run_subprocess(cmd, timeout=240)
        if res.returncode != 0 or not wav_path.exists():
            log("Silero не смог создать озвучку:")
            log((res.stderr or res.stdout).strip())
            log("Подсказка: запусти install_silero_windows.bat. Если исходники Silero лежат не в папке проекта, укажи silero_repo_dir в config.json.")
            return None
        return wav_path

    def _f5_tts_to_wav(self, text: str, h: str, voice_cfg: Dict[str, Any]) -> Optional[Path]:
        wav_path = self.tmp_dir / f"host_{h}_f5.wav"
        text_file = self.tmp_dir / f"host_{h}_f5.txt"
        text_file.write_text(text, encoding="utf-8")
        py = str(voice_cfg.get("f5_tts_python", ".venv_f5_tts\\Scripts\\python.exe")).strip() or sys.executable
        py_path = Path(py)
        if not py_path.is_absolute():
            py_path = BASE_DIR / py_path
        if not executable_exists(str(py_path)):
            log("Не найден Python окружения F5-TTS. Запусти install_f5_tts_windows.bat или укажи f5_tts_python в config.json.")
            return None
        ref_audio = str(voice_cfg.get("f5_tts_ref_audio", "")).strip()
        ref_path = Path(ref_audio)
        if ref_audio and not ref_path.is_absolute():
            ref_path = BASE_DIR / ref_path
        if not ref_audio or not ref_path.exists():
            log(f"F5-TTS: не найден reference voice для {host_name_or_empty(voice_cfg.get('name')) or 'ведущего'}: {ref_path}. Положи WAV/MP3 в references\\maxim_ref.wav / irina_ref.wav или пропиши f5_tts_ref_audio.")
            return None
        ref_text = str(voice_cfg.get("f5_tts_ref_text", "")).strip()
        if not ref_text:
            txt_sidecar = ref_path.with_suffix(".txt")
            if txt_sidecar.exists():
                ref_text = txt_sidecar.read_text(encoding="utf-8", errors="replace").strip()
        if not ref_text:
            log("F5-TTS: f5_tts_ref_text пустой. Нужна точная расшифровка reference audio, иначе F5 может подтянуть ASR и съесть лишнюю VRAM.")
            return None
        helper = BASE_DIR / "tools" / "f5_tts_render.py"
        if not helper.exists():
            log("F5-TTS backend скрыт/не установлен: tools\\f5_tts_render.py отсутствует. Используй OmniVoice/Piper или верни legacy tools.")
            return None
        cmd = [
            str(py_path), str(helper),
            "--text-file", str(text_file),
            "--out", str(wav_path),
            "--ref-audio", str(ref_path),
            "--ref-text", ref_text,
            "--model", str(voice_cfg.get("f5_tts_model", "F5TTS_Base")),
            "--ckpt-file", str(voice_cfg.get("f5_tts_ckpt_file", "")),
            "--vocab-file", str(voice_cfg.get("f5_tts_vocab_file", "")),
            "--model-cfg", str(voice_cfg.get("f5_tts_model_cfg", "")),
            "--vocoder", str(voice_cfg.get("f5_tts_vocoder", "vocos")),
            "--nfe-step", str(int(voice_cfg.get("f5_tts_nfe_step", 32) or 32)),
            "--sway", str(float(voice_cfg.get("f5_tts_sway_sampling_coef", -1.0) or -1.0)),
            "--speed", str(float(voice_cfg.get("f5_tts_speed", 1.0) or 1.0)),
            "--seed", str(int(voice_cfg.get("f5_tts_seed", -1) or -1)),
        ]
        if bool(voice_cfg.get("f5_tts_remove_silence", True)):
            cmd.append("--remove-silence")
        env = os.environ.copy()
        env.setdefault("HF_HOME", str(BASE_DIR / ".hf_cache"))
        env.setdefault("HF_HUB_CACHE", str(BASE_DIR / ".hf_cache" / "hub"))
        env.setdefault("TORCH_HOME", str(BASE_DIR / ".torch_cache"))
        env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        timeout = int(voice_cfg.get("f5_tts_timeout_sec", self.cfg.get("tts_subprocess_timeout_sec", 900)) or 900)
        res = run_subprocess(cmd, timeout=timeout, env=env)
        if res.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size < 1024:
            log("F5-TTS не смог создать озвучку:")
            log((res.stderr or res.stdout).strip()[-2500:])
            return None
        return wav_path

    def _lmstudio_tts_to_mp3(self, text: str, out_mp3: Path, voice_cfg: Dict[str, Any]) -> bool:
        """Experimental OpenAI-compatible /audio/speech backend.
        This only works if the running LM Studio build/model exposes a real audio endpoint.
        Many GGUF TTS models load in LM Studio as text models and do not return playable audio.
        """
        base = str(voice_cfg.get("lmstudio_tts_base_url") or self.cfg.get("lmstudio_tts_base_url") or self.cfg.get("lm_base_url") or "http://127.0.0.1:1234/v1").rstrip("/")
        model = str(voice_cfg.get("lmstudio_tts_model") or self.cfg.get("lmstudio_tts_model") or self.cfg.get("lm_model") or "local-model").strip() or "local-model"
        voice = str(voice_cfg.get("lmstudio_tts_voice") or self.cfg.get("lmstudio_tts_voice") or "default").strip() or "default"
        fmt = str(voice_cfg.get("lmstudio_tts_response_format") or self.cfg.get("lmstudio_tts_response_format") or "mp3").strip().lower() or "mp3"
        speed = float(voice_cfg.get("lmstudio_tts_speed", self.cfg.get("lmstudio_tts_speed", 1.0)) or 1.0)
        timeout = float(voice_cfg.get("lmstudio_tts_timeout_sec", self.cfg.get("lmstudio_tts_timeout_sec", 180)) or 180)
        url = base + "/audio/speech"
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": fmt,
            "speed": speed,
        }
        import urllib.request, urllib.error
        try:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=raw, headers={"Content-Type": "application/json", "Accept": "audio/*"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                ctype = str(resp.headers.get("Content-Type", ""))
            if len(data) < 1024:
                log(f"LM Studio TTS вернул слишком мало данных ({len(data)} байт), content-type={ctype}")
                return False
            # If LM Studio returns JSON/error text with status 200, do not save it as audio.
            head = data[:80].lstrip().lower()
            if head.startswith(b"{") or head.startswith(b"[") or b"application/json" in ctype.lower().encode("ascii", "ignore"):
                try:
                    msg = data.decode("utf-8", "replace")[:1200]
                except Exception:
                    msg = repr(data[:300])
                log("LM Studio TTS вернул JSON/текст вместо аудио: " + msg)
                return False
            tmp = out_mp3.with_suffix("." + ("wav" if fmt == "wav" else "mp3"))
            tmp.write_bytes(data)
            if tmp.suffix.lower() == ".mp3":
                if tmp.resolve() != out_mp3.resolve():
                    shutil.move(str(tmp), str(out_mp3))
                return out_mp3.exists() and out_mp3.stat().st_size > 1024
            # Convert non-mp3 audio to mp3 for the rest of the radio pipeline.
            return self._wav_to_mp3(tmp, out_mp3)
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")[:1200]
            except Exception:
                body = ""
            log(f"LM Studio TTS HTTP {e.code}: {body or e.reason}")
            log("Подсказка: если GGUF TTS модель просто загружена как обычная chat-модель, LM Studio может не иметь рабочего /v1/audio/speech для неё. Тогда этот backend не сможет создать MP3.")
            return False
        except Exception as e:
            log(f"LM Studio TTS ошибка: {e}")
            return False

    def _qwen3_tts_to_wav(self, text: str, h: str, voice_cfg: Dict[str, Any]) -> Optional[Path]:
        wav_path = self.tmp_dir / f"host_{h}.wav"
        text_file = self.tmp_dir / f"host_{h}.txt"
        text_file.write_text(text, encoding="utf-8")
        py = str(voice_cfg.get("qwen3_tts_python", ".venv_qwen3_tts\\Scripts\\python.exe")).strip() or sys.executable
        py_path = Path(py)
        if not py_path.is_absolute():
            py_path = BASE_DIR / py_path
        if not executable_exists(str(py_path)):
            log("Не найден Python окружения Qwen3-TTS. Запусти install_qwen3_tts_windows.bat или укажи qwen3_tts_python в config.json.")
            return None
        if bool(voice_cfg.get("qwen3_tts_persistent_worker", True)):
            if self.qwen3_worker is None:
                self.qwen3_worker = Qwen3TTSWorkerClient(self)
            if self.qwen3_worker.render(text, wav_path, voice_cfg):
                return wav_path
            log("Qwen3-TTS worker не создал WAV, fallback на одноразовый subprocess.")

        helper = BASE_DIR / "tools" / "qwen3_tts_render.py"
        if not helper.exists():
            log("Qwen3-TTS backend скрыт/не установлен: tools\\qwen3_tts_render.py отсутствует. Используй OmniVoice/Piper или верни legacy tools.")
            return None
        cmd = [
            str(py_path), str(helper),
            "--text-file", str(text_file),
            "--out", str(wav_path),
            "--model-id", str(voice_cfg.get("qwen3_tts_model_id", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")),
            "--mode", str(voice_cfg.get("qwen3_tts_mode", "voice_design")),
            "--language", str(voice_cfg.get("qwen3_tts_language", "Russian")),
            "--speaker", str(voice_cfg.get("qwen3_tts_speaker", "Ryan")),
            "--instruct", str(voice_cfg.get("qwen3_tts_instruct", "")),
            "--device-map", str(voice_cfg.get("qwen3_tts_device_map", "auto")),
            "--dtype", str(voice_cfg.get("qwen3_tts_dtype", "auto")),
            "--attn", str(voice_cfg.get("qwen3_tts_attn_implementation", "sdpa")),
            "--gpu-memory-gb", str(voice_cfg.get("qwen3_tts_gpu_memory_limit_gb", 0) or 0),
            "--cpu-memory-gb", str(voice_cfg.get("qwen3_tts_cpu_memory_limit_gb", 0) or 0),
            "--max-new-tokens", str(int(voice_cfg.get("qwen3_tts_max_new_tokens", 1024))),
        ]
        if bool(voice_cfg.get("qwen3_tts_do_sample", False)):
            cmd.append("--do-sample")
        log("Qwen3-TTS: запускаю одноразовый рендер-процесс. Лучше включить qwen3_tts_persistent_worker=true.")
        res = run_subprocess(cmd, timeout=int(voice_cfg.get("tts_subprocess_timeout_sec", 900)))
        combined = ((res.stderr or "") + "\n" + (res.stdout or "")).strip()
        if res.returncode != 0 or not wav_path.exists():
            log(f"Qwen3-TTS не смог создать озвучку, код {res.returncode}:")
            log(combined[-3000:] if combined else "stderr/stdout пустые")
            log("Подсказка: запусти install_qwen3_tts_windows.bat. Первый запуск может долго качать модели с Hugging Face.")
            return None
        if combined and self.cfg.get("tts_debug_log", True):
            log("Qwen3-TTS stdout/stderr: " + combined[-700:])
        return wav_path

    def _wav_to_mp3(self, wav_path: Path, out_mp3: Path) -> bool:
        ffmpeg = str(self.cfg.get("ffmpeg_path", "ffmpeg"))
        if not executable_exists(ffmpeg):
            log("Не найден FFmpeg. Укажи путь к ffmpeg.exe в config.json или добавь ffmpeg в PATH.")
            return False
        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            ffmpeg,
            "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(wav_path),
            "-vn", "-ar", "44100", "-ac", "2", "-b:a", f"{int(self.cfg.get('bitrate_kbps', 128))}k",
            str(out_mp3),
        ]
        res = run_subprocess(cmd, timeout=120)
        if res.returncode != 0:
            log("FFmpeg не смог конвертировать озвучку в MP3:")
            log(res.stderr.strip() or res.stdout.strip())
            return False
        return out_mp3.exists() and out_mp3.stat().st_size > 1024

    def cleanup_cache(self) -> None:
        max_files = int(self.cfg.get("max_cached_spoken_files", 120))
        files = sorted(self.cache_dir.glob("host_*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[max_files:]:
            try:
                p.unlink()
            except Exception:
                pass
        cutoff = time.time() - 24 * 3600
        for p in self.tmp_dir.glob("*"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except Exception:
                pass


