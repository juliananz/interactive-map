import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from folium import plugins
from jenkspy import JenksNaturalBreaks
from shapely.geometry import Point, mapping
import re

# --- Paths ---
ageb_path = r"D:\SEC\datos\geograficos\05_coahuiladezaragoza\conjunto_de_datos\05a.shp"
mun_path  = r"D:\SEC\datos\geograficos\05_coahuiladezaragoza\conjunto_de_datos\05mun.shp"
pob_path  = r"D:\SEC\datos\poblacion\Poblacion por ageb san pedro.xlsx"

# --- Wrangler point ---
wrangler_lat = 25 + 45/60 + 54.9/3600
wrangler_lon = -(103 + 0/60 + 11.5/3600)
radius_km = 15

# --- TOTAL POPULATION (municipal) ---
TOTAL_POPULATION = 101041

# --- PUNTOS ADICIONALES ---
puntos_adicionales = [
    {
        "nombre": "Oficinas para prestar",
        "lat": 25 + 45/60 + 20.6/3600,
        "lon": -(102 + 59/60 + 26.3/3600),
        "tipo": "oficinas"
    },
    {
        "nombre": "6 hectareas disponibles",
        "lat": 25 + 44/60 + 58.3/3600,
        "lon": -(102 + 59/60 + 42.7/3600),
        "tipo": "terreno_6ha"
    },
    {
        "nombre": "3 hectareas disponibles",
        "lat": 25 + 44/60 + 49.6/3600,
        "lon": -(103 + 0/60 + 7.0/3600),
        "tipo": "terreno_3ha"
    },
    {
        "nombre": "6 hectareas disponibles (2)",
        "lat": 25 + 45/60 + 53.3/3600,
        "lon": -(103 + 0/60 + 58.4/3600),
        "tipo": "terreno_6ha"
    },
    {
        "nombre": "Subestacion electrica de San Pedro",
        "lat": 25 + 46/60 + 29.6/3600,
        "lon": -(103 + 7/60 + 21.0/3600),
        "tipo": "infraestructura"
    },
]

# --- Load data ---
print("Cargando datos...")
ageb = gpd.read_file(ageb_path)
mun  = gpd.read_file(mun_path)

print(f"\nLeyendo archivo Excel...")
pob = pd.read_excel(pob_path, sheet_name="Solo totales")

# --- Renombrar columnas ---
pob = pob.rename(columns={
    'Clave de entidad federativa': 'ENTIDAD',
    'Clave de municipio o demarcación territorial': 'MUN',
    'Clave de localidad': 'LOC',
    'Clave de AGEB': 'AGEB',
    'Población total': 'POBTOT'
})

# --- Build CVEGEO ---
pob['ENTIDAD'] = pob['ENTIDAD'].astype(str).str.zfill(2)
pob['MUN'] = pob['MUN'].astype(str).str.zfill(3)
pob['LOC'] = pob['LOC'].astype(str).str.zfill(4)

def format_ageb(ageb_val):
    ageb_str = str(ageb_val).strip().upper()
    if ageb_str == 'NAN' or ageb_str == '':
        return '0000'
    if ageb_str.isdigit():
        return ageb_str.zfill(4)
    else:
        if len(ageb_str) > 0 and ageb_str[0].isalpha():
            letra = ageb_str[0]
            numero = ageb_str[1:]
            if numero.isdigit():
                return letra + numero.zfill(3)
        return ageb_str.zfill(4)

pob['AGEB_FORMATTED'] = pob['AGEB'].apply(format_ageb)
pob['CVEGEO'] = pob['ENTIDAD'] + pob['MUN'] + pob['LOC'] + pob['AGEB_FORMATTED']
ageb['CVEGEO'] = ageb['CVEGEO'].astype(str).str.strip().str.upper()

# --- Merge ---
merged = ageb.merge(pob[['CVEGEO', 'POBTOT']], on='CVEGEO', how='inner')
print(f"AGEBs despues del merge: {len(merged)}")

# --- Reproject to WGS84 ---
merged = merged.to_crs(epsg=4326)
mun = mun.to_crs(epsg=4326)

