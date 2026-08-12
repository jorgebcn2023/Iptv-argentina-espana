from pathlib import Path
import shutil

source = Path("playlists/playlist_IPTV_ARG_ESP_FINAL.m3u")
output = Path("playlist_IPTV_ARG_ESP_FINAL.m3u")

shutil.copy(source, output)
print(output)
