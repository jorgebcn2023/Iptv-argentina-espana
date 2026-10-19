import os
import unittest
from unittest.mock import Mock, patch

import xtream_api


SAMPLE = """#EXTM3U
#EXTINF:-1 tvg-id="ar.one" tvg-logo="https://img.example/one.png" group-title="Argentina",Canal Uno
#EXTVLCOPT:http-user-agent=TestAgent/1.0
#EXTVLCOPT:http-referrer=https://example.org/
https://stream.example/one/index.m3u8
#EXTINF:-1 group-title="España",Canal Dos
https://stream.example/two.m3u8
#EXTINF:-1 group-title="España",Canal Dos alternativo
https://stream.example/two-alt.m3u8
"""


class PlaylistParserTests(unittest.TestCase):
    def test_parses_channels_categories_and_headers(self):
        channels = xtream_api.parse_m3u(SAMPLE)
        self.assertEqual(len(channels), 3)
        self.assertEqual(channels[0]["name"], "Canal Uno")
        self.assertEqual(channels[0]["group"], "Argentina")
        self.assertEqual(channels[0]["tvg_id"], "ar.one")
        self.assertEqual(
            channels[0]["directives"],
            [
                "#EXTVLCOPT:http-user-agent=TestAgent/1.0",
                "#EXTVLCOPT:http-referrer=https://example.org/",
            ],
        )
        self.assertEqual(channels[0]["url"], "https://stream.example/one/index.m3u8")
        self.assertEqual(channels[1]["group"], "España")

    def test_preserves_original_extinf_and_names_with_commas(self):
        entry = '#EXTINF:-1 tvg-country="AR" group-title="News" tvg-chno="5",News, World'
        channels = xtream_api.parse_m3u("#EXTM3U\\n" + entry + "\\nhttps://stream.example/news.m3u8\\n")
        self.assertEqual(channels[0]["name"], "News, World")
        self.assertEqual(channels[0]["extinf"], entry)

    def test_does_not_deduplicate_alternative_streams(self):
        channels = xtream_api.parse_m3u(SAMPLE)
        self.assertEqual(channels[1]["name"], "Canal Dos")
        self.assertEqual(channels[2]["name"], "Canal Dos alternativo")
        self.assertNotEqual(channels[1]["url"], channels[2]["url"])

    def test_category_ids_are_stable_for_same_order(self):
        channels = xtream_api.parse_m3u(SAMPLE)
        first = xtream_api.category_id_map(channels)
        second = xtream_api.category_id_map(channels)
        self.assertEqual(first, second)
        self.assertEqual(first["Argentina"], "1")
        self.assertEqual(first["España"], "2")


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.old_user = xtream_api.USERNAME
        self.old_password = xtream_api.PASSWORD
        xtream_api.USERNAME = "test-user"
        xtream_api.PASSWORD = "test-password"

    def tearDown(self):
        xtream_api.USERNAME = self.old_user
        xtream_api.PASSWORD = self.old_password

    def test_auth_accepts_exact_credentials(self):
        self.assertIsNone(xtream_api.check_auth("test-user", "test-password"))

    def test_auth_rejects_wrong_credentials(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            xtream_api.check_auth("test-user", "wrong")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_auth_fails_closed_if_not_configured(self):
        from fastapi import HTTPException
        xtream_api.USERNAME = ""
        xtream_api.PASSWORD = ""
        with self.assertRaises(HTTPException) as ctx:
            xtream_api.check_auth("anything", "anything")
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
