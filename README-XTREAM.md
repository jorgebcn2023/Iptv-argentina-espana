# Prototipo de API compatible con Xtream Codes

API personal, de solo lectura, basada en la playlist M3U de la rama `feature/titan-iptv-v2`.

## Qué hace

- Lee y almacena en caché la playlist fuente.
- Expone `/player_api.php` con autenticación, categorías y catálogo de canales en directo.
- Expone `/get.php` para generar una lista M3U Plus.
- Conserva las directivas `#EXTVLCOPT`, `#KODIPROP`, `#EXTHTTP` y `#EXTGRP` en la exportación M3U.
- Expone `/health` para comprobar carga y número de canales.

## Limitaciones importantes

- No es el software original Xtream Codes; es un prototipo de compatibilidad.
- No aloja, transcodifica ni hace proxy de vídeo. La ruta `/live/...` redirige a la URL original.
- Los encabezados especiales no se pueden aplicar a la petición remota mediante una redirección HTTP. Si un canal depende de ellos, puede funcionar en el M3U original y fallar a través de la ruta de reproducción Xtream. La exportación M3U intenta conservar las directivas.
- La guía EPG no está incluida; los endpoints EPG devuelven datos vacíos.
- La numeración de canales se deriva del orden de la playlist y puede cambiar si se reordena la fuente.
- No se debe publicar el servicio sin HTTPS ni reutilizar contraseñas personales.

## Despliegue gratuito de prueba en Render

1. Crear un servicio web desde este repositorio y elegir la rama `xtream-api-prototype`.
2. Usar `render.yaml` o configurar:
   - Build: `pip install -r requirements-xtream.txt`
   - Start: `uvicorn xtream_api:app --host 0.0.0.0 --port $PORT`
3. Definir en las variables de entorno del servicio:
   - `XTREAM_USERNAME`: elegir un nombre de usuario nuevo.
   - `XTREAM_PASSWORD`: generar una contraseña larga y única.
   - `PLAYLIST_URL`: URL raw de la rama deseada.
4. No poner las credenciales en GitHub, en este README ni en capturas públicas.

## Endpoints

- `GET /`
- `GET /health`
- `GET /player_api.php?username=...&password=...`
- `GET /player_api.php?username=...&password=...&action=get_live_categories`
- `GET /player_api.php?username=...&password=...&action=get_live_streams`
- `GET /get.php?username=...&password=...&type=m3u_plus&output=ts`
- `GET /live/USUARIO/CONTRASEÑA/ID.ts`

El servicio requiere configurar credenciales antes de que los endpoints de catálogo respondan. No se incluyen credenciales por defecto.