# --- Crear buffer ---
wrangler_pt = Point(wrangler_lon, wrangler_lat)
wrangler_gdf = gpd.GeoDataFrame([{'geometry': wrangler_pt}], crs="EPSG:4326")
wrangler_utm = wrangler_gdf.to_crs(epsg=32613)
merged_utm = merged.to_crs(epsg=32613)
buffer_utm = wrangler_utm.buffer(radius_km * 1000)

merged_utm['intersects'] = merged_utm.intersects(buffer_utm.iloc[0])
filtered_utm = merged_utm[merged_utm['intersects']].copy()
print(f"AGEBs en buffer de {radius_km} km: {len(filtered_utm)}")

merged_filtered = filtered_utm.to_crs(epsg=4326)
buffer_wgs84 = buffer_utm.to_crs(epsg=4326)

# --- Population classification ---
merged_filtered["POBTOT"] = pd.to_numeric(merged_filtered["POBTOT"], errors="coerce").fillna(0)

if len(merged_filtered) == 0:
    print("\nERROR: No hay AGEBs")
    exit()

urban_population = merged_filtered['POBTOT'].sum()

n_classes = min(6, max(1, merged_filtered["POBTOT"].nunique()))

if n_classes > 1:
    nb = JenksNaturalBreaks(n_classes=n_classes)
    nb.fit(merged_filtered["POBTOT"])
    bins = nb.breaks_
else:
    min_pob = merged_filtered["POBTOT"].min()
    max_pob = merged_filtered["POBTOT"].max()
    bins = [min_pob, max_pob]

colors = ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c', '#fc4e2a'][:n_classes]

def assign_color(value):
    for i in range(len(bins) - 1):
        if bins[i] <= value < bins[i + 1]:
            return colors[i]
    return colors[-1]

merged_filtered["color_POBTOT"] = merged_filtered["POBTOT"].apply(assign_color)
mun_clip = mun[mun.intersects(buffer_wgs84.iloc[0])]

# --- Crear mapa ---
print(f"\nCreando mapa...")
m = folium.Map(
    location=[wrangler_lat, wrangler_lon],
    zoom_start=12,
    tiles='OpenStreetMap',
    control_scale=True
)

folium.TileLayer('CartoDB positron', name='Mapa Claro').add_to(m)

# --- AGEBs ---
print("Agregando AGEBs al mapa...")
for idx, row in merged_filtered.iterrows():
    geo_json = row['geometry'].__geo_interface__
    pop_val = int(row['POBTOT'])
    cvegeo_val = str(row['CVEGEO'])
    color_val = str(row['color_POBTOT'])

    feature = {
        "type": "Feature",
        "geometry": geo_json,
        "properties": {
            "CVEGEO": cvegeo_val,
            "POBTOT": pop_val,
            "fillColor": color_val
        }
    }

    tooltip_text = "AGEB: " + cvegeo_val + " | Pob: " + f"{pop_val:,}"

    folium.GeoJson(
        feature,
        style_function=lambda x: {
            'fillColor': x['properties']['fillColor'],
            'color': 'gray',
            'weight': 0.5,
            'fillOpacity': 0.6
        },
        highlight_function=lambda x: {
            'fillColor': x['properties']['fillColor'],
            'color': 'black',
            'weight': 2,
            'fillOpacity': 0.9
        },
        tooltip=tooltip_text
    ).add_to(m)

# Limites municipales
folium.GeoJson(
    mun_clip,
    style_function=lambda x: {
        'fillColor': 'none',
        'color': 'black',
        'weight': 2,
        'fillOpacity': 0
    },
    name='Limites Municipales'
).add_to(m)

# Circulo de 15 km
folium.Circle(
    location=[wrangler_lat, wrangler_lon],
    radius=radius_km * 1000,
    color='red',
    fill=False,
    weight=2,
    dash_array='10',
    popup='Radio de ' + str(radius_km) + ' km'
).add_to(m)

# Punto Wrangler
folium.Marker(
    [wrangler_lat, wrangler_lon],
    popup='<b>Wrangler San Pedro</b>',
    tooltip='Wrangler San Pedro',
    icon=folium.DivIcon(
        html='<div style="font-size:22px; color:red; text-align:center; line-height:22px;">&#9733;</div>',
        icon_size=(22, 22),
        icon_anchor=(11, 11)
    )
).add_to(m)

