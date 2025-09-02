#!/usr/bin/env python3
"""
Скрипт для быстрого запуска приложения в режиме разработки
"""

import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path

def check_dependencies():
    """Проверка зависимостей"""
    try:
        import fastapi
        import uvicorn
        import openai
        import requests
        import bs4
        print("✅ Все зависимости установлены")
        return True
    except ImportError as e:
        print(f"❌ Отсутствует зависимость: {e}")
        print("Установите зависимости: pip install -r backend/requirements.txt")
        return False

def check_env_file():
    """Проверка файла .env"""
    env_file = Path(".env")
    if not env_file.exists():
        print("⚠️ Файл .env не найден")
        print("Создайте файл .env с вашим OpenAI API ключом:")
        print("OPENAI_API_KEY=your_api_key_here")
        return False
    
    with open(env_file, 'r') as f:
        content = f.read()
        if 'your_openai_api_key_here' in content:
            print("⚠️ Замените placeholder в .env на реальный API ключ")
            return False
    
    print("✅ Файл .env настроен")
    return True

def start_backend():
    """Запуск бэкенда"""
    print("🚀 Запускаем бэкенд...")
    
    backend_dir = Path("backend")
    if not backend_dir.exists():
        print("❌ Директория backend не найдена")
        return False
    
    # Запуск бэкенда
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
            cwd=backend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Ждем запуска
        time.sleep(3)
        
        # Проверяем, что процесс запущен
        if process.poll() is None:
            print("✅ Бэкенд запущен на http://localhost:8000")
            return process
        else:
            stdout, stderr = process.communicate()
            print(f"❌ Ошибка запуска бэкенда: {stderr.decode()}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка запуска бэкенда: {e}")
        return False

def start_frontend():
    """Запуск фронтенда"""
    print("🌐 Запускаем фронтенд...")
    
    frontend_dir = Path("frontend")
    if not frontend_dir.exists():
        print("❌ Директория frontend не найдена")
        return False
    
    # Запуск простого HTTP сервера
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "http.server", "80"],
            cwd=frontend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Ждем запуска
        time.sleep(2)
        
        # Проверяем, что процесс запущен
        if process.poll() is None:
            print("✅ Фронтенд запущен на http://localhost")
            return process
        else:
            stdout, stderr = process.communicate()
            print(f"❌ Ошибка запуска фронтенда: {stderr.decode()}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка запуска фронтенда: {e}")
        return False

def open_browser():
    """Открытие браузера"""
    print("🌐 Открываем браузер...")
    try:
        webbrowser.open("http://localhost")
        print("✅ Браузер открыт")
    except Exception as e:
        print(f"⚠️ Не удалось открыть браузер: {e}")
        print("Откройте вручную: http://localhost")

def main():
    """Основная функция"""
    print("🏨 Запуск приложения 'Контакты отелей' в режиме разработки")
    print("=" * 60)
    
    # Проверки
    if not check_dependencies():
        return
    
    if not check_env_file():
        return
    
    # Запуск сервисов
    backend_process = start_backend()
    if not backend_process:
        return
    
    frontend_process = start_frontend()
    if not frontend_process:
        backend_process.terminate()
        return
    
    try:
        # Открываем браузер
        open_browser()
        
        print("\n🎉 Приложение запущено!")
        print("📱 Фронтенд: http://localhost")
        print("🔧 Бэкенд: http://localhost:8000")
        print("📚 API документация: http://localhost:8000/docs")
        print("\n⏹️ Для остановки нажмите Ctrl+C")
        
        # Ждем завершения
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Останавливаем приложение...")
        
        if backend_process:
            backend_process.terminate()
            print("✅ Бэкенд остановлен")
        
        if frontend_process:
            frontend_process.terminate()
            print("✅ Фронтенд остановлен")
        
        print("👋 Приложение остановлено")

if __name__ == "__main__":
    main()
