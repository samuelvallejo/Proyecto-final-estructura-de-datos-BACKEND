"""Create, once, the private parameters of a NEW Azure installation.

Do not use it to replace the key of a database that already holds encrypted data.
It never prints passwords or keys; the file stays outside the repository/OneDrive.
"""
import argparse
import json
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backend-ref', required=True, help='SHA revisado publicado de este backend')
parser.add_argument('--output', type=Path, default=Path.home() / '.bachescan-azure' / 'parameters.private.json')
args = parser.parse_args()
if len(args.backend_ref) != 40 or any(c not in '0123456789abcdef' for c in args.backend_ref):
    parser.error('backend-ref debe ser un SHA completo de Git.')
target = args.output.expanduser().resolve()
if target.exists():
    parser.error('El archivo ya existe. Se conserva su clave; usa los parámetros existentes para actualizar.')
target.parent.mkdir(parents=True, exist_ok=True)
parameters = {'$schema': 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#',
    'contentVersion': '1.0.0.0', 'parameters': {
        'backendRef': {'value': args.backend_ref},
        'databasePassword': {'value': 'Aa1!' + secrets.token_urlsafe(36)},
        'dataEncryptionKey': {'value': Fernet.generate_key().decode('ascii')},
    }}
with target.open('x', encoding='utf-8') as output:
    json.dump(parameters, output, indent=2)
    output.write('\n')
print('Parámetros privados guardados en:', target)
print('No compartas el archivo ni lo subas a GitHub. Contiene la clave de los datos de esta instalación.')
