# TITAN IPTV v2

Pipeline aislado para optimizar la playlist IPTV sin modificar la producción de `main`.

## Flujo

`discover -> normalize -> deduplicate -> validate -> classify -> build`

- Fuentes públicas de GitHub y Reddit se mantienen como entradas declarativas.
- La deduplicación usa URL normalizada como clave primaria.
- Las URLs no verificadas se mantienen fuera de la playlist publicada.
- Las listas generadas se organizan por país.
- Esta rama es experimental hasta completar validación y revisión.

## Seguridad

No incorpora credenciales, listas privadas, códigos Xtream ni mecanismos para eludir controles de acceso. Solo se procesan fuentes públicas.