# --- Puntos adicionales ---
iconos_tipo = {
    'oficinas':        {'color': '#2196F3', 'symbol': '&#9632;'},
    'terreno_6ha':     {'color': '#4CAF50', 'symbol': '&#9650;'},
    'terreno_3ha':     {'color': '#8BC34A', 'symbol': '&#9650;'},
    'infraestructura': {'color': '#FF9800', 'symbol': '&#9889;'},
}

for punto in puntos_adicionales:
    icono = iconos_tipo.get(punto['tipo'], {'color': 'gray', 'symbol': '&#9679;'})
    popup_text = (
        "<b>" + punto['nombre'] + "</b><br>"
        "Lat: " + f"{punto['lat']:.6f}" + "<br>"
        "Lon: " + f"{punto['lon']:.6f}"
    )
    folium.Marker(
        [punto['lat'], punto['lon']],
        popup=popup_text,
        tooltip=punto['nombre'],
        icon=folium.DivIcon(
            html=(
                '<div style="font-size:16px; color:' + icono['color'] + '; '
                'text-align:center; line-height:16px; '
                '-webkit-text-stroke: 0.5px #333;">'
                + icono['symbol'] + '</div>'
            ),
            icon_size=(16, 16),
            icon_anchor=(8, 8)
        )
    ).add_to(m)

# --- LEGEND ---
legend_rows = ""
for i in range(len(bins) - 1):
    legend_rows += (
        '<div style="display:flex; align-items:center; margin:4px 0;">'
        '<span style="background-color:' + colors[i] + '; '
        'border:1px solid gray; width:20px; height:14px; '
        'display:inline-block; flex-shrink:0;"></span>'
        '<span style="margin-left:6px; font-size:12px;">'
        + f"{int(bins[i]):,}" + ' - ' + f"{int(bins[i+1]):,}"
        + '</span></div>'
    )

legend_html = (
    '<div style="'
    'position:fixed; bottom:30px; left:10px; '
    'width:220px; max-height:80vh; overflow-y:auto; '
    'background-color:rgba(255,255,255,0.95); '
    'border:2px solid #666; z-index:9999; '
    'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif; '
    'font-size:12px; padding:10px; border-radius:6px; '
    '-webkit-overflow-scrolling:touch; '
    'box-sizing:border-box;">'
    '<div style="font-weight:bold; font-size:13px; '
    'border-bottom:1px solid #ccc; padding-bottom:4px; margin-bottom:6px;">'
    'Poblacion por AGEB</div>'
    + legend_rows +
    '<div style="font-weight:bold; font-size:13px; '
    'border-top:1px solid #ccc; border-bottom:1px solid #ccc; '
    'padding:4px 0; margin:8px 0 4px 0;">'
    'Puntos de Interes</div>'
    '<div style="margin:3px 0;">'
    '<span style="color:red; font-size:14px;">&#9733;</span> Wrangler San Pedro</div>'
    '<div style="margin:3px 0;">'
    '<span style="color:#2196F3; font-size:14px;">&#9632;</span> Oficinas</div>'
    '<div style="margin:3px 0;">'
    '<span style="color:#4CAF50; font-size:14px;">&#9650;</span> Terrenos 6 ha</div>'
    '<div style="margin:3px 0;">'
    '<span style="color:#8BC34A; font-size:14px;">&#9650;</span> Terrenos 3 ha</div>'
    '<div style="margin:3px 0;">'
    '<span style="color:#FF9800; font-size:14px;">&#9889;</span> Infraestructura</div>'
    '<div style="margin-top:8px; font-size:11px; color:#444; '
    'border-top:1px solid #ccc; padding-top:6px;">'
    'Total AGEBs: ' + str(len(merged_filtered)) + '<br>'
    '<b>Pob. urbana: ' + f"{urban_population:,.0f}" + ' hab.</b><br>'
    '<b>Pob. total: ' + f"{TOTAL_POPULATION:,}" + ' hab.</b></div>'
    '</div>'
)

