# Automatización de la Playlist IPTV

## 📋 Descripción

Este proyecto cuenta con **automatización mediante GitHub Actions** para mantener la playlist `playlist.m3u` actualizada automáticamente desde las fuentes externas configuradas.

## 🔄 Cómo Funciona

### GitHub Actions (Automático)

El workflow `update-playlist.yml` ejecuta automáticamente:

1. **Cada día a las 00:00 UTC** (configurable)
2. **Manualmente** desde la sección Actions de GitHub
3. Descarga las playlists de las fuentes configuradas en `config/sources.yml`
4. Filtra canales según las palabras clave en `config/settings.yml`
5. Genera `playlist.m3u` actualizada
6. Commitea y pushea los cambios automáticamente

### Fuentes Configuradas

Las fuentes se encuentran en `config/sources.yml`:

```yaml
sources:
  - http://138.59.227.20:8000/playlist.m3u8
  - http://45.5.118.152:8000/playlist.m3u8
  - https://raw.githubusercontent.com/JMigue85/IPTV-SV/refs/heads/main/IPTVSV.m3u
```

### Palabras Clave Permitidas

Se filtran en `config/settings.yml`:

```yaml
allowed_keywords:
  - argentina
  - españa
  - spain
  - internacional
  - international
```

## 🎯 URLs de Acceso

### URL de la Playlist Actualizada

```
https://raw.githubusercontent.com/jorgebcn2023/Iptv-argentina-espana/main/playlist.m3u
```

**Uso**: Copia esta URL en tu reproductor IPTV (VLC, Kodi, etc.)

## 🛠️ Actualización Manual

Si deseas actualizar la playlist manualmente:

### Opción 1: Ejecutar el script
```bash
chmod +x update.sh
./update.sh
```

### Opción 2: Ejecutar Python directamente
```bash
python main.py
```

## 📊 Estadísticas

- **Última actualización**: Automática diariamente
- **Canales**: ~334 entradas filtradas
- **Países**: Argentina, España, Internacional
- **Frecuencia**: Diariamente a las 00:00 UTC

## ⚙️ Configuración de la Automatización

Para cambiar el horario de ejecución, edita `.github/workflows/update-playlist.yml`:

```yaml
on:
  schedule:
    # Formato cron: minuto, hora, día, mes, día de la semana
    - cron: '0 0 * * *'  # Cambia estos valores
```

Ejemplos:
- `'0 */6 * * *'` → Cada 6 horas
- `'30 2 * * *'` → Diariamente a las 02:30
- `'0 12 * * 0'` → Domingos a las 12:00

## 🔧 Ejecutar Manualmente desde GitHub

1. Ve a **Actions** en tu repositorio
2. Selecciona **Update IPTV Playlist**
3. Haz clic en **Run workflow**

## 📝 Notas

- Los cambios se commitean automáticamente con mensaje de fecha/hora
- Si no hay cambios, no se crea commit
- El token de GitHub se usa automáticamente para permisos de push

## 🚀 Próximas Mejoras (Opcional)

- Agregar validación de URLs
- Generar estadísticas de canales
- Crear notificaciones de errores
- Generar múltiples playlists por país
