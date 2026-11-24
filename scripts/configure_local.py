"""Configures the project's isolated PostgreSQL without printing credentials."""
from pathlib import Path
import psycopg
from dotenv import dotenv_values


class LocalSetup:
    """Creates the local database and a .env file from .env.example, copying only known optional keys."""
    SERVER = 'host=127.0.0.1 port=55432 user=bachescan_test dbname=postgres'
    COPIED_KEYS = ('GEMINI_API_KEY', 'NOMINATIM_USER_AGENT')

    def create_database(self):
        with psycopg.connect(self.SERVER, autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname='bachescan'").fetchone():
                conn.execute('CREATE DATABASE bachescan')

    def write_env(self, env: Path) -> bool:
        if env.exists():
            return False
        existing = dotenv_values('../backend/.env')
        template = Path('.env.example').read_text(encoding='utf-8')
        template = template.replace('postgresql://bachescan:bachescan@localhost:5432/bachescan',
                                    'postgresql://bachescan_test@127.0.0.1:55432/bachescan')
        for key in self.COPIED_KEYS:
            value = existing.get(key)
            if value:
                template = template.replace(key + '=\n', key + '=' + value + '\n')
        env.write_text(template, encoding='utf-8')
        return True


if __name__ == '__main__':
    setup = LocalSetup()
    setup.create_database()
    if setup.write_env(Path('.env')):
        print('Configuración local creada. Las credenciales permanecen en .env.')
    else:
        print('La configuración .env existente se conserva.')
