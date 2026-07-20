# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import random
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ai_truck_radio_app.config import (
    APP_NAME,
    APP_VERSION,
    BASE_DIR,
    RUS_MONTHS,
    RUS_WEEKDAYS,
    log,
    require_http_url,
)


class WeatherClient:
    WEATHER_CODES_RU = {
        0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
        45: "туман", 48: "изморозь и туман",
        51: "слабая морось", 53: "морось", 55: "сильная морось",
        56: "ледяная морось", 57: "сильная ледяная морось",
        61: "слабый дождь", 63: "дождь", 65: "сильный дождь",
        66: "ледяной дождь", 67: "сильный ледяной дождь",
        71: "слабый снег", 73: "снег", 75: "сильный снег", 77: "снежные зёрна",
        80: "кратковременный дождь", 81: "ливень", 82: "сильный ливень",
        85: "снегопад", 86: "сильный снегопад",
        95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
    }

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.last_fetch_ts = 0.0
        self.last_error_ts = 0.0
        self.cached_text = ""
        self.lock = threading.Lock()

    def _url_json(self, url: str, timeout: float) -> Dict[str, Any]:
        url = require_http_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

    def _open_meteo(self, city: str, timeout: float) -> str:
        q_city = urllib.parse.quote(city)
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={q_city}&count=1&language=ru&format=json"
        geo = self._url_json(geo_url, timeout)
        results = geo.get("results") or []
        if not results:
            return ""
        place = results[0]
        lat = place.get("latitude")
        lon = place.get("longitude")
        if lat is None or lon is None:
            return ""
        resolved_name = str(place.get("name") or city).strip() or city
        admin = str(place.get("admin1") or "").strip()
        country = str(place.get("country") or "").strip()
        location = resolved_name
        if admin and admin.lower() not in resolved_name.lower():
            location += f", {admin}"
        elif country and country.lower() not in resolved_name.lower():
            location += f", {country}"

        units = str(self.cfg.get("weather_units", "metric")).lower()
        temp_unit = "fahrenheit" if units == "us" else "celsius"
        wind_unit = "mph" if units == "us" else "kmh"
        forecast_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            f"&temperature_unit={temp_unit}&wind_speed_unit={wind_unit}&timezone=auto"
        )
        data = self._url_json(forecast_url, timeout)
        cur = data.get("current") or {}
        units_data = data.get("current_units") or {}
        temp = cur.get("temperature_2m")
        feels = cur.get("apparent_temperature")
        code = cur.get("weather_code")
        wind = cur.get("wind_speed_10m")
        desc = self.WEATHER_CODES_RU.get(int(code), "погода обновлена") if code is not None else ""
        temp_suffix = units_data.get("temperature_2m") or ("°F" if units == "us" else "°C")
        wind_suffix = units_data.get("wind_speed_10m") or ("mph" if units == "us" else "км/ч")
        parts = [f"{location}: {desc}" if desc else location]
        if temp not in [None, ""]:
            parts.append(f"{temp}{temp_suffix}")
        if feels not in [None, ""]:
            parts.append(f"ощущается как {feels}{temp_suffix}")
        if wind not in [None, ""]:
            parts.append(f"ветер {wind} {wind_suffix}")
        return ", ".join(parts)

    def _wttr(self, city: str, timeout: float) -> str:
        q_city = urllib.parse.quote(city)
        units = "u" if str(self.cfg.get("weather_units", "metric")).lower() == "us" else "m"
        url = f"https://wttr.in/{q_city}?format=j1&lang=ru&{units}"
        data = self._url_json(url, timeout)
        cc = (data.get("current_condition") or [{}])[0]
        desc_items = cc.get("lang_ru") or cc.get("weatherDesc") or []
        desc = ""
        if desc_items and isinstance(desc_items[0], dict):
            desc = str(desc_items[0].get("value") or "").strip()
        temp = cc.get("temp_C") if units == "m" else cc.get("temp_F")
        feels = cc.get("FeelsLikeC") if units == "m" else cc.get("FeelsLikeF")
        wind = cc.get("windspeedKmph") if units == "m" else cc.get("windspeedMiles")
        unit_temp = "°C" if units == "m" else "°F"
        unit_wind = "км/ч" if units == "m" else "миль/ч"
        parts = [f"{city}: {desc}" if desc else city]
        if temp not in [None, ""]:
            parts.append(f"{temp}{unit_temp}")
        if feels not in [None, ""]:
            parts.append(f"ощущается как {feels}{unit_temp}")
        if wind not in [None, ""]:
            parts.append(f"ветер {wind} {unit_wind}")
        return ", ".join(parts)

    def get_weather_text(self) -> str:
        if not self.cfg.get("weather_enabled", False):
            return ""
        city = str(self.cfg.get("weather_city") or "").strip()
        if not city:
            return ""
        cache_sec = max(60, int(float(self.cfg.get("weather_cache_minutes", 45)) * 60))
        error_cooldown = max(30, int(float(self.cfg.get("weather_error_cooldown_sec", 600))))
        now = time.time()
        with self.lock:
            if self.cached_text and now - self.last_fetch_ts < cache_sec:
                return self.cached_text
            # Если сервис погоды тупит, не тормозим каждую вставку. Возвращаем старую погоду, если она есть.
            if self.last_error_ts and now - self.last_error_ts < error_cooldown and self.cached_text:
                return self.cached_text
            if self.last_error_ts and now - self.last_error_ts < error_cooldown and not self.cached_text:
                return ""
        timeout = max(1.5, float(self.cfg.get("weather_timeout_sec", 4)))
        provider = str(self.cfg.get("weather_provider", "open-meteo")).lower().strip()
        providers = [provider]
        if provider == "auto":
            providers = ["open-meteo", "wttr"]
        elif provider == "open-meteo":
            providers = ["open-meteo", "wttr"]
        elif provider == "wttr":
            providers = ["wttr", "open-meteo"]

        last_err = None
        for pr in providers:
            try:
                text = self._open_meteo(city, timeout) if pr == "open-meteo" else self._wttr(city, timeout)
                if text:
                    with self.lock:
                        self.cached_text = text
                        self.last_fetch_ts = time.time()
                        self.last_error_ts = 0.0
                    return text
            except Exception as e:
                last_err = e
                continue
        with self.lock:
            self.last_error_ts = time.time()
        if last_err:
            log(f"Погоду не удалось получить: {last_err}")
        return ""

