"""Настройка HTTPS для учебного VPS. Запускать через sudo после установки Caddy."""
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import time

if os.geteuid() != 0:
    raise SystemExit('Необходимо запустить через sudo.')
if not shutil.which('caddy'):
    raise SystemExit('Сначала установи Caddy: sudo apt install -y caddy')

root = Path('/home/admin/music-ideas')
access = root / '.demo-access'
if access.exists():
    password = access.read_text().strip()
else:
    password = secrets.token_urlsafe(18)
    descriptor = os.open(access, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(password + '\n')
    owner = pwd.getpwnam('admin')
    os.chown(access, owner.pw_uid, owner.pw_gid)

hashed = subprocess.run(['caddy', 'hash-password'], input=password + '\n',
                        text=True, capture_output=True, check=True).stdout.strip()
# HTTP-01 использует свободный порт 80. TLS-ALPN отключён, так как 443 занят Xray.
config = '''{
    https_port 8443
}

https://193-181-215-56.sslip.io:8443 {
    tls {
        issuer acme {
            dir https://acme-v02.api.letsencrypt.org/directory
            disable_tlsalpn_challenge
        }
    }
    basicauth {
        demo PASSWORD_HASH
    }
    reverse_proxy 127.0.0.1:8000
}
'''.replace('PASSWORD_HASH', hashed)
candidate = Path('/etc/caddy/music-ideas.caddyfile')
candidate.write_text(config)
subprocess.run(['caddy', 'validate', '--config', str(candidate), '--adapter', 'caddyfile'], check=True)
current = Path('/etc/caddy/Caddyfile')
if current.exists():
    shutil.copy2(current, current.with_name('Caddyfile.before-music-' + str(int(time.time()))))
shutil.copy2(candidate, current)
current.chmod(0o644)

# Меняем только два правила и только если UFW уже включён.
if shutil.which('ufw'):
    status = subprocess.run(['ufw', 'status'], capture_output=True, text=True,
                            env={**os.environ, 'LC_ALL': 'C'}, check=True).stdout
    if 'Status: active' in status:
        subprocess.run(['ufw', 'allow', '80/tcp'], check=True)
        subprocess.run(['ufw', 'allow', '8443/tcp'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'caddy'], check=True)
subprocess.run(['systemctl', 'reload', 'caddy'], check=True)
print('HTTPS настроен: https://193-181-215-56.sslip.io:8443')
print('Логин: demo. Пароль сохранён в /home/admin/music-ideas/.demo-access')
print('Выпуск сертификата может занять немного времени. Порт 443 не менялся.')
