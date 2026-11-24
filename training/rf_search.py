"""Searches Roboflow Universe for pothole-detection datasets and shows size, license and classes."""
import sys
from rf_api import get

seen = {}
for query in sys.argv[1:]:
    for page in (1, 2, 3):
        status, body = get('universe/search', q=query, page=page)
        if status != 200 or not isinstance(body, dict):
            break
        for item in body.get('results', []):
            url = item.get('url', '')
            if url in seen or item.get('type') not in ('object-detection', 'instance-segmentation'):
                continue
            seen[url] = item
if not seen:
    print('sin resultados')
rows = []
for url, item in seen.items():
    slug = url.split('universe.roboflow.com/')[-1].strip('/')
    status, info = get(slug)
    project = info.get('project', {}) if isinstance(info, dict) else {}
    versions = info.get('versions', []) if isinstance(info, dict) else []
    latest = max((int(v.get('id', '0').split('/')[-1]) for v in versions if v.get('id')), default=0)
    rows.append((project.get('images', 0), slug, project.get('license', '?'), item.get('type'), latest,
                 ', '.join(f'{k}:{v}' for k, v in list((project.get('classes') or {}).items())[:4])))
for images, slug, license_, kind, version, classes in sorted(rows, reverse=True)[:40]:
    print(f'{images:>6}  {slug:<55} v{version:<3} {license_:<12} {kind:<22} {classes}')