def current_time_text() -> str:
    now = time.localtime()
    weekday = RUS_WEEKDAYS[now.tm_wday]
    month = RUS_MONTHS[now.tm_mon - 1]
    return f"{now.tm_hour:02d}:{now.tm_min:02d}, {weekday}, {now.tm_mday} {month} {now.tm_year}"


def current_time_text_at_offset(offset_sec: float = 0.0) -> str:
    try:
        now = time.localtime(time.time() + float(offset_sec or 0.0))
    except Exception:
        now = time.localtime()
    weekday = RUS_WEEKDAYS[now.tm_wday]
    month = RUS_MONTHS[now.tm_mon - 1]
    return f"{now.tm_hour:02d}:{now.tm_min:02d}, {weekday}, {now.tm_mday} {month} {now.tm_year}"


_NUM_0_59 = [
    "ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
    "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать", "двадцать",
]
_TENS = {2: "двадцать", 3: "тридцать", 4: "сорок", 5: "пятьдесят"}


def _num_words_ru(n: int) -> str:
    n = int(n)
    if 0 <= n < len(_NUM_0_59):
        return _NUM_0_59[n]
    tens, ones = divmod(n, 10)
    base = _TENS.get(tens, str(n))
    return base if ones == 0 else f"{base} {_NUM_0_59[ones]}"


def _hour_word(hour: int) -> str:
    if hour % 10 == 1 and hour % 100 != 11:
        return "час"
    if hour % 10 in {2, 3, 4} and hour % 100 not in {12, 13, 14}:
        return "часа"
    return "часов"


def _minute_word(minute: int) -> str:
    if minute % 10 == 1 and minute % 100 != 11:
        return "минута"
    if minute % 10 in {2, 3, 4} and minute % 100 not in {12, 13, 14}:
        return "минуты"
    return "минут"


def daypart_name_for_hour(hour: int) -> str:
    hour = int(hour) % 24
    if 5 <= hour <= 11:
        return "утро"
    if 12 <= hour <= 17:
        return "день"
    if 18 <= hour <= 22:
        return "вечер"
    return "ночь"


def daypart_suffix_for_hour(hour: int) -> str:
    hour = int(hour) % 24
    if 5 <= hour <= 11:
        return "утра"
    if 12 <= hour <= 17:
        return "дня"
    if 18 <= hour <= 22:
        return "вечера"
    return "ночи"


def current_time_spoken_text_at_offset(offset_sec: float = 0.0) -> str:
    try:
        now = time.localtime(time.time() + float(offset_sec or 0.0))
    except Exception:
        now = time.localtime()
    weekday = RUS_WEEKDAYS[now.tm_wday]
    month = RUS_MONTHS[now.tm_mon - 1]
    hour = int(now.tm_hour)
    minute = int(now.tm_min)
    return (
        f"сегодня ровно {_num_words_ru(hour)} {_hour_word(hour)} "
        f"{_num_words_ru(minute)} {_minute_word(minute)} {daypart_suffix_for_hour(hour)}, "
        f"{weekday}, {now.tm_mday} {month}"
    )


