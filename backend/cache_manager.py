"""
Модуль для управления кэшем данных о курортах и организациях.
Обеспечивает сохранение промежуточных результатов и восстановление состояния.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)

@dataclass
class Organization:
    """Структура данных об организации"""
    name: str
    website: str = ""
    email: str = ""
    address: str = ""

@dataclass
class ProcessStatus:
    """Статус выполнения процессов"""
    names_found: bool = False
    websites_found: bool = False
    contacts_extracted: bool = False
    last_completed_stage: Optional[str] = None  # 'names', 'websites', 'contacts'
    last_stage_status: str = "not_started"  # 'completed', 'interrupted', 'not_started'

@dataclass
class CacheData:
    """Структура данных кэша"""
    current_location: str
    last_update: str
    process_status: ProcessStatus
    organizations: List[Organization]

class CacheManager:
    """Менеджер кэша данных"""
    
    def __init__(self, cache_dir: str = "backend"):
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, "data_cache.json")
        self.archive_file = os.path.join(cache_dir, "data_cache_archive.json")
        
        # Создаем директорию если не существует
        os.makedirs(cache_dir, exist_ok=True)
    
    def _serialize_cache_data(self, data: CacheData) -> Dict:
        """Преобразует CacheData в словарь для JSON"""
        result = asdict(data)
        result['process_status'] = asdict(data.process_status)
        return result
    
    def _deserialize_cache_data(self, data: Dict) -> CacheData:
        """Преобразует словарь из JSON в CacheData"""
        # Преобразуем организации
        organizations = [Organization(**org) for org in data.get('organizations', [])]
        
        # Преобразуем статус процесса
        process_status_data = data.get('process_status', {})
        process_status = ProcessStatus(**process_status_data)
        
        return CacheData(
            current_location=data.get('current_location', ''),
            last_update=data.get('last_update', ''),
            process_status=process_status,
            organizations=organizations
        )
    
    def load_cache(self) -> Optional[CacheData]:
        """Загружает данные из кэша"""
        try:
            if not os.path.exists(self.cache_file):
                return None
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return self._deserialize_cache_data(data)
        except Exception as e:
            logger.error(f"Ошибка загрузки кэша: {e}")
            return None
    
    def save_cache(self, data: CacheData) -> bool:
        """Сохраняет данные в кэш"""
        try:
            data.last_update = datetime.now().isoformat()
            serialized_data = self._serialize_cache_data(data)
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(serialized_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Кэш сохранен для города: {data.current_location}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения кэша: {e}")
            return False
    
    def archive_current_cache(self) -> bool:
        """Архивирует текущий кэш"""
        try:
            if os.path.exists(self.cache_file):
                # Перезаписываем архивный файл
                with open(self.cache_file, 'r', encoding='utf-8') as src:
                    with open(self.archive_file, 'w', encoding='utf-8') as dst:
                        dst.write(src.read())
                logger.info("Текущий кэш заархивирован")
                return True
        except Exception as e:
            logger.error(f"Ошибка архивирования кэша: {e}")
        return False
    
    def clear_cache(self) -> bool:
        """Очищает текущий кэш"""
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
                logger.info("Кэш очищен")
                return True
        except Exception as e:
            logger.error(f"Ошибка очистки кэша: {e}")
        return False
    
    def check_location_match(self, location: str) -> Tuple[bool, Optional[CacheData]]:
        """Проверяет совпадение города с кэшем"""
        cache_data = self.load_cache()
        if not cache_data:
            return False, None
        
        # Нормализуем названия для сравнения
        cached_location = cache_data.current_location.lower().strip()
        new_location = location.lower().strip()
        
        return cached_location == new_location, cache_data
    
    def get_next_stage(self, cache_data: CacheData) -> str:
        """Определяет следующий этап на основе статуса процесса"""
        status = cache_data.process_status
        
        if not status.names_found:
            return "names"
        elif not status.websites_found:
            return "websites"
        elif not status.contacts_extracted:
            return "contacts"
        else:
            return "completed"
    
    def update_stage_status(self, cache_data: CacheData, stage: str, status: str) -> CacheData:
        """Обновляет статус этапа"""
        process_status = cache_data.process_status
        
        if stage == "names":
            process_status.names_found = (status == "completed")
        elif stage == "websites":
            process_status.websites_found = (status == "completed")
        elif stage == "contacts":
            process_status.contacts_extracted = (status == "completed")
        
        process_status.last_completed_stage = stage if status == "completed" else None
        process_status.last_stage_status = status
        
        return cache_data
    
    def create_empty_cache(self, location: str) -> CacheData:
        """Создает пустой кэш для нового города"""
        return CacheData(
            current_location=location,
            last_update=datetime.now().isoformat(),
            process_status=ProcessStatus(),
            organizations=[]
        )

# Глобальный экземпляр менеджера кэша
cache_manager = CacheManager()

