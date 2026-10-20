<div align="center">

# ⚡ HookPulse

**Интерактивный терминальный (TUI) отладчик вебхуков и API-запросов для Python-разработчиков**

Перехватывайте входящие вебхуки (Stripe, GitHub, Telegram, Svix и любые HTTP-запросы), просматривайте JSON с подсветкой синтаксиса, **повторяйте запросы на свой `localhost` одной клавишей (`r`)** и **автоматически генерируйте готовые `Pydantic v2` модели (`p`)** прямо в терминале.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Built with Textual](https://img.shields.io/badge/TUI-Textual-purple.svg)](https://github.com/Textualize/textual)
[![Code Style: PEP 8](https://img.shields.io/badge/code%20style-PEP%208-orange.svg)](https://peps.python.org/pep-0008/)

[**English**](README.md) | [**Русский**](README.ru.md)

<br>

![HookPulse Interactive TUI Demo](assets/demo.gif)

</div>

## Зачем нужен HookPulse?

Отладка вебхуков от внешних сервисов (платежки, боты, GitHub Actions) обычно превращается в боль: сырой JSON в логах консоли нечитаем, при падении локального обработчика приходится заново инициировать событие на стороне провайдера, а писать вручную `Pydantic`-модели для вложенных структур на 50 полей — скучная рутина.

* **Мгновенный Replay одной клавишей (`r`):** Повторяйте любой перехваченный запрос (со всеми заголовками, криптографическими подписями `Stripe-Signature`, query-параметрами и телом) на свой локальный сервер (FastAPI / Django / Flask / Litestar) с отображением HTTP-статуса и времени ответа в миллисекундах.
* **Автогенерация `Pydantic v2` схем (`p`):** Рекурсивно анализирует JSON-тело запроса и строит готовые иерархические классы `BaseModel` (с поддержкой `Optional`, типизированных списков и `Field(alias=...)` для зарезервированных слов Python).
* **Умное определение источника:** Автоматически распознает вебхуки от **Stripe**, **GitHub** (включая тип события, например `GitHub:push`), **Telegram** и **Svix**.
* **Экспорт в `cURL` одной клавишей (`c`):** Копирует экранированную команду `curl`, готовую к запуску в консоли или отправке коллеге.
* **Встроенный демо-режим (`--demo` или `d`):** Позволяет сразу протестировать интерфейс и генератор схем на реальных примерах вебхуков Stripe, GitHub и Telegram без настройки внешних сервисов.

## Быстрый старт

### 1. Локальный запуск из репозитория

Склонируйте репозиторий и установите зависимости:

```bash
git clone https://github.com/YOUR_USERNAME/hookpulse.git
cd hookpulse
pip install textual aiohttp httpx rich pyperclip
```

Запустите **HookPulse** в демо-режиме (с готовыми вебхуками Stripe, GitHub и Telegram):

```bash
python hookpulse.py --demo
```

Или запустите как установленный Python-модуль:

```bash
pip install -e .
python -m hookpulse.cli --demo
```

### 2. Запуск одной строкой через `uvx` напрямую с GitHub (или PyPI)

Сразу после загрузки кода на GitHub любой пользователь сможет запустить утилиту без ручного клонирования:

```bash
uvx --from git+https://github.com/YOUR_USERNAME/hookpulse hookpulse --demo
```

А после публикации пакета в PyPI (`twine upload dist/*`):

```bash
uvx hookpulse --port 9000 --target http://localhost:8000
```

## Как проверить перехват реальных вебхуков и Replay

1. Запустите **HookPulse** на порту `9000` с пересылкой на ваш локальный бэкенд `localhost:8000`:
   ```bash
   python hookpulse.py --port 9000 --target http://localhost:8000
   ```
2. Во втором окне терминала отправьте тестовый POST-запрос:
   ```bash
   curl -X POST http://localhost:9000/webhooks/stripe \
     -H "Content-Type: application/json" \
     -H "Stripe-Signature: t=1729412400,v1=demo" \
     -d '{"event": "payment_intent.succeeded", "amount": 4900, "currency": "usd"}'
   ```
3. В окне **HookPulse** выделите пришедший запрос и нажмите:
   - **`p`** — скопировать готовую `Pydantic v2` модель в буфер обмена.
   - **`r`** — повторить (Replay) запрос на `http://localhost:8000/webhooks/stripe`.
   - **`c`** — скопировать готовую команду `cURL`.

## Горячие клавиши

| Клавиша | Действие | Описание |
| :--- | :--- | :--- |
| `r` | **Replay Request** | Повторно отправляет выбранный запрос на `--target` (`http://localhost:8000`) и замеряет статус и время ответа |
| `p` | **Copy Pydantic v2** | Генерирует вложенные `Pydantic v2` модели из JSON-тела и копирует код в буфер обмена |
| `c` | **Copy cURL** | Копирует готовую команду `curl -X ...` со всеми заголовками и телом |
| `d` | **Demo Webhooks** | Добавляет в таблицу тестовые вебхуки от Stripe, GitHub и Telegram |
| `s` | **Save JSON** | Сохраняет историю всех перехваченных запросов в файл `hookpulse_history.json` |
| `x` | **Clear All** | Очищает список запросов |
| `q` | **Quit** | Выход из программы |

## Параметры командной строки (CLI)

| Флаг | По умолчанию | Описание |
| :--- | :--- | :--- |
| `-p`, `--port` | `9000` | Локальный порт, на котором HookPulse слушает входящие вебхуки |
| `--host` | `0.0.0.0` | Хост для привязки HTTP-сервера |
| `-t`, `--target` | `http://localhost:8000` | Базовый URL вашего локального приложения для повтора (Replay) запросов |
| `--demo` | `False` | Загружает демонстрационные вебхуки сразу при старте |
| `--schema-from-file` | `None` | Консольный режим без TUI: читает `.json` файл, выводит `Pydantic v2` схему в `stdout` и завершает работу |

## Работа в связке с туннелями (Cloudflare / ngrok / Pinggy)

Чтобы принимать реальные вебхуки из интернета, запустите HookPulse на порту `9000`, а ваше FastAPI/Django приложение — на `8000`:

```bash
python hookpulse.py --port 9000 --target http://localhost:8000
```

Во втором окне терминала пробросьте порт `9000` наружу:

```bash
cloudflared tunnel --url http://localhost:9000
```

Теперь любой внешний вебхук сохраняется в **HookPulse** — вы можете править код своего бэкенда на `localhost:8000` и нажимать `r` сколько угодно раз, пока обработчик не заработает идеально.

## Запуск тестов

```bash
python -m unittest discover -s tests -v
```

## Лицензия

Проект распространяется под лицензией [MIT](LICENSE).