m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl().add_to(m)

# ============================================================
# POST-PROCESS: Rebuild HTML for iPhone/Safari/GitHub Pages
# ============================================================
output_path = r"D:\SEC\index.html"
m.save(output_path)

with open(output_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Extract parts
head_match = re.search(r'<head>(.*?)</head>', html, re.DOTALL)
head_content = head_match.group(1) if head_match else ''

body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL)
body_content = body_match.group(1) if body_match else ''

script_match = re.search(r'</body>\s*<script>(.*?)</script>', html, re.DOTALL)
map_script = script_match.group(1) if script_match else ''

# Parse head components
css_links = re.findall(r'<link\s+rel="stylesheet"[^>]*/?>',  head_content)
js_scripts = re.findall(r'<script\s+src="[^"]*"[^>]*>\s*</script>', head_content)
inline_scripts = re.findall(r'<script>.*?</script>', head_content, re.DOTALL)
style_blocks = re.findall(r'<style>.*?</style>', head_content, re.DOTALL)
meta_tags = re.findall(r'<meta[^>]*/?>',  head_content)

# Rebuild clean HTML
new_html = '<!DOCTYPE html>\n<html>\n<head>\n'
new_html += '    <meta charset="utf-8">\n'
new_html += '    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">\n'

for tag in meta_tags:
    if 'viewport' not in tag and 'charset' not in tag.lower():
        new_html += '    ' + tag + '\n'

# CSS first
for css in css_links:
    new_html += '    ' + css + '\n'

for style in style_blocks:
    new_html += '    ' + style + '\n'

# Mobile/iOS CSS
new_html += '''    <style>
    html, body {
        height: 100% !important;
        width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
        -webkit-overflow-scrolling: touch;
    }
    .folium-map {
        position: absolute !important;
        top: 0 !important;
        left: 0 !important;
        height: 100% !important;
        width: 100% !important;
    }
    .leaflet-container {
        height: 100% !important;
        width: 100% !important;
        -webkit-tap-highlight-color: transparent;
        -webkit-touch-callout: none;
    }
    @media screen and (max-width: 480px) {
        div[style*="position:fixed"][style*="bottom"] {
            width: 180px !important;
            font-size: 11px !important;
            bottom: 10px !important;
            left: 5px !important;
            max-height: 55vh !important;
        }
    }
    </style>
'''

# Inline head scripts (L_NO_TOUCH, etc)
for iscript in inline_scripts:
    new_html += '    ' + iscript + '\n'

# External JS scripts
for js in js_scripts:
    new_html += '    ' + js + '\n'

new_html += '</head>\n<body>\n'
new_html += body_content

# Map init — DOMContentLoaded + Leaflet polling
new_html += '\n<script>\n'
new_html += 'document.addEventListener("DOMContentLoaded", function() {\n'
new_html += '    (function waitForLeaflet() {\n'
new_html += '        if (typeof L === "undefined") {\n'
new_html += '            setTimeout(waitForLeaflet, 150);\n'
new_html += '            return;\n'
new_html += '        }\n'
new_html += map_script
new_html += '\n    })();\n'
new_html += '});\n'
new_html += '</script>\n'
new_html += '</body>\n</html>'

with open(output_path, 'w', encoding='utf-8') as f:
    f.write(new_html)

print(f"\n{'='*60}")
print(f"MAPA GUARDADO EXITOSAMENTE")
print(f"{'='*60}")
print(f"Ubicacion: {output_path}")
print(f"AGEBs en el mapa: {len(merged_filtered)}")
print(f"Puntos de interes: {len(puntos_adicionales)}")
print(f"Poblacion urbana: {urban_population:,.0f} habitantes")
print(f"Poblacion total: {TOTAL_POPULATION:,} habitantes")
print(f"{'='*60}")
print()
print("PARA GITHUB PAGES:")
print("  1. Crea repositorio 'mapa-san-pedro' en GitHub")
print("  2. Sube D:\\SEC\\index.html al repositorio")
print("  3. Settings > Pages > Branch: main > Save")
print("  4. Listo: https://TU-USUARIO.github.io/mapa-san-pedro/")