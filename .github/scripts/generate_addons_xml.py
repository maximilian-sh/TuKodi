"""
Generates addons.xml and addons.xml.md5 from all addon.xml files in the repo.
Output goes into the dist/ directory alongside the built ZIPs.
"""
import hashlib
import os
import xml.etree.ElementTree as ET

ADDONS = [
    'plugin.video.tukodi',
    'repository.tukodi',
]

root = ET.Element('addons')

for addon_id in ADDONS:
    tree = ET.parse(f'{addon_id}/addon.xml')
    root.append(tree.getroot())

ET.indent(root, space='    ')

os.makedirs('dist', exist_ok=True)
addons_xml_path = 'dist/addons.xml'

with open(addons_xml_path, 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write(ET.tostring(root, encoding='unicode'))
    f.write('\n')

with open(addons_xml_path, 'rb') as f:
    md5 = hashlib.md5(f.read()).hexdigest()

with open('dist/addons.xml.md5', 'w') as f:
    f.write(md5)

print(f'Generated addons.xml (md5: {md5})')
