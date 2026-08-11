#!/bin/bash
# Script para actualizar la playlist de forma manual

echo "🔄 Actualizando playlist IPTV..."
python main.py

if [ $? -eq 0 ]; then
    echo "✅ Playlist actualizada exitosamente"
    echo ""
    echo "📊 Estadísticas:"
    head -1 playlist.m3u
    wc -l playlist.m3u
else
    echo "❌ Error al actualizar la playlist"
    exit 1
fi
