"""Back up the live DB before migrations; execute in a one-off web container with its entrypoint overridden.

SQLite uses the online backup API (safe with WAL). PostgreSQL requires pg_dump;
if unavailable, deployment stops before changing the running application.
"""
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import sqlite3
import subprocess
from sqlalchemy.engine import URL

from app import create_app, db


def backup_database(engine, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dialect = engine.dialect.name
    if dialect == 'sqlite':
        destination = directory / f'before-deploy-{stamp}.sqlite3'
        os.close(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        raw = engine.raw_connection()
        try:
            with sqlite3.connect(destination) as target:
                raw.driver_connection.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database backup integrity check failed.')
        finally:
            raw.close()
    elif dialect == 'postgresql':
        if not shutil.which('pg_dump'):
            raise RuntimeError('pg_dump is required; deployment stopped. Create a verified PostgreSQL backup first.')
        destination = directory / f'before-deploy-{stamp}.dump'
        url = engine.url
        env = dict(os.environ, PGPASSWORD=url.password or '')
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as target:
            public_url = URL.create('postgresql', username=url.username, host=url.host,
                                    port=url.port, database=url.database, query=url.query).render_as_string()
            subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--dbname', public_url],
                           env=env, stdout=target, check=True)
        subprocess.run(['pg_restore', '--list', str(destination)], stdout=subprocess.DEVNULL, check=True)
    else:
        raise RuntimeError('Unsupported database; deployment stopped before migration.')
    os.chmod(destination, 0o600)
    if destination.stat().st_size == 0:
        raise RuntimeError('Database backup is empty; deployment stopped.')
    return destination


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        destination = backup_database(db.engine, Path(app.instance_path) / 'backups')
        print(f'Database backup verified: {destination.name} ({destination.stat().st_size} bytes)')
