"""Descarga datasets públicos de Roboflow (YOLOv8) y los une en uno solo con la clase 0 = bache.

Uso: python prepare_data.py workspace/proyecto/version [...]
La API key se lee de roboflow.env (ROBOFLOW_API_KEY) y nunca se imprime.
"""
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
# En Windows conviene una ruta corta (límite de 260 caracteres): BACHESCAN_TRAIN_DIR=C:/bachescan-train
DATA = Path(os.environ.get('BACHESCAN_TRAIN_DIR', ROOT / 'data'))
RAW = DATA / 'raw'
MERGED = DATA / 'merged'
POTHOLE_WORDS = ('pothole', 'potholes', 'bache', 'hueco', 'hole', 'd40')


def api_key():
    text = (ROOT / 'roboflow.env').read_text(encoding='utf-8')
    match = re.search(r'^ROBOFLOW_API_KEY=(.*)$', text, re.M)
    key = match.group(1).strip() if match else ''
    if len(key) < 10:
        raise SystemExit('Falta ROBOFLOW_API_KEY en roboflow.env')
    return key


def download(spec):
    """Exporta la versión en formato YOLOv8 con la API REST de Roboflow y la descomprime."""
    import time
    import urllib.request
    import zipfile
    from rf_api import get
    workspace, project, version = spec.split('/')
    target = RAW / f'{workspace}__{project}__v{version}'
    if (target / 'data.yaml').exists():
        return target
    archive = RAW / f'{target.name}.zip'
    if archive.exists():  # Zip ya descargado: solo descomprimir.
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
        archive.unlink()
        return target
    for attempt in range(40):  # Roboflow prepara la exportación la primera vez; puede tardar.
        status, body = get(f'{workspace}/{project}/{version}/yolov8')
        link = body.get('export', {}).get('link') if isinstance(body, dict) else None
        if status == 200 and link:
            break
        print(spec, 'preparando exportación…', status, str(body)[:120])
        time.sleep(15)
    else:
        raise SystemExit(f'No se pudo exportar {spec}')
    archive = RAW / f'{target.name}.zip'
    RAW.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with urllib.request.urlopen(link, timeout=120) as response, open(archive, 'wb') as out:
        total = int(response.headers.get('Content-Length', 0))
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if done % (50 << 20) < (1 << 20):
                print(f'{spec}: {done >> 20} de {total >> 20} MB ({(done >> 20) / max(1, time.time() - started):.1f} MB/s)', flush=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    archive.unlink()
    print(spec, 'descargado en', round(time.time() - started), 's')
    return target


def pothole_classes(names):
    """Índices de clase que representan baches; un dataset de una sola clase cuenta completo."""
    names = list(names.values()) if isinstance(names, dict) else list(names)
    if len(names) == 1:
        return {0}
    return {index for index, name in enumerate(names) if any(word in str(name).lower() for word in POTHOLE_WORDS)}


def merge(folders):
    if MERGED.exists():
        shutil.rmtree(MERGED)
    totals = {}
    for folder in folders:
        info = yaml.safe_load((folder / 'data.yaml').read_text(encoding='utf-8'))
        keep = pothole_classes(info['names'])
        print(folder.name, 'clases', info['names'], '-> bache:', sorted(keep))
        for split in ('train', 'valid', 'test'):
            images = folder / split / 'images'
            if not images.exists():
                continue
            out_images = MERGED / split / 'images'
            out_labels = MERGED / split / 'labels'
            out_images.mkdir(parents=True, exist_ok=True)
            out_labels.mkdir(parents=True, exist_ok=True)
            for image in images.iterdir():
                label = folder / split / 'labels' / (image.stem + '.txt')
                lines = []
                if label.exists():
                    for line in label.read_text(encoding='utf-8').splitlines():
                        parts = line.split()
                        if len(parts) >= 5 and int(float(parts[0])) in keep:
                            coords = [float(value) for value in parts[1:]]
                            if len(coords) > 4:  # Polígono de segmentación -> caja envolvente.
                                xs, ys = coords[0::2], coords[1::2]
                                x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
                                coords = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]
                            lines.append('0 ' + ' '.join(f'{value:.6f}' for value in coords[:4]))
                name = f'{folder.name}__{image.name}'
                shutil.copy2(image, out_images / name)
                (out_labels / (Path(name).stem + '.txt')).write_text('\n'.join(lines), encoding='utf-8')
                totals[split] = totals.get(split, 0) + 1
    (MERGED / 'data.yaml').write_text(yaml.safe_dump({
        'path': str(MERGED), 'train': 'train/images', 'val': 'valid/images',
        'test': 'test/images' if (MERGED / 'test').exists() else 'valid/images', 'names': {0: 'pothole'},
    }), encoding='utf-8')
    print('Unido:', totals)


if __name__ == '__main__':
    merge([download(spec) for spec in sys.argv[1:]])
