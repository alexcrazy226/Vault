# Vault

Локальный password manager на `Python 3.11+` с интерфейсом на `Tkinter`, локальной базой `SQLite`, темами, аватарками, музыкой, генератором паролей.

## Что умеет приложение

- регистрация и вход в учётную запись
- локальное хранение логинов и паролей
- несколько аккаунтов для одного сайта
- современное шифрование через `cryptography`
- поиск по сохранённым записям
- генератор паролей
- темы оформления
- аватарка пользователя
- фоновая музыка
- пользовательские обои
- сборка в Windows `.exe`

## Структура проекта

- `main.py` - точка входа
- `vault_app/` - модули приложения
- `app.ico` - иконка приложения
- `music.mp3` - фоновая музыка
- `OH FUCK.png` - дефолтный фон
- `requirements.txt` - зависимости
- `Vault.spec` / `main.spec` - файлы сборки PyInstaller
- `release/Vault.exe` - готовая Windows-сборка для скачивания

## Быстрый запуск из исходников

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Сборка `.exe`

```powershell
pyinstaller --onefile --windowed --name Vault main.py
```

## Скачать готовый `.exe`

Готовая сборка лежит здесь:

- [`release/Vault.exe`](./release/Vault.exe)

## Важно

- база данных `vault.db` создаётся локально при запуске
- настройки приложения сохраняются в `app_state.json`
- Telegram-уведомления работают только если заданы переменные окружения `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_IDS`
