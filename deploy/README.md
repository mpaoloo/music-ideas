# Размещение на VPS

Подготовлено для Ubuntu 24.04, пользователя admin и папки /home/admin/music-ideas.
Служба слушает только 127.0.0.1:8000. Публичный адрес и HTTPS настраиваются отдельно.
Порты и конфигурация Xray не меняются.

Сначала администратор устанавливает пакет python3-venv. Затем из папки приложения:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod 600 .env
sudo install -m 644 deploy/music-ideas.service /etc/systemd/system/music-ideas.service
sudo systemctl daemon-reload
sudo systemctl enable --now music-ideas
```

Проверка и журнал:

```sh
systemctl status music-ideas --no-pager
sudo journalctl -u music-ideas -n 50 --no-pager
```

Данные хранятся в data/ и uploads/ внутри папки приложения. Не заменяй их
при обновлении кода. .env передаётся отдельно по SSH и не входит в репозиторий.
Лимиты службы: 512 МБ памяти, 60% одного CPU, 64 процесса/потока.
Это ограничивает расход ресурсов приложением, но не гарантирует отсутствие
конкуренции с VPN за сеть и диск. Перед публичным запуском проверить нагрузку
и добавить контроль доступа к платным AI-запросам.

## HTTPS для текущего VPS

После запуска приложения:

```sh
sudo apt install -y caddy
sudo python3 /home/admin/music-ideas/deploy/configure_https.py
```

Скрипт настроен на 193-181-215-56.sslip.io:8443 и HTTP-01 на порту 80.
Он сохраняет резервную копию конфигурации Caddy и не изменяет Xray.
Логин демо — demo, случайный пароль сохраняется в .demo-access (в Git не входит).
Это общий вход в одну библиотеку, а не отдельные аккаунты пользователей.
Скрипт не универсален: перед применением на другой машине измени адрес и пути.
