# TITAN IPTV v2

Desarrollo aislado sobre `feature/titan-iptv-v2`. La rama `main` y la playlist de producción no se modifican.

## Objetivo

Construir una playlist reproducible a partir de fuentes públicas, con normalización, deduplicación por URL, clasificación por país, validación y cuarentena de fallos.

## Fuentes iniciales

- iptv-org/iptv: colección pública mantenida en GitHub.
- Free-TV/IPTV: colección pública orientada a canales gratuitos.
- Reddit: solo como canal de descubrimiento; cada URL debe pasar validación y políticas antes de incorporarse.

## Seguridad y calidad

- No se incorporan credenciales, Xtream Codes ni accesos privados.
- No se incorporan streams de pago.
- Las URLs se normalizan antes de deduplicar.
- Una URL fallida pasa a cuarentena y no destruye una fuente válida existente.
- La producción queda separada de TITAN hasta una validación explícita.

## Flujo

`discover -> normalize -> dedupe -> validate -> classify -> build -> report`

## Países iniciales

Argentina, España, Italia, Reino Unido, Estados Unidos y Brasil.
