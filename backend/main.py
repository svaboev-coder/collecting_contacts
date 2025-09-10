from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
import requests
from bs4 import BeautifulSoup
import json
import os
from dotenv import load_dotenv
import hashlib

# Загружаем переменные окружения из .env файла
load_dotenv()
import asyncio
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path
import tempfile
try:
    # Запуск из папки backend (python backend/main.py)
    from utils import contact_extractor, scraper, name_finder, contacts_crawler
    from agent import ContactAgent, WebsiteFinderAgent
    from proxy_api import ProxyAPIClient
    from cache_manager import cache_manager, CacheData, Organization, ProcessStatus
except ImportError:
    # Запуск как пакет (uvicorn backend.main:app)
    from backend.utils import contact_extractor, scraper, name_finder, contacts_crawler
    from backend.agent import ContactAgent, WebsiteFinderAgent
    from backend.proxy_api import ProxyAPIClient
    from backend.cache_manager import cache_manager, CacheData, Organization, ProcessStatus

# Настройка логирования (принудительно + абсолютный путь)
LOG_PATH = '/app/backend_debug.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding='utf-8')
    ],
    force=True,
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Контакты отелей", version="1.0.0")
logger.info(f"📝 Лог пишется в файл: {LOG_PATH}")

# Хранилище названий (файловое)
NAMES_STORE_DIR = Path(__file__).resolve().parent / 'names_store'
try:
    NAMES_STORE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 Директория для названий: {NAMES_STORE_DIR}")
except Exception as e:
    logger.error(f"Не удалось создать директорию для названий: {e}")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            client_host = request.client.host if request.client else "?"
            logger.info(f"➡️ {request.method} {request.url.path}{'?' + request.url.query if request.url.query else ''} from {client_host}")
            body_bytes = await request.body()
            if body_bytes:
                body_preview = body_bytes.decode('utf-8', errors='ignore')[:2000]
                logger.info(f"🧾 Request body: {body_preview}")

            async def receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            request._receive = receive

            response = await call_next(request)

            resp_body = b""
            async for chunk in response.body_iterator:
                resp_body += chunk
            resp_preview = resp_body.decode('utf-8', errors='ignore')[:2000]
            logger.info(f"⬅️ {response.status_code} {request.method} {request.url.path} body: {resp_preview}")

            return Response(content=resp_body,
                            status_code=response.status_code,
                            headers=dict(response.headers),
                            media_type=response.media_type)
        except Exception as e:
            logger.error(f"LoggingMiddleware error: {e}")
            return await call_next(request)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Включаем подробное логирование HTTP-запросов/ответов
app.add_middleware(LoggingMiddleware)

# Инициализация ProxyAPI клиента
try:
    proxy_client = ProxyAPIClient()
    logger.info("✅ ProxyAPI клиент успешно инициализирован")
    try:
        from proxy_api import ProxyAPIClient as _P
        # выведем используемый base_url, если есть
        logger.info(f"🌐 ProxyAPI BASE URL: {proxy_client.base_url}")
    except Exception:
        pass
except Exception as e:
    logger.error(f"❌ Ошибка инициализации ProxyAPI клиента: {e}")
    proxy_client = None

# Кэш для результатов
results_cache = {}
CACHE_EXPIRY_HOURS = 24

