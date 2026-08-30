# TITAN IPTV v2

Pipeline aislado de producción para recopilar fuentes IPTV públicas, normalizarlas, deduplicarlas por URL y generar playlists por país.

## Países iniciales

Argentina, España, Italia, Reino Unido, Estados Unidos y Brasil.

## Seguridad y calidad

- `main` no participa en este pipeline.
- Solo fuentes públicas.
- No se almacenan credenciales, tokens ni enlaces privados.
- Las URLs se normalizan antes de deduplicar.
- Una URL duplicada se conserva una sola vez.
- Los streams fallidos deben pasar a cuarentena antes de su eliminación definitiva.
- Las playlists TITAN se generan en `titan_v2/playlists/`.

## Fuentes base

Se usa `iptv-org` como fuente pública estructurada. El proyecto publica playlists agrupadas por país y categoría. Las fuentes comunitarias de Reddit se tratan únicamente como descubrimiento y requieren un enlace directo público verificable.

## Uso local

```bash
python titan_v2/build_playlist.py input.m3u [input2.m3u ...]
```

El builder produce `all.m3u` y las seis playlists nacionales configuradas.
