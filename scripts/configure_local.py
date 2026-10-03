"""Configura el PostgreSQL aislado del proyecto sin imprimir credenciales."""
from pathlib import Path
import psycopg
from dotenv import dotenv_values

if __name__ == '__main__':
    with psycopg.connect('host=127.0.0.1 port=55432 user=bachescan_test dbname=postgres', autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname='bachescan'").fetchone():
            conn.execute('CREATE DATABASE bachescan')
    env = Path('.env')
    if not env.exists():
        existing = dotenv_values('../backend/.env')
        template = Path('.env.example').read_text(encoding='utf-8')
        template = template.replace('postgresql://bachescan:bachescan@localhost:5432/bachescan',
                                    'postgresql://bachescan_test@127.0.0.1:55432/bachescan')
        for key in ('GEMINI_API_KEY', 'NOMINATIM_USER_AGENT'):
            value = existing.get(key)
            if value:
                template = template.replace(key + '=\n', key + '=' + value + '\n')
        env.write_text(template, encoding='utf-8')
        print('Configuración local creada. Las credenciales permanecen en .env.')
    else:
        print('La configuración .env existente se conserva.')