class LocationRequest(BaseModel):
    location: str
    
    @field_validator('location')
    @classmethod
    def validate_location(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Название населенного пункта должно содержать минимум 2 символа')
        if len(v.strip()) > 100:
            raise ValueError('Название населенного пункта слишком длинное')
        return v.strip()

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
    timestamp: str
    location: str

class NameListResult(BaseModel):
    location: str
    names: List[str]
    timestamp: str

class WebsiteFindRequest(BaseModel):
    location: str
    names: List[str]

    @field_validator('location')
    @classmethod
    def _validate_location(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Название населенного пункта должно содержать минимум 2 символа')
        if len(v.strip()) > 100:
            raise ValueError('Название населенного пункта слишком длинное')
        return v.strip()

class WebsiteItem(BaseModel):
    name: str
    website: str

class WebsiteFindResult(BaseModel):
    location: str
    items: List[WebsiteItem]
    logs: List[str]
    timestamp: str

class WebsiteExportItem(BaseModel):
    name: str
    website: str
    email: str = ""
    address: str = ""

class WebsiteExportRequest(BaseModel):
    location: str
    items: List[WebsiteExportItem]

# Новые модели для работы с кэшем
class CacheStatusResponse(BaseModel):
    location_match: bool
    next_stage: str
    process_status: Dict[str, Any]
    organizations_count: int
    cache_data: Optional[Dict[str, Any]] = None

class CacheUpdateRequest(BaseModel):
    location: str
    stage: str  # 'names', 'websites', 'contacts'
    status: str  # 'completed', 'interrupted', 'not_started'
    organizations: Optional[List[Dict[str, str]]] = None


class ContactExtractItem(BaseModel):
    name: str
    website: str

class ContactExtractedItem(BaseModel):
    name: str
    website: str
    email: str
    address: str

class ContactExtractRequest(BaseModel):
    location: str
    items: List[ContactExtractItem]

class ContactExtractResult(BaseModel):
    location: str
    items: List[ContactExtractedItem]
    logs: List[str]
    timestamp: str


@app.post("/extract-contacts", response_model=ContactExtractResult)
async def extract_contacts(req: ContactExtractRequest):
    """Извлекает email и почтовый адрес с сайтов организаций.

    Обрабатывает элементы по одному, выполняя краулинг в отдельном потоке,
    чтобы не блокировать event loop. Разрешены поддомены в рамках одного
    корневого домена. Возвращает 'как на сайте'.
    """
    logger.info("➡️ POST /extract-contacts from 127.0.0.1")
    logger.info(f"🧾 Request body: {req.model_dump()}")
    try:
        logs: List[str] = []
        out_items: List[ContactExtractedItem] = []
        items = req.items or []
        for it in items:
            name = (it.name or '').strip()
            website = (it.website or '').strip()
            if website and not website.startswith(('http://', 'https://')):
                website = 'http://' + website
            if not website:
                out_items.append(ContactExtractedItem(name=name, website='', email='', address=''))
                continue
            # Выполняем краулинг в отдельном потоке
            logs.append(f"🔍 ProxyClient для {website}: {type(proxy_client) if proxy_client else 'None'}")
            res, crawl_logs = await asyncio.to_thread(
                contacts_crawler.extract_from_site,
                website,
                req.location,
                allow_subdomains=True,
                max_pages=12,
                max_depth=2,
                proxy_client=proxy_client,
            )
            try:
                logs.extend(crawl_logs or [])
            except Exception:
                pass
            email = (res or {}).get('email') or ''
            address = (res or {}).get('address') or ''
            out_items.append(ContactExtractedItem(name=name, website=website, email=email, address=address))

        result = ContactExtractResult(
            location=req.location,
            items=out_items,
            logs=logs,
            timestamp=datetime.now().isoformat()
        )
        logger.info(f"⬅️ 200 POST /extract-contacts body: {result.model_dump()}")
        return result
    except Exception as e:
        logger.error(f"Ошибка извлечения контактов: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка извлечения контактов: {e}")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

def _names_file_path(location: str) -> Path:
    key = hashlib.sha1(location.strip().lower().encode('utf-8')).hexdigest()[:16]
    safe_loc = ''.join(ch for ch in location if ch.isalnum() or ch in (' ', '-', '_')).strip().replace(' ', '_')
    fname = f"names_{safe_loc}_{key}.json"
    return NAMES_STORE_DIR / fname

def _write_names_file(location: str, names: List[str]) -> Path:
    path = _names_file_path(location)
    data = {
        'location': location,
        'names': names,
        'timestamp': datetime.now().isoformat()
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path

def _read_names_file(location: str) -> Optional[List[str]]:
    path = _names_file_path(location)
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('names'), list):
            return data['names']
    except Exception as e:
        logger.warning(f"Не удалось прочитать файл названий для {location}: {e}")
    return None

def _cleanup_temp_names_files(location: Optional[str] = None) -> int:
    """Удаляет временные файлы temp_названия_*.xlsx. Если указан location — только для него."""
    try:
        patterns: List[str] = []
        if location and location.strip():
            patterns.append(f"temp_названия_{location.strip()}_*.xlsx")
        # Всегда подчищаем общий мусор на всякий случай
        patterns.append("temp_названия_*.xlsx")

        checked_dirs = {PROJECT_ROOT, BACKEND_DIR, Path.cwd()}
        removed = 0
        for d in checked_dirs:
            for pat in patterns:
                for p in d.glob(pat):
                    try:
                        p.unlink()
                        removed += 1
                    except Exception as e:
                        logger.warning(f"Не удалось удалить временный файл {p}: {e}")
        if removed:
            logger.info(f"🧹 Удалено временных файлов названий: {removed}")
        return removed
    except Exception as e:
        logger.warning(f"Ошибка очистки временных файлов названий: {e}")
        return 0

def _normalize(s: str) -> str:
    return ''.join(ch.lower() for ch in s if ch.isalnum() or ch.isspace()).strip()

def _looks_like_same_place(query: str, candidate_name: str) -> bool:
    q = _normalize(query)
    c = _normalize(candidate_name)
    if not q or not c:
        return False
    # точное вхождение или совпадение по словам
    if q == c:
        return True
    if q in c:
        return True
    # проверка по словам (все слова запроса присутствуют в названии результата)
    q_words = [w for w in q.split() if w]
    return all(w in c for w in q_words)

def _validate_location_exists(location: str) -> bool:
    """Проверяет существование населённого пункта через Nominatim.
    Возвращает True только для place/boundary соответствующих типов и при разумном совпадении названия.
    """
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": location, "format": "jsonv2", "limit": 1, "addressdetails": 1}
        headers = {
            "Accept": "application/json",
            "User-Agent": "ResortContactsCollector/1.0 (contact@example.com)"
        }
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, list) or not data:
            # Фолбэк через наш name_finder (с корректным UA)
            center = None
            try:
                center = name_finder._geocode_city_center(location)  # noqa: SLF001
            except Exception:
                center = None
            return bool(center)
        item = data[0]
        item_class = (item.get("class") or "").lower()
        item_type = (item.get("type") or "").lower()
        allowed_types = {"city", "town", "village", "hamlet", "municipality", "county", "state", "province", "suburb", "locality", "neighbourhood"}
        if item_class not in {"place", "boundary"}:
            return False
        # для boundary принимаем administrative
        if item_class == "boundary" and item_type not in {"administrative"}:
            return False
        if item_class == "place" and item_type and item_type not in allowed_types:
            # не отвергаем сразу: фолбэк через геоцентр
            center = None
            try:
                center = name_finder._geocode_city_center(location)  # noqa: SLF001
            except Exception:
                center = None
            return bool(center)
        disp = item.get("display_name") or item.get("name") or ""
        if _looks_like_same_place(location, disp):
            return True
        # Фолбэк: если строковое сопоставление не прошло — попробуем центр
        center = None
        try:
            center = name_finder._geocode_city_center(location)  # noqa: SLF001
        except Exception:
            center = None
        return bool(center)
    except Exception as e:
        logger.warning(f"Ошибка валидации населённого пункта: {e}")
        # Последний фолбэк
        try:
            center = name_finder._geocode_city_center(location)  # noqa: SLF001
            return bool(center)
        except Exception:
            return False

@app.post("/list-names", response_model=NameListResult)
async def list_names(request: LocationRequest):
    try:
        # Удаляем предыдущие временные файлы экспорта для чистоты
        _cleanup_temp_names_files(request.location)
        # 1) Пытаемся быстро отдать из файла, если он есть и не пустой
        cached = _read_names_file(request.location)
        if cached:
            logger.info(f"Отдаю названия из файла для {request.location}: {len(cached)}")
            return NameListResult(location=request.location, names=cached, timestamp=datetime.now().isoformat())

        # 2) Ищем названия в отдельном потоке с таймаутом, чтобы не блокировать event loop
        start_ts = datetime.now()
        logger.info(f"Начинаю поиск названий для {request.location}")
        try:
            names = await asyncio.wait_for(asyncio.to_thread(name_finder.find_accommodation_names, request.location), timeout=45)
        except asyncio.TimeoutError:
            logger.warning(f"Таймаут поиска названий для {request.location}")
            names = []
        except Exception as e:
            logger.error(f"Ошибка поиска названий для {request.location}: {e}")
            names = []
        finally:
            took = (datetime.now() - start_ts).total_seconds()
            logger.info(f"Поиск названий для {request.location} завершён за {took:.1f}с. Найдено: {len(names)}")

        # 3) Сохраняем результат только если что-то нашли
        if names:
            _write_names_file(request.location, names)
        return NameListResult(location=request.location, names=names or [], timestamp=datetime.now().isoformat())
    except HTTPException as e:
        # Пробрасываем как есть, чтобы сохранить статус-код (например, 404)
        raise e
    except Exception as e:
        logger.error(f"Ошибка получения списка названий: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка получения списка названий: {str(e)}")

@app.get("/export-names-excel/{location}")
async def export_names_excel_get(location: str):
    """Экспорт списка названий (GET) с приоритетом чтения из файла."""
    try:
        names = _read_names_file(location) or []
        if not names:
            # Если файла нет — находим и сохраняем, чтобы в следующий раз было быстро
            names = name_finder.find_accommodation_names(location)
            _write_names_file(location, names)

        df = pd.DataFrame({'name': names})
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'названия_{location}_{timestamp}.xlsx'
        temp_path = f"temp_{filename}"

        try:
            with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Названия')
                ws = writer.sheets['Названия']
                ws.insert_rows(1)
                ws['A1'] = f'Названия для: {location}'
                ws.insert_rows(2)
                ws['A2'] = f'Дата экспорта: {datetime.now().strftime("%d.%m.%Y %H:%M")}'
                ws.insert_rows(3)
                ws['A3'] = f'Найдено: {len(names)}'

            return FileResponse(
                temp_path,
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                filename=filename
            )
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise HTTPException(status_code=500, detail=f"Ошибка создания Excel: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка экспорта названий: {str(e)}")

@app.post("/export-names-excel")
async def export_names_excel_post(req: WebsiteExportRequest):
    """Экспорт списка названий (и сайтов, если переданы) через POST."""
    try:
        items = req.items or []
        # Всегда экспортируем колонки: name, website, email, address
        rows: List[Dict[str, str]] = []
        for it in items:
            rows.append({
                'name': (it.name or ''),
                'website': ((it.website or '').strip() or 'сайт не найден'),
                'email': ((getattr(it, 'email', '') or '').strip() or 'не найден'),
                'address': ((getattr(it, 'address', '') or '').strip() or 'не найден'),
            })
        if not rows:
            df = pd.DataFrame(columns=['name', 'website', 'email', 'address'])
        else:
            df = pd.DataFrame(rows, columns=['name', 'website', 'email', 'address'])

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'названия_{req.location}_{timestamp}.xlsx'
        temp_path = f"temp_{filename}"
        try:
            with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
                sheet = 'Названия'
                df.to_excel(writer, index=False, sheet_name=sheet)
                ws = writer.sheets[sheet]
                ws.insert_rows(1)
                ws['A1'] = f'Названия для: {req.location}'
                ws.insert_rows(2)
                ws['A2'] = f'Дата экспорта: {datetime.now().strftime("%d.%m.%Y %H:%M")}'
                # Объединяем заголовок на четыре колонки
                ws.merge_cells('A1:D1')
                ws.merge_cells('A2:D2')
            return FileResponse(
                temp_path,
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                filename=filename
            )
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise HTTPException(status_code=500, detail=f"Ошибка создания Excel: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка экспорта названий: {str(e)}")

@app.post("/find-websites", response_model=WebsiteFindResult)
async def find_websites(request: WebsiteFindRequest):
    try:
        # Выполняем работу в отдельном потоке, чтобы не блокировать event loop
        agent = WebsiteFinderAgent(proxy_client=proxy_client)
        items, logs = await asyncio.to_thread(agent.find_for_names, request.location, request.names)
        return WebsiteFindResult(
            location=request.location,
            items=[WebsiteItem(**it) for it in items],
            logs=logs,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Ошибка поиска сайтов: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка поиска сайтов: {e}")

# Новые API endpoints для работы с кэшем
@app.get("/cache-status/{location}", response_model=CacheStatusResponse)
async def get_cache_status(location: str):
    """Проверяет статус кэша для указанного города"""
    try:
        location_match, cache_data = cache_manager.check_location_match(location)
        
        if not location_match:
            return CacheStatusResponse(
                location_match=False,
                next_stage="names",
                process_status={"names_found": False, "websites_found": False, "contacts_extracted": False},
                organizations_count=0
            )
        
        next_stage = cache_manager.get_next_stage(cache_data)
        process_status = {
            "names_found": cache_data.process_status.names_found,
            "websites_found": cache_data.process_status.websites_found,
            "contacts_extracted": cache_data.process_status.contacts_extracted,
            "last_completed_stage": cache_data.process_status.last_completed_stage,
            "last_stage_status": cache_data.process_status.last_stage_status
        }
        
        return CacheStatusResponse(
            location_match=True,
            next_stage=next_stage,
            process_status=process_status,
            organizations_count=len(cache_data.organizations),
            cache_data={
                "current_location": cache_data.current_location,
                "last_update": cache_data.last_update,
                "organizations": [
                    {
                        "name": org.name,
                        "website": org.website,
                        "email": org.email,
                        "address": org.address
                    }
                    for org in cache_data.organizations
                ]
            }
        )
    except Exception as e:
        logger.error(f"Ошибка получения статуса кэша: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка получения статуса кэша: {e}")

@app.post("/cache-update")
async def update_cache(request: CacheUpdateRequest):
    """Обновляет кэш после завершения этапа"""
    try:
        # Проверяем совпадение города
        location_match, cache_data = cache_manager.check_location_match(request.location)
        
        if not location_match:
            # Создаем новый кэш для нового города
            cache_manager.archive_current_cache()
            cache_data = cache_manager.create_empty_cache(request.location)
        
        # Обновляем статус этапа
        cache_data = cache_manager.update_stage_status(cache_data, request.stage, request.status)
        
        # Обновляем организации если переданы
        if request.organizations:
            cache_data.organizations = [
                Organization(
                    name=org.get("name", ""),
                    website=org.get("website", ""),
                    email=org.get("email", ""),
                    address=org.get("address", "")
                )
                for org in request.organizations
            ]
        
        # Сохраняем кэш
        success = cache_manager.save_cache(cache_data)
        
        if success:
            return {"status": "success", "message": "Кэш обновлен"}
        else:
            raise HTTPException(status_code=500, detail="Ошибка сохранения кэша")
            
    except Exception as e:
        logger.error(f"Ошибка обновления кэша: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка обновления кэша: {e}")

@app.post("/cache-clear/{location}")
async def clear_cache(location: str):
    """Очищает кэш для указанного города"""
    try:
        cache_manager.archive_current_cache()
        cache_manager.clear_cache()
        logger.info(f"Кэш очищен для города: {location}")
        return {"status": "success", "message": "Кэш очищен"}
    except Exception as e:
        logger.error(f"Ошибка очистки кэша: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка очистки кэша: {e}")

@app.post("/collect-contacts", response_model=CollectionResult)
async def collect_contacts(request: LocationRequest, background_tasks: BackgroundTasks):
    try:
        # Проверяем кэш
        cache_key = f"{request.location.lower().strip()}"
        if cache_key in results_cache:
            cached_result = results_cache[cache_key]
            if datetime.now() - cached_result['timestamp'] < timedelta(hours=CACHE_EXPIRY_HOURS):
                logger.info(f"Возвращаем кэшированный результат для {request.location}")
                return cached_result['result']
            else:
                # Удаляем устаревший кэш
                del results_cache[cache_key]
        
        logs = []
        contacts = []
        
        # Агентный режим
        logs.append(f"🤖 Агент начинает сбор для: {request.location}")
        if not proxy_client:
            raise Exception("ProxyAPI клиент не инициализирован")
        agent = ContactAgent(proxy_client=proxy_client)
        agent_contacts, agent_logs = await agent.run(request.location)
        logs.extend(agent_logs)
        contacts = [ContactInfo(**c) for c in agent_contacts]
        
        # Создаем результат
        result = CollectionResult(
            logs=logs,
            contacts=contacts,
            timestamp=datetime.now().isoformat(),
            location=request.location
        )
        
        # Кэшируем результат
        results_cache[cache_key] = {
            'result': result,
            'timestamp': datetime.now()
        }
        
        # Очищаем старые записи кэша
        background_tasks.add_task(cleanup_old_cache)
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка сбора контактов: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка сбора контактов: {str(e)}")

@app.get("/export-excel/{location}")
async def export_excel(location: str):
    """Экспорт результатов в Excel файл"""
    try:
        cache_key = f"{location.lower().strip()}"
        if cache_key not in results_cache:
            raise HTTPException(status_code=404, detail="Результаты для данного населенного пункта не найдены")
        
        cached_data = results_cache[cache_key]
        contacts = cached_data['result'].contacts
        
        if not contacts:
            # Создаем пустой DataFrame с заголовками
            df = pd.DataFrame(columns=['name', 'address', 'coordinates', 'email', 'website'])
            logger.info(f"Создаем пустой Excel файл для {location} (0 контактов)")
        else:
            # Создаем DataFrame с данными
            df = pd.DataFrame([contact.model_dump() for contact in contacts])
            logger.info(f"Создаем Excel файл для {location} с {len(contacts)} контактами")
        
        # Создаем временный файл
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'контакты_{location}_{timestamp}.xlsx'
        
        # Создаем временный файл в текущей директории
        temp_path = f"temp_{filename}"
        
        try:
            # Добавляем заголовок с информацией
            with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Контакты')
                
                # Получаем рабочую книгу для добавления метаданных
                workbook = writer.book
                worksheet = writer.sheets['Контакты']
                
                # Добавляем заголовок с информацией
                worksheet.insert_rows(1)
                worksheet['A1'] = f'Контакты для: {location}'
                worksheet['A2'] = f'Дата сбора: {datetime.now().strftime("%d.%m.%Y %H:%M")}'
                worksheet['A3'] = f'Найдено контактов: {len(contacts)}'
                
                # Объединяем ячейки для заголовка
                worksheet.merge_cells('A1:E1')
                worksheet.merge_cells('A2:E2')
                worksheet.merge_cells('A3:E3')
            
            logger.info(f"Excel файл успешно создан: {temp_path}")
            
            # Возвращаем файл
            return FileResponse(
                temp_path,
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                filename=filename
            )
        except Exception as e:
            logger.error(f"Ошибка создания Excel файла: {str(e)}")
            # Удаляем временный файл в случае ошибки
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise HTTPException(status_code=500, detail=f"Ошибка создания Excel файла: {str(e)}")
        
    except Exception as e:
        logger.error(f"Ошибка экспорта в Excel: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка экспорта: {str(e)}")

@app.post("/export-websites-excel")
async def export_websites_excel(req: WebsiteExportRequest):
    """Экспорт найденных сайтов в Excel по текущему списку имён."""
    try:
        rows = [{"name": it.name, "website": it.website} for it in (req.items or [])]
        df = pd.DataFrame(rows if rows else [], columns=["name", "website"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'сайты_{req.location}_{timestamp}.xlsx'
        temp_path = f"temp_{filename}"
        try:
            with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Сайты')
                ws = writer.sheets['Сайты']
                ws.insert_rows(1)
                ws['A1'] = f'Сайты для: {req.location}'
                ws.insert_rows(2)
                ws['A2'] = f'Дата экспорта: {datetime.now().strftime("%d.%m.%Y %H:%M")}'
                ws.merge_cells('A1:B1')
                ws.merge_cells('A2:B2')
            return FileResponse(
                temp_path,
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                filename=filename
            )
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise HTTPException(status_code=500, detail=f"Ошибка создания Excel: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка экспорта сайтов: {str(e)}")

@app.get("/cache-status")
async def get_cache_status():
    """Получение статуса кэша"""
    cache_info = {
        'total_entries': len(results_cache),
        'entries': []
    }
    
    for location, data in results_cache.items():
        age_hours = (datetime.now() - data['timestamp']).total_seconds() / 3600
        cache_info['entries'].append({
            'location': location,
            'age_hours': round(age_hours, 2),
            'contacts_count': len(data['result'].contacts),
            'timestamp': data['timestamp'].isoformat()
        })
    
    return cache_info

async def cleanup_old_cache():
    """Очистка устаревших записей кэша"""
    current_time = datetime.now()
    expired_keys = []
    
    for key, data in results_cache.items():
        if current_time - data['timestamp'] > timedelta(hours=CACHE_EXPIRY_HOURS):
            expired_keys.append(key)
    
    for key in expired_keys:
        del results_cache[key]
        logger.info(f"Удалена устаревшая запись кэша: {key}")

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
        if not proxy_client:
            raise Exception("ProxyAPI клиент не инициализирован")
            
        logger.info(f"=== ВЫПОЛНЕНИЕ ШАГА {step.step} ===")
        logger.info(f"Выполняем шаг: {step.step} - {step.description}")
        logger.info(f"Промпт для шага: {enhanced_prompt}")
        
        response = await proxy_client.chat_completion(
            model="claude-3-5-sonnet-20240620",
            messages=[{"role": "user", "content": enhanced_prompt}],
            max_tokens=1000
        )
        
        logger.info(f"=== ПОЛУЧЕН ОТВЕТ ДЛЯ ШАГА {step.step} ===")
        logger.info(f"ProxyAPI ответ для шага получен: {response}")
        try:
            result = response['choices'][0]['message']['content']
        except Exception:
            logger.error(f"Неверный формат ответа шага: {response}")
            raise
        logger.info(f"Результат шага {step.step}: {result[:200]}...")
        logger.info(f"Полный результат шага {step.step}: {result}")
        
        # Дополнительная обработка результата для извлечения контактов
        logger.info(f"=== ИЗВЛЕЧЕНИЕ КОНТАКТОВ ИЗ ШАГА {step.step} ===")
        logger.info(f"Извлекаем контакты из результата шага {step.step}")
        extracted_contacts = contact_extractor.extract_contacts_from_text(result)
        logger.info(f"Извлеченные контакты из шага {step.step}: {extracted_contacts}")
        
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
            logger.info(f"Шаг {step.step} завершен с контактами")
            return enhanced_result
        
        logger.info(f"Шаг {step.step} завершен без контактов")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка выполнения шага {step.step}: {str(e)}")
        logger.error(f"Тип ошибки шага: {type(e).__name__}")
        logger.error(f"Детали ошибки шага: {e}")
        return f"Ошибка выполнения шага: {str(e)}"

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

@app.get("/log-path")
async def get_log_path():
    try:
        exists = os.path.exists(LOG_PATH)
        size = os.path.getsize(LOG_PATH) if exists else 0
        return {"path": LOG_PATH, "exists": exists, "size": size}
    except Exception as e:
        logger.error(f"Ошибка чтения пути лога: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/logs")
async def get_logs(tail: int = 200):
    try:
        if not os.path.exists(LOG_PATH):
            return {"lines": [], "message": "Файл лога не найден", "path": LOG_PATH}
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        tail = max(1, min(tail, 5000))
        return {"path": LOG_PATH, "lines": [l.rstrip("\n") for l in lines[-tail:]]}
    except Exception as e:
        logger.error(f"Ошибка чтения лога: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
