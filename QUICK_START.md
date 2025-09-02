# 🚀 Быстрый запуск

## Вариант 1: Docker Compose (рекомендуется)

1. **Создайте файл .env:**
   ```bash
   cp env.example .env
   # Отредактируйте .env и добавьте ваш OpenAI API ключ
   ```

2. **Запустите приложение:**
   ```bash
   docker-compose up --build
   ```

3. **Откройте браузер:**
   - Фронтенд: http://localhost
   - Бэкенд: http://localhost:8000
   - API docs: http://localhost:8000/docs

## Вариант 2: Режим разработки

1. **Установите зависимости:**
   ```bash
   pip install -r backend/requirements.txt
   ```

2. **Создайте .env файл** (см. выше)

3. **Запустите скрипт:**
   ```bash
   python run_dev.py
   ```

## 🧪 Тестирование

```bash
python test_app.py
```

## ⚠️ Важно

- Убедитесь, что у вас есть действующий OpenAI API ключ
- Порт 80 должен быть свободен (для фронтенда)
- Порт 8000 должен быть свободен (для бэкенда)

## 🛑 Остановка

- **Docker**: `Ctrl+C` или `docker-compose down`
- **Dev mode**: `Ctrl+C`
