import requests
from bs4 import BeautifulSoup
import re
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class WebScraper:
    """Утилита для работы с веб-страницами"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def get_page_content(self, url: str) -> Optional[str]:
        """Получение содержимого веб-страницы"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            
            # Парсинг HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Удаление скриптов и стилей
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Извлечение текста
            text = soup.get_text()
            
            # Очистка текста
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения страницы {url}: {str(e)}")
            return None
    
    def extract_emails(self, text: str) -> list:
        """Извлечение email адресов из текста"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        return list(set(emails))  # Убираем дубликаты
    
    def extract_phones(self, text: str) -> list:
        """Извлечение телефонных номеров из текста"""
        phone_patterns = [
            r'\+7\s?\(?\d{3}\)?\s?\d{3}[- ]?\d{2}[- ]?\d{2}',  # +7 (XXX) XXX-XX-XX
            r'8\s?\(?\d{3}\)?\s?\d{3}[- ]?\d{2}[- ]?\d{2}',   # 8 (XXX) XXX-XX-XX
            r'\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}',           # XXX-XXX-XX-XX
        ]
        
        phones = []
        for pattern in phone_patterns:
            found = re.findall(pattern, text)
            phones.extend(found)
        
        return list(set(phones))
    
    def extract_coordinates(self, text: str) -> list:
        """Извлечение географических координат из текста"""
        coord_patterns = [
            r'(\d{1,2}°\d{1,2}′\d{1,2}″[NS]?\s+\d{1,2}°\d{1,2}′\d{1,2}″[EW]?)',  # Градусы, минуты, секунды
            r'(\d{1,2}\.\d{4,6}[NS]?\s+\d{1,2}\.\d{4,6}[EW]?)',  # Десятичные градусы
            r'(\d{1,2}\.\d{4,6}°[NS]?\s+\d{1,2}\.\d{4,6}°[EW]?)',  # С градусами
        ]
        
        coordinates = []
        for pattern in coord_patterns:
            found = re.findall(pattern, text)
            coordinates.extend(found)
        
        return list(set(coordinates))
    
    def extract_addresses(self, text: str) -> list:
        """Извлечение адресов из текста"""
        # Простой паттерн для российских адресов
        address_patterns = [
            r'[А-Яа-я\s]+,\s*[А-Яа-я\s]+,\s*[А-Яа-я\s]+,\s*\d+',  # Город, улица, дом
            r'[А-Яа-я\s]+,\s*[А-Яа-я\s]+,\s*\d+',  # Улица, дом
            r'[А-Яа-я\s]+,\s*\d+',  # Улица, дом
        ]
        
        addresses = []
        for pattern in address_patterns:
            found = re.findall(pattern, text)
            addresses.extend(found)
        
        return list(set(addresses))
    
    def clean_text(self, text: str) -> str:
        """Очистка текста от лишних символов"""
        if not text:
            return ""
        
        # Удаление лишних пробелов
        text = re.sub(r'\s+', ' ', text)
        
        # Удаление специальных символов
        text = re.sub(r'[^\w\s\-.,!?()]', '', text)
        
        # Ограничение длины
        if len(text) > 5000:
            text = text[:5000] + "..."
        
        return text.strip()

class ContactExtractor:
    """Класс для извлечения контактной информации"""
    
    def __init__(self):
        self.scraper = WebScraper()
    
    def extract_contacts_from_text(self, text: str) -> Dict[str, Any]:
        """Извлечение всех типов контактов из текста"""
        if not text:
            return {}
        
        cleaned_text = self.scraper.clean_text(text)
        
        return {
            'emails': self.scraper.extract_emails(cleaned_text),
            'phones': self.scraper.extract_phones(cleaned_text),
            'coordinates': self.scraper.extract_coordinates(cleaned_text),
            'addresses': self.scraper.extract_addresses(cleaned_text),
            'cleaned_text': cleaned_text
        }
    
    def extract_contacts_from_url(self, url: str) -> Dict[str, Any]:
        """Извлечение контактов с веб-страницы"""
        content = self.scraper.get_page_content(url)
        if content:
            return self.extract_contacts_from_text(content)
        return {}
    
    def merge_contact_data(self, data_list: list) -> Dict[str, Any]:
        """Объединение данных из нескольких источников"""
        merged = {
            'emails': [],
            'phones': [],
            'coordinates': [],
            'addresses': [],
            'all_texts': []
        }
        
        for data in data_list:
            if isinstance(data, dict):
                for key in merged:
                    if key in data and data[key]:
                        if isinstance(data[key], list):
                            merged[key].extend(data[key])
                        else:
                            merged[key].append(data[key])
        
        # Убираем дубликаты
        for key in merged:
            if isinstance(merged[key], list):
                merged[key] = list(set(merged[key]))
        
        return merged

# Создание глобального экземпляра
scraper = WebScraper()
contact_extractor = ContactExtractor()
