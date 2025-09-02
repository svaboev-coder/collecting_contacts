#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы приложения "Контакты отелей"
"""

import requests
import json
import time

def test_health_endpoint():
    """Тест endpoint'а проверки состояния"""
    try:
        response = requests.get("http://localhost:8000/health")
        print(f"✅ Health check: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Статус: {data.get('status')}")
            print(f"   Сервис: {data.get('service')}")
        return True
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def test_collect_contacts(location="Сочи"):
    """Тест сбора контактов"""
    try:
        print(f"\n🔍 Тестируем сбор контактов для: {location}")
        
        payload = {"location": location}
        response = requests.post(
            "http://localhost:8000/collect-contacts",
            json=payload,
            timeout=120  # Увеличиваем timeout для долгих запросов
        )
        
        print(f"✅ Статус ответа: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   Количество логов: {len(data.get('logs', []))}")
            print(f"   Количество контактов: {len(data.get('contacts', []))}")
            
            # Показываем логи
            print("\n📋 Логи выполнения:")
            for i, log in enumerate(data.get('logs', [])[:5]):  # Показываем первые 5 логов
                print(f"   {i+1}. {log}")
            
            if len(data.get('logs', [])) > 5:
                print(f"   ... и еще {len(data.get('logs', [])) - 5} логов")
            
            # Показываем контакты
            contacts = data.get('contacts', [])
            if contacts:
                print(f"\n📊 Найденные контакты:")
                for i, contact in enumerate(contacts):
                    print(f"   {i+1}. {contact.get('name', 'Не указано')}")
                    print(f"      Адрес: {contact.get('address', 'Не указано')}")
                    print(f"      Координаты: {contact.get('coordinates', 'Не указано')}")
                    print(f"      Email: {contact.get('email', 'Не указано')}")
                    print(f"      Сайт: {contact.get('website', 'Не указано')}")
                    print()
            else:
                print("   ❌ Контакты не найдены")
                
        else:
            print(f"   ❌ Ошибка: {response.text}")
            
        return True
        
    except requests.exceptions.Timeout:
        print("   ⏰ Timeout - запрос занял слишком много времени")
        return False
    except Exception as e:
        print(f"   ❌ Ошибка теста: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("🧪 Тестирование приложения 'Контакты отелей'")
    print("=" * 50)
    
    # Проверяем доступность сервиса
    if not test_health_endpoint():
        print("\n❌ Сервис недоступен. Убедитесь, что приложение запущено:")
        print("   docker-compose up --build")
        return
    
    # Тестируем сбор контактов
    test_locations = ["Сочи", "Анапа"]
    
    for location in test_locations:
        success = test_collect_contacts(location)
        if not success:
            print(f"   ⚠️ Тест для {location} не прошел")
        
        # Пауза между тестами
        if location != test_locations[-1]:
            print("\n⏳ Ждем 5 секунд перед следующим тестом...")
            time.sleep(5)
    
    print("\n🎉 Тестирование завершено!")

if __name__ == "__main__":
    main()
