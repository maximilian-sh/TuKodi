"""
Generates addons.xml, addons.xml.md5, and browsable index.html files
so Kodi's file manager can navigate the repository like a directory.
"""
import hashlib
import os
import shutil
import xml.etree.ElementTree as ET

ADDONS = [
    'plugin.video.tukodi',
    'repository.tukodi',
]

RAW_BASE = 'https://raw.githubusercontent.com/maximilian-sh/TuKodi/gh-pages'

# Source URL for the Kodi file manager (used in README)
SOURCE_URL = f'{RAW_BASE}/'

os.makedirs('dist', exist_ok=True)

# --- addons.xml ---
root = ET.Element('addons')
for addon_id in ADDONS:
    tree = ET.parse(f'{addon_id}/addon.xml')
    root.append(tree.getroot())

ET.indent(root, space='    ')

with open('dist/addons.xml', 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write(ET.tostring(root, encoding='unicode'))
    f.write('\n')

with open('dist/addons.xml', 'rb') as f:
    md5 = hashlib.md5(f.read()).hexdigest()

with open('dist/addons.xml.md5', 'w') as f:
    f.write(md5)

print(f'Generated addons.xml (md5: {md5})')

# --- index.html files so Kodi can browse the source ---
def write_index(path, entries):
    """Write a simple HTML directory listing Kodi can parse."""
    links = '\n'.join(f'<a href="{e}">{e}</a><br>' for e in entries)
    with open(os.path.join(path, 'index.html'), 'w') as f:
        f.write(f'<html><body>{links}</body></html>\n')

# Root index: list addon subdirectories
write_index('dist', [f'{a}/' for a in ADDONS])

# Per-addon index: use relative ZIP name so Kodi resolves it relative to raw.githubusercontent.com base
for addon_id in ADDONS:
    version = ET.parse(f'{addon_id}/addon.xml').getroot().get('version')
    zip_name = f'{addon_id}-{version}.zip'
    addon_dist = f'dist/{addon_id}'
    os.makedirs(addon_dist, exist_ok=True)
    write_index(addon_dist, [zip_name])
    # Copy icon so Kodi can load it from raw.githubusercontent.com
    icon_src = f'{addon_id}/icon.png'
    if os.path.exists(icon_src):
        shutil.copy(icon_src, f'{addon_dist}/icon.png')
    print(f'  {addon_id}/index.html → {zip_name}')
