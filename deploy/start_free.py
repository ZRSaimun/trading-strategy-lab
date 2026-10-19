"""Supervise one loopback API and one public Next server, without a shell."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, '/app/api')
from app.deployment import validate_cloud_environment


def main():
    try:
        env = validate_cloud_environment(os.environ)
    except ValueError as exc:
        print(f'Configuration rejected: {exc}', flush=True)
        return 1
    ca = None
    if env.get('DATABASE_CA_PEM'):
        fd, name = tempfile.mkstemp(prefix='tsl-database-ca-', suffix='.pem')
        ca = Path(name)
        with os.fdopen(fd, 'w') as f:
            f.write(env['DATABASE_CA_PEM'])
        env['PGSSLROOTCERT'] = str(ca)
    children = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        # Hide migration errors: SQLAlchemy driver errors can contain a DB hostname.
        migration = subprocess.Popen(['alembic', 'upgrade', 'head'], cwd='/app/api', env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        children.append(migration)
        try:
            code = migration.wait(timeout=90)
        except subprocess.TimeoutExpired:
            print('Database migration timed out; servers were not started', flush=True)
            return 1
        if code or stopping:
            print('Database migration failed or shutdown requested; check connection, certificate and schema ownership', flush=True)
            return 1
        api = subprocess.Popen(['uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000',
                                '--workers', '1', '--limit-concurrency', '8', '--no-proxy-headers'],
                               cwd='/app/api', env=env)
        children.append(api)
        ready = False
        for _ in range(120):
            if stopping or api.poll() is not None:
                break
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1) as response:
                    ready = response.status == 200
            except OSError:
                pass
            if ready:
                break
            time.sleep(.5)
        if not ready or stopping:
            print('API did not become ready', flush=True)
            return 1
        web = subprocess.Popen(['node', 'server.js'], cwd='/app/web', env=env)
        children.append(web)
        while not stopping:
            if api.poll() is not None or web.poll() is not None:
                print('A server exited; stopping its peer', flush=True)
                return 1
            time.sleep(.25)
        return 0
    finally:
        stop(None, None)
        deadline = time.monotonic() + 10
        for child in children:
            try:
                child.wait(timeout=max(.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if ca:
            ca.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(main())
