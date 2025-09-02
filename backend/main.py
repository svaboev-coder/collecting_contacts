from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import openai
import requests
from bs4 import BeautifulSoup
import json
import os
import asyncio
from typing import List, Dict, Any
import logging
from utils import contact_extractor, scraper

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Контакты отелей", version="1.0.0")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Настройка OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

class LocationRequest(BaseModel):
    location: str

class ContactInfo(BaseModel):
    name: str
    address: str
    coordinates: str
    email: str
    website: str

class CollectionStep(BaseModel):
    step: int
    description: str
    prompt: str

class CollectionPlan(BaseModel):
    steps: List[CollectionStep]

class CollectionResult(BaseModel):
    logs: List[str]
    contacts: List[ContactInfo]

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/collect-contacts", response_model=CollectionResult)
async def collect_contacts(request: LocationRequest):
    try:
        logs = []
        contacts = []
        
        # Шаг 1: Получение плана сбора контактов
        logs.append(f"🔍 Начинаем сбор контактов для: {request.location}")
        
        plan_prompt = f"""
        Составь пошаговый план (5-6 шагов) для сбора контактов мест размещения 
        (отелей, баз отдыха, пансионатов, санаториев) в заданном населенном пункте "{request.location}".
        
        Верни результат в JSON формате:
        {{
            "steps": [
                {{
                    "step": 1,
                    "description": "Описание шага",
                    "prompt": "Промпт для ChatGPT"
                }}
            ]
        }}
        
        Каждый шаг должен быть направлен на поиск и сбор конкретной информации:
        - Поиск источников информации
        - Извлечение названий организаций
        - Сбор адресов и координат
        - Поиск email адресов
        - Поиск официальных сайтов
        """
        
        logs.append("📋 Формируем план сбора контактов...")
        
        try:
            plan_response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": plan_prompt}],
                max_tokens=1000
            )
            
            plan_content = plan_response.choices[0].message.content
            logs.append("✅ План сбора получен")
            
            # Парсинг JSON плана
            try:
                plan_data = json.loads(plan_content)
                plan = CollectionPlan(**plan_data)
            except json.JSONDecodeError:
                # Если JSON не парсится, создаем базовый план
                logs.append("⚠️ Ошибка парсинга плана, используем базовый план")
                plan = create_basic_plan(request.location)
                
        except Exception as e:
            logs.append(f"⚠️ Ошибка получения плана: {str(e)}")
            plan = create_basic_plan(request.location)
        
        # Выполнение шагов плана
        intermediate_results = []
        
        for step in plan.steps:
            logs.append(f"🚀 Выполняем шаг {step.step}: {step.description}")
            
            try:
                # Выполнение шага
                step_result = await execute_collection_step(step, request.location, intermediate_results)
                intermediate_results.append(step_result)
                logs.append(f"✅ Шаг {step.step} выполнен")
                
            except Exception as e:
                logs.append(f"❌ Ошибка в шаге {step.step}: {str(e)}")
                continue
        
        # Финальный анализ и формирование таблицы
        logs.append("🔍 Выполняем финальный анализ...")
        
        try:
            final_prompt = f"""
            На основе собранной информации о местах размещения в {request.location}, 
            сформируй итоговую таблицу контактов в следующем формате:
            
            {json.dumps([result for result in intermediate_results if result], ensure_ascii=False, indent=2)}
            
            Верни результат в JSON формате:
            {{
                "contacts": [
                    {{
                        "name": "Название организации",
                        "address": "Почтовый адрес",
                        "coordinates": "Геокоординаты (широта, долгота)",
                        "email": "Email адрес",
                        "website": "Ссылка на официальный сайт"
                    }}
                ]
            }}
            
            Если какая-то информация отсутствует, укажи "Не найдено".
            """
            
            final_response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": final_prompt}],
                max_tokens=2000
            )
            
            final_content = final_response.choices[0].message.content
            
            try:
                final_data = json.loads(final_content)
                if "contacts" in final_data:
                    contacts = [ContactInfo(**contact) for contact in final_data["contacts"]]
                    logs.append(f"✅ Собрано {len(contacts)} контактов")
                else:
                    logs.append("⚠️ Не удалось получить контакты из финального анализа")
            except json.JSONDecodeError:
                logs.append("⚠️ Ошибка парсинга финального результата")
                
        except Exception as e:
            logs.append(f"❌ Ошибка финального анализа: {str(e)}")
        
        logs.append("🎉 Сбор контактов завершен!")
        
        return CollectionResult(logs=logs, contacts=contacts)
        
    except Exception as e:
        logger.error(f"Ошибка сбора контактов: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка сбора контактов: {str(e)}")

async def execute_collection_step(step: CollectionStep, location: str, previous_results: List[str]) -> str:
    """Выполнение одного шага сбора контактов"""
    
    # Формируем промпт с учетом предыдущих результатов
    enhanced_prompt = f"""
    {step.prompt}
    
    Населенный пункт: {location}
    
    Предыдущие результаты:
    {json.dumps(previous_results, ensure_ascii=False, indent=2)}
    
    Выполни этот шаг и верни результат в текстовом виде.
    """
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": enhanced_prompt}],
            max_tokens=1000
        )
        
        result = response.choices[0].message.content
        
        # Дополнительная обработка результата для извлечения контактов
        extracted_contacts = contact_extractor.extract_contacts_from_text(result)
        
        # Если найдены контакты, добавляем их к результату
        if any(extracted_contacts.values()):
            enhanced_result = f"""
{result}

--- ИЗВЛЕЧЕННЫЕ КОНТАКТЫ ---
Email адреса: {', '.join(extracted_contacts.get('emails', []))}
Телефоны: {', '.join(extracted_contacts.get('phones', []))}
Координаты: {', '.join(extracted_contacts.get('coordinates', []))}
Адреса: {', '.join(extracted_contacts.get('addresses', []))}
"""
            return enhanced_result
        
        return result
        
    except Exception as e:
        return f"Oшибка выполнения шага: {str(e)}"

def create_basic_plan(location: str) -> CollectionPlan:
    """Создание базового плана сбора контактов"""
    
    basic_steps = [
        CollectionStep(
            step=1,
            description="Поиск основных источников информации о местах размещения",
            prompt=f"Найди основные источники информации о местах размещения в {location} (сайты туристических порталов, справочники, отзывы)"
        ),
        CollectionStep(
            step=2,
            description="Сбор названий организаций",
            prompt=f"Из найденных источников извлеки названия отелей, баз отдыха, пансионатов и санаториев в {location}"
        ),
        CollectionStep(
            step=3,
            description="Поиск адресов и координат",
            prompt=f"Для найденных организаций найди их почтовые адреса и географические координаты"
        ),
        CollectionStep(
            step=4,
            description="Поиск email адресов",
            prompt=f"Найди email адреса для найденных организаций"
        ),
        CollectionStep(
            step=5,
            description="Поиск официальных сайтов",
            prompt=f"Найди ссылки на официальные сайты найденных организаций"
        )
    ]
    
    return CollectionPlan(steps=basic_steps)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "hotel-contacts-collector"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
