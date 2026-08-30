# TITAN IPTV v2 — Build Status

Status: `BOOTSTRAPPED`

Branch: `feature/titan-iptv-v2`

Production (`main`): untouched.

## Implemented

- Source registry for public GitHub and Reddit discovery.
- Country configuration for AR, ES, IT, GB, US and BR.
- URL normalization and exact normalized-URL deduplication.
- Separate TITAN output namespace.
- Quarantine policy for failed streams.
- Policy rejecting private credentials and paid streams.

## Pending runtime stage

- Fetch and parse all configured source playlists.
- Validate individual stream HTTP responses.
- Classify channels using metadata and country aliases.
- Generate country playlists and consolidated TITAN playlist.
- Produce machine-readable validation/deduplication reports.

No production playlist is replaced by this branch.
