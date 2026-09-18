import copy
import http.client
import json
import tempfile
import threading
import unittest
import urllib.parse
from http.server import HTTPServer
from pathlib import Path

from ai_truck_radio_app.config import DEFAULT_CONFIG, save_json
from ai_truck_radio_app.entertainment_history import _path
from ai_truck_radio_app.server import make_handler


class _LM:
    def list_models(self):
        return []

    def pick_model(self):
        return "local-model"


class _Engine:
    def __init__(self):
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.cfg["show_plan_enabled"] = True
        self.lm = _LM()

    def update_config(self, updates):
        self.cfg.update(updates)
        self.last_updates = dict(updates)


class ApiConfigSecurityTests(unittest.TestCase):
    def setUp(self):
        self.engine = _Engine()
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(self.engine, self.engine.cfg))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def post(self, path, values, headers=None):
        body = urllib.parse.urlencode(values)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        base_headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body.encode()))}
        base_headers.update(headers or {})
        conn.request("POST", path, body=body, headers=base_headers)
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        conn.close()
        return response.status, payload

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.server.server_port}"})
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        conn.close()
        return response.status, payload

    def test_save_config_is_partial_and_accepts_explicit_false(self):
        status, data = self.post("/api/save_config", {"weather_city": "Владивосток"})
        self.assertEqual(200, status)
        self.assertTrue(data["ok"])
        self.assertTrue(self.engine.cfg["show_plan_enabled"])
        status, _ = self.post("/api/save_config", {"_checkbox_keys": "show_plan_enabled", "show_plan_enabled": "false"})
        self.assertEqual(200, status)
        self.assertFalse(self.engine.cfg["show_plan_enabled"])

    def test_host_profiles_and_paths_are_not_silently_dropped(self):
        hosts = [{"name": "Ирина", "enabled": True, "air_weight": 1.5, "piper_voice": "ru_RU", "custom_voice_flag": "keep"}]
        status, _ = self.post("/api/save_config", {
            "music_dir": "D:/music",
            "ffmpeg_path": "D:/bin/ffmpeg.exe",
            "hosts_json": json.dumps(hosts, ensure_ascii=False),
        })
        self.assertEqual(200, status)
        self.assertEqual("D:/music", self.engine.cfg["music_dir"])
        self.assertEqual("ru_RU", self.engine.cfg["hosts"][0]["piper_voice"])
        self.assertEqual("keep", self.engine.cfg["hosts"][0]["custom_voice_flag"])

    def test_invalid_numbers_and_unsafe_history_path_are_rejected(self):
        status, _ = self.post("/api/save_config", {"music_volume": "NaN"})
        self.assertEqual(400, status)
        status, _ = self.post("/api/save_config", {"entertainment_history_file": "../outside.json"})
        self.assertEqual(400, status)

    def test_schema_ranges_cover_forward_compatible_numeric_fields(self):
        status, payload = self.get("/api/config/schema")
        self.assertEqual(200, status)
        schema = payload["schema"]
        self.assertEqual({"min": 1, "max": 65535}, {k: schema["port"][k] for k in ("min", "max")})
        self.assertEqual({"min": 0, "max": 1}, {k: schema["time_context_chance"][k] for k in ("min", "max")})
        self.assertEqual({"min": 0, "max": 1}, {k: schema["reference_asr_review_consensus_similarity"][k] for k in ("min", "max")})

        for key, value in (("port", "70000"), ("time_context_chance", "-0.1"), ("reference_asr_review_consensus_similarity", "1.1")):
            status, data = self.post("/api/save_config", {key: value})
            self.assertEqual(400, status, key)
            self.assertFalse(data["ok"], key)
        self.assertEqual(DEFAULT_CONFIG["port"], self.engine.cfg["port"])
        self.assertEqual(DEFAULT_CONFIG["time_context_chance"], self.engine.cfg["time_context_chance"])
        self.assertEqual(DEFAULT_CONFIG["reference_asr_review_consensus_similarity"], self.engine.cfg["reference_asr_review_consensus_similarity"])

        status, data = self.post("/api/save_config", {"f5_tts_seed": "-1"})
        self.assertEqual(200, status)
        self.assertTrue(data["ok"])
        self.assertEqual(-1, self.engine.cfg["f5_tts_seed"])
        status, data = self.post("/api/save_config", {"f5_tts_seed": "-2"})
        self.assertEqual(400, status)
        self.assertFalse(data["ok"])

    def test_malformed_host_profiles_are_rejected(self):
        status, data = self.post("/api/save_config", {"hosts_json": "{broken"})
        self.assertEqual(400, status)
        self.assertFalse(data["ok"])

    def test_non_loopback_origin_is_rejected(self):
        status, data = self.post("/api/save_config", {"weather_city": "x"}, {"Origin": "http://evil.example"})
        self.assertEqual(403, status)
        self.assertFalse(data["ok"])

    def test_history_path_cannot_escape_cache(self):
        self.assertEqual(_path({"entertainment_history_file": "../secret.json"}).name, "entertainment_history.json")

    def test_atomic_json_write_leaves_valid_json_under_parallel_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            threads = [threading.Thread(target=save_json, args=(target, {"n": i})) for i in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertIn(json.loads(target.read_text(encoding="utf-8"))["n"], range(12))
