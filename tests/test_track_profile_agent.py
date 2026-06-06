# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_track_profiles as profiles  # noqa: E402
from track_profile_agent import _canonical_url, _unwrap_search_url  # noqa: E402


class TrackProfileAgentTests(unittest.TestCase):
    def test_unwraps_yahoo_result_url(self) -> None:
        wrapped = (
            "https://r.search.yahoo.com/_ylt=x/RV=2/RE=1/RO=10/"
            "RU=https%3a%2f%2fen.wikipedia.org%2fwiki%2fWild_Light_%28album%29/RK=2/RS=x"
        )
        self.assertEqual(
            _unwrap_search_url(wrapped),
            "https://en.wikipedia.org/wiki/Wild_Light_(album)",
        )

    def test_canonical_url_merges_http_and_https(self) -> None:
        self.assertEqual(
            _canonical_url("http://www.en.wikipedia.org/wiki/Test#History"),
            "https://en.wikipedia.org/wiki/Test",
        )

    def test_normalized_profile_uses_expected_schema_and_selected_sources(self) -> None:
        research = {
            "queries": ["65daysofstatic Wild Light album"],
            "pages": [
                {"url": "https://example.com/one", "title": "One", "text": "Evidence one"},
                {"url": "https://example.com/two", "title": "Two", "text": "Evidence two"},
            ],
        }
        result = profiles._normalize_agent_profile(
            {
                "description": "Короткое описание.",
                "song_context": "Трек входит в альбом.",
                "used_source_ids": [2, 999],
            },
            artist="65daysofstatic",
            title="The Undertow",
            file_name="65daysofstatic - The Undertow.mp3",
            model="test-model",
            research=research,
        )
        self.assertEqual(result["_cleanup_meta"]["schema_version"], "radio_track_profile")
        self.assertEqual(result["sources"], ["https://example.com/two"])
        self.assertEqual(result["research_status"], "partial")
        self.assertEqual(result["display_title"], "65daysofstatic — The Undertow")

    def test_unverified_profile_does_not_claim_sources(self) -> None:
        result = profiles._normalize_agent_profile(
            {"description": "Описание по имени файла.", "used_source_ids": []},
            artist="Artist",
            title="Track",
            file_name="Artist - Track.mp3",
            model="test-model",
            research={"queries": [], "pages": []},
        )
        self.assertEqual(result["research_status"], "unverified")
        self.assertEqual(result["sources"], [])

    def test_normalization_preserves_file_identity_and_removes_evening_framing(self) -> None:
        result = profiles._normalize_agent_profile(
            {
                "artist": "Ärtist",
                "title": "Träck",
                "display_title": "Ärtist - Träck",
                "radio_angle": "Идеально для вечернего эфира. Подчеркнуть ритм композиции.",
                "used_source_ids": [],
            },
            artist="Artist",
            title="Track",
            file_name="Artist - Track.mp3",
            model="test-model",
            research={"queries": [], "pages": []},
        )
        self.assertEqual(result["display_title"], "Artist — Track")
        self.assertEqual(result["artist"], "Artist")
        self.assertNotIn("вечер", result["radio_angle"].lower())
        self.assertIn("ритм", result["radio_angle"].lower())

    def test_song_facts_require_a_track_matching_source(self) -> None:
        result = profiles._normalize_agent_profile(
            {
                "song_context": "Выдуманная связь с другой записью.",
                "song_fact": "Выдуманный факт.",
                "interesting_fact": "Ещё один факт.",
                "used_source_ids": [1],
            },
            artist="Artist",
            title="Track",
            file_name="Artist - Track.mp3",
            model="test-model",
            research={
                "queries": [],
                "pages": [
                    {
                        "url": "https://example.com/artist",
                        "title": "Artist biography",
                        "text": "Artist biography",
                        "artist_match": True,
                        "track_match": False,
                    }
                ],
            },
        )
        self.assertEqual(result["song_context"], "")
        self.assertEqual(result["song_fact"], "")
        self.assertEqual(result["interesting_fact"], "")

    def test_list_text_fields_are_joined_without_python_brackets(self) -> None:
        result = profiles._normalize_agent_profile(
            {
                "avoid": ["Не выдумывать факты.", "Не путать исполнителя."],
                "used_source_ids": [],
            },
            artist="Artist",
            title="Track",
            file_name="Artist - Track.mp3",
            model="test-model",
            research={"queries": [], "pages": []},
        )
        self.assertNotIn("[", result["avoid"])
        self.assertIn("Не путать исполнителя.", result["avoid"])


if __name__ == "__main__":
    unittest.main()
