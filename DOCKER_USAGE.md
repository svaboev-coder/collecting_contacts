# Docker Usage Guide

## 🛡️ Стабильная версия (для клиента)

### Запуск стабильной версии:
```bash
docker-compose up -d
```

**Особенности:**
- ✅ Использует зафиксированные образы `v1.0-stable`
- ✅ Полностью изолирована от изменений в коде
- ✅ Готова к передаче клиенту
- ✅ Не требует сборки образов

## 🚀 Версия для разработки

### Запуск версии для разработки:
```bash
docker-compose -f docker-compose.dev.yml up -d
```

**Особенности:**
- 🔧 Собирает образы из исходного кода
- 🔧 Volumes подключены для live-редактирования
- 🔧 Изменения в коде применяются автоматически
- 🔧 Для разработки и тестирования

## 📦 Управление образами

### Создание новой стабильной версии:
```bash
# 1. Остановить dev версию
docker-compose -f docker-compose.dev.yml down

# 2. Собрать новые образы
docker-compose -f docker-compose.dev.yml build

# 3. Создать теги для новой версии
docker tag collecting_contacts_clone-backend collecting_contacts_clone-backend:v1.1-stable
docker tag collecting_contacts_clone-frontend collecting_contacts_clone-frontend:v1.1-stable

# 4. Сохранить в файлы
docker save collecting_contacts_clone-backend:v1.1-stable -o backend-v1.1-stable.tar
docker save collecting_contacts_clone-frontend:v1.1-stable -o frontend-v1.1-stable.tar

# 5. Обновить docker-compose.yml с новыми тегами
```

## 🎯 Рекомендации

- **Для клиента**: Используйте `docker-compose up -d`
- **Для разработки**: Используйте `docker-compose -f docker-compose.dev.yml up -d`
- **Для продакшена**: Используйте стабильные образы