def is_night_now(cfg: Dict[str, Any]) -> bool:
    if not cfg.get("night_mode_enabled", True):
        return False
    hour = time.localtime().tm_hour
    start = int(cfg.get("night_start_hour", 22))
    end = int(cfg.get("night_end_hour", 6))
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def style_prompt(style: str, night: bool) -> str:
    style_l = (style or "универсальное радио").lower()
    if "уют" in style_l:
        base = "уютное музыкальное радио: мягко, дружелюбно, тёплый эфир, музыка, настроение, город, температура и слушатели"
    elif "душ" in style_l:
        base = "душевное музыкальное радио: живые ведущие, тёплый человеческий разговор, музыка, настроение, слушатели, время, город и погода"
    elif "кибер" in style_l:
        base = "киберпанк-радио: неон, синтетика, ночной город и музыка будущего, но без перегиба, машинной рутины и ролевых сцен"
    elif "хоррор" in style_l:
        base = "хоррор-эфир: загадочная атмосфера и лёгкое напряжение, но без трэша, без крика и без дорожной ролевой сцены"
    else:
        base = "универсальное локальное музыкальное радио: живые ведущие, музыка, настроение, слушатели, время, город и погода; без игр, симуляторов, кабины, рейсов, трасс и аудитории водителей"
    base += "; запрещены упоминания VR, игр, симуляторов, кабины, грузовиков, рейсов, трасс, водителей, дальнобойщиков и ситуации за рулём"
    if night:
        base += "; ночная подача — тише, атмосфернее, меньше бодрого крика"
    return base


def should_include_news(cfg: Dict[str, Any], random_fn: Optional[Callable[[], float]] = None) -> bool:
    """Make the single probability decision; the file reader never applies the chance again."""
    if not cfg.get("news_enabled", True):
        return False
    chance = max(0.0, min(1.0, float(cfg.get("news_chance", 0.35) or 0.0)))
    return (random_fn or random.random)() < chance


def read_news_line(cfg: Dict[str, Any]) -> str:
    if not cfg.get("news_enabled", True):
        return ""
    path = Path(str(cfg.get("news_file", "data/news.txt")))
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return ""
    try:
        lines = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
        if not lines:
            return ""
        count = max(1, int(cfg.get("news_lines_per_insert", 1)))
        return " ".join(random.sample(lines, k=min(count, len(lines))))
    except Exception as e:
        log(f"Не удалось прочитать новости из {path}: {e}")
        return ""


def read_greeting_line(cfg: Dict[str, Any]) -> str:
    if not cfg.get("listener_greetings_enabled", True):
        return ""
    path = Path(str(cfg.get("listener_greetings_file", "greetings.txt")))
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return ""
    try:
        lines = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
        return random.choice(lines) if lines else ""
    except Exception as e:
        log(f"Не удалось прочитать приветы из {path}: {e}")
        return ""


def read_greeting_line_unique(cfg: Dict[str, Any], used: set[str]) -> str:
    """Pick a listener greeting without repeats inside one preplanned window."""
    if not cfg.get("listener_greetings_enabled", True):
        return ""
    path = Path(str(cfg.get("listener_greetings_file", "greetings.txt")))
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return ""
    try:
        lines = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
        if not lines:
            return ""
        choices = [x for x in lines if x not in used] or lines
        val = random.choice(choices)
        used.add(val)
        return val
    except Exception as e:
        log(f"Не удалось прочитать приветы из {path}: {e}")
        return ""


def exact_hour_announcement_text(cfg: Dict[str, Any], now_struct: Optional[time.struct_time] = None) -> str:
    if not cfg.get("exact_hour_time_announce_enabled", True):
        return ""
    now = now_struct or time.localtime()
    window = max(0, int(cfg.get("exact_hour_window_minutes", 3) or 0))
    if not (now.tm_min <= window):
        return ""
    hour = now.tm_hour
    if hour == 0:
        human = "полночь"
    elif hour == 12:
        human = "ровно двенадцать дня"
    elif hour == 13:
        human = "ровно час дня"
    elif hour == 1:
        human = "ровно час ночи"
    else:
        suffix = "утра" if 2 <= hour <= 11 else ("дня" if 14 <= hour <= 17 else "вечера")
        display = hour if hour <= 12 else hour - 12
        human = f"ровно {display} часа {suffix}" if display in {2,3,4} else f"ровно {display} часов {suffix}"
    return f"Сейчас {human}. Можно один раз естественно проговорить время в эфире."

