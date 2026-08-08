#!/usr/bin/env python3
"""
Script para categorizar canales sin categoría en la playlist.m3u
"""

import re
from pathlib import Path

def get_category(name: str) -> str:
    """Determina la categoría basada en el nombre del canal"""
    name_lower = name.lower()
    
    # Canales Argentinos
    if any(x in name_lower for x in ['c5n', 'america tv', 'el trece', 'el nueve', 'telefe', 
                                       'la nacion', 'tn ', 'tn,', 'tn:', 'canal 26', 'volver', 
                                       'canal 7', 'argentina', '26tv', 'america', 'net tv',
                                       'argentinisima', 'tele', 'ln ', 'ln,', 'a24', 'l.n.']):
        return 'Argentina'
    
    # Series y Novelas
    if any(x in name_lower for x in ['novela', 'telenovela', 'tln', 'tlnovelas', 'series hd',
                                       'gol tv', 'movie box', 'telemundo']):
        return 'Entretenimiento / Cine / Series'
    
    # Películas
    if any(x in name_lower for x in ['movie', 'film', 'películas', 'cine', 'warner', 'paramount',
                                       'universal', 'syfy', 'amc', 'axn']):
        return 'Cine / Películas'
    
    # Deportes
    if any(x in name_lower for x in ['sports', 'deporte', 'espn', 'fox sports', 'dsports',
                                       'movistar deportes', 'tigo sports', 'golperu', 'futbol',
                                       'golf channel', 'nba', 'nfl', 'mlb']):
        return 'Deportes'
    
    # Infantiles
    if any(x in name_lower for x in ['adult swim', 'cartoon', 'kids', 'nickelodeon', 'disney',
                                       'infan', 'baby', 'tooncast', 'boomerang', 'pj masks',
                                       'channel', 'canal infantil']):
        return 'Infantiles'
    
    # Documentales
    if any(x in name_lower for x in ['documental', 'discovery', 'natgeo', 'nat geo', 'history',
                                       'animal planet', 'bbc', 'investigacion', 'documental',
                                       'xphere', 'cultura']):
        return 'Documentales y Cultura'
    
    # Música
    if any(x in name_lower for x in ['music', 'musica', 'mtv', 'vh1', 'canal music', 'radio']):
        return 'Música'
    
    # Noticias
    if any(x in name_lower for x in ['news', 'noticias', 'cnn', 'bbc', 'france', 'informativo',
                                       'tv noticias', 'noticiero', 'ntv', 'ntn24']):
        return 'Informativos'
    
    # Variedad/Entretenimiento
    if any(x in name_lower for x in ['tnt', 'hbo', 'cubavisión', 'rtv', 'teletanc', 'encantu',
                                       'videostar', 'entertainment', 'entretenimiento']):
        return 'Entretenimiento Premium'
    
    # Contenido adulto
    if any(x in name_lower for x in ['xxx', 'porno', 'adulto', 'adult', 'sexy', '18+']):
        return 'Adulto'
    
    # Predeterminado
    return 'Otros'

def categorize_playlist():
    """Categoriza todos los canales sin categoría en la playlist"""
    
    playlist_path = Path('playlist.m3u')
    content = playlist_path.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    new_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Si es una línea EXTINF sin categoría
        if line.startswith('#EXTINF') and 'group-title="-"' in line:
            # Extraer el nombre del canal
            match = re.search(r',(.+)$', line)
            if match:
                channel_name = match.group(1).strip()
                category = get_category(channel_name)
                
                # Reemplazar group-title="-" con la categoría detectada
                new_line = re.sub(
                    r'group-title="-"',
                    f'group-title="{category}"',
                    line
                )
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        elif line.startswith('#EXTINF') and 'group-title' not in line:
            # Canal sin group-title completamente
            match = re.search(r',(.+)$', line)
            if match:
                channel_name = match.group(1).strip()
                category = get_category(channel_name)
                
                # Agregar group-title antes del nombre
                new_line = line.replace(',', f' group-title="{category}",', 1)
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
        
        i += 1
    
    # Escribir el archivo actualizado
    output = '\n'.join(new_lines)
    playlist_path.write_text(output, encoding='utf-8')
    
    print("✓ Playlist categorizada exitosamente")

if __name__ == '__main__':
    categorize_playlist()
