#!/usr/bin/env python3
"""
Скрипт для быстрого запуска приложения в режиме разработки
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def check_python_version():
    """Проверка версии Python"""
    if sys.version_info < (3, 8):
        print("❌ Требуется Python 3.8 или выше")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")

def install_requirements():
    """Установка зависимостей"""
    print("📦 Устанавливаем зависимости...")
    
    backend_dir = Path("backend")
    if not backend_dir.exists():
        print("❌ Папка backend не найдена")
        return False
    
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"], 
                      check=True, capture_output=True)
        print("✅ Зависимости установлены")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка установки зависимостей: {e}")
        return False

def check_env_file():
    """Проверка и создание .env файла"""
    env_file = Path(".env")
    env_example = Path("env.example")
    
    if not env_file.exists() and env_example.exists():
        print("🔧 Создаем .env файл из примера...")
        with open(env_example, 'r', encoding='utf-8') as f:
            example_content = f.read()
        
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(example_content)
        
        print("⚠️  ВНИМАНИЕ: Установите OPENAI_API_KEY в файле .env")
        print("   Получите ключ на https://platform.openai.com/api-keys")
        return False
    elif not env_file.exists():
        print("❌ Файл .env не найден и env.example отсутствует")
        return False
    
    return True

def start_backend():
    """Запуск бэкенда"""
    print("🚀 Запускаем бэкенд...")
    
    backend_dir = Path("backend")
    if not backend_dir.exists():
        print("❌ Папка backend не найдена")
        return None
    
    try:
        # Запускаем бэкенд в фоне
        process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=backend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Ждем немного для запуска
        time.sleep(3)
        
        if process.poll() is None:
            print("✅ Бэкенд запущен (PID: {})".format(process.pid))
            return process
        else:
            stdout, stderr = process.communicate()
            print(f"❌ Ошибка запуска бэкенда:")
            print(f"stdout: {stdout.decode()}")
            print(f"stderr: {stderr.decode()}")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка запуска бэкенда: {e}")
        return None

def start_frontend():
    """Запуск фронтенда (простой HTTP сервер)"""
    print("🌐 Запускаем фронтенд...")
    
    frontend_dir = Path("frontend")
    if not frontend_dir.exists():
        print("❌ Папка frontend не найдена")
        return None
    
    try:
        # Запускаем простой HTTP сервер для фронтенда
        process = subprocess.Popen(
            [sys.executable, "-m", "http.server", "3000"],
            cwd=frontend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        time.sleep(2)
        
        if process.poll() is None:
            print("✅ Фронтенд запущен на http://localhost:3000")
            return process
        else:
            stdout, stderr = process.communicate()
            print(f"❌ Ошибка запуска фронтенда:")
            print(f"stdout: {stdout.decode()}")
            print(f"stderr: {stderr.decode()}")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка запуска фронтенда: {e}")
        return None

def main():
    """Основная функция"""
    print("🏨 Запуск приложения 'Контакты отелей'")
    print("=" * 50)
    
    # Проверяем версию Python
    check_python_version()
    
    # Устанавливаем зависимости
    if not install_requirements():
        print("❌ Не удалось установить зависимости")
        return
    
    # Проверяем .env файл
    if not check_env_file():
        print("❌ Проблема с .env файлом")
        return
    
    print("\n🚀 Запускаем приложение...")
    
    # Запускаем бэкенд
    backend_process = start_backend()
    if not backend_process:
        print("❌ Не удалось запустить бэкенд")
        return
    
    # Запускаем фронтенд
    frontend_process = start_frontend()
    if not frontend_process:
        print("❌ Не удалось запустить фронтенд")
        backend_process.terminate()
        return
    
    print("\n🎉 Приложение запущено!")
    print("📱 Фронтенд: http://localhost:3000")
    print("🔧 Бэкенд API: http://localhost:8000")
    print("📚 Документация API: http://localhost:8000/docs")
    print("\n💡 Для остановки нажмите Ctrl+C")
    
    try:
        # Ждем завершения процессов
        while True:
            time.sleep(1)
            if backend_process.poll() is not None:
                print("❌ Бэкенд остановлен")
                break
            if frontend_process.poll() is not None:
                print("❌ Фронтенд остановлен")
                break
                
    except KeyboardInterrupt:
        print("\n🛑 Останавливаем приложение...")
        
        if backend_process:
            backend_process.terminate()
            print("✅ Бэкенд остановлен")
        
        if frontend_process:
            frontend_process.terminate()
            print("✅ Фронтенд остановлен")
        
        print("👋 До свидания!")

if __name__ == "__main__":
    main()
