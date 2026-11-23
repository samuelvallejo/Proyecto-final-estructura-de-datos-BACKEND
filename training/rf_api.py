"""GET a la API de Roboflow con la key de roboflow.env; nunca imprime la key.

Uso: python rf_api.py <ruta o URL> [parametros extra como k=v ...]
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def key():
    text = (Path(__file__).with_name('roboflow.env')).read_text(encoding='utf-8')
    match = re.search(r'^ROBOFLOW_API_KEY=(.*)$', text, re.M)
    return match.group(1).strip() if match else ''


def get(path, **params):
    base = path if path.startswith('http') else 'https://api.roboflow.com/' + path.lstrip('/')
    query = urllib.parse.urlencode({**params, 'api_key': key()})
    url = base + ('&' if '?' in base else '?') + query
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bachescan-training'}), timeout=60) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace')[:300].replace(key(), '***')
    except Exception as error:  # Nunca propagar la URL: contiene la key.
        return 0, f'{type(error).__name__}: ' + str(error).replace(key(), '***')[:200]


if __name__ == '__main__':
    extra = dict(arg.split('=', 1) for arg in sys.argv[2:])
    status, body = get(sys.argv[1], **extra)
    text = json.dumps(body, ensure_ascii=False)[:3000] if not isinstance(body, str) else body
    print(status, text.replace(key(), '***'))
