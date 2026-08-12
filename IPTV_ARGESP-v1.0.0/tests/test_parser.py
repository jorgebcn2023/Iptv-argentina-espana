from scripts.m3u_parser import parse_entries

def test_preserve_metadata():
    text = """#EXTM3U
#EXTINF:-1,Test
#EXTVLCOPT:http-user-agent=Agent/1.0
#EXTVLCOPT:http-referrer=https://example.com/
http://example.com/live.m3u8
"""
    entries = parse_entries(text)
    assert len(entries) == 1
    assert entries[0].url.endswith(".m3u8")
    assert len(entries[0].metadata) == 3
