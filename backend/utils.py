import requests
from bs4 import BeautifulSoup
import re
from typing import Optional, Dict, Any, List
import logging
from urllib.parse import urljoin, urlparse

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
            # Более дружелюбные заголовки
            self.session.headers.update({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': url
            })
            response = self.session.get(url, timeout=15)
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

    def get_links(self, url: str, max_links: int = 20, keywords: Optional[List[str]] = None) -> List[str]:
        """Извлекает релевантные ссылки со страницы для дальнейшего обхода."""
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            raw_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith('javascript:'):
                    continue
                abs_url = urljoin(url, href)
                raw_links.append(abs_url)

            if keywords is None:
                keywords = [
                    'hotel', 'otel', 'guest', 'hostel', 'booking', 'tripadvisor',
                    'гост', 'отел', 'санатор', 'пансионат', 'база', 'геленджик', 'курорт',
                    'contact', 'kontact', 'kontakty', 'contacts', 'about', 'o-kompanii'
                ]
            filtered: List[str] = []
            seen = set()
            for link in raw_links:
                low = link.lower()
                if any(k in low for k in keywords):
                    parsed = urlparse(link)
                    key = (parsed.scheme, parsed.netloc, parsed.path)
                    if key in seen:
                        continue
                    seen.add(key)
                    filtered.append(link)
                    if len(filtered) >= max_links:
                        break
            return filtered
        except Exception as e:
            logger.error(f"Ошибка извлечения ссылок с {url}: {e}")
            return []

    def get_title(self, url: str) -> str:
        """Возвращает <title> страницы (для имени)."""
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            return (soup.title.string or '').strip() if soup.title else ''
        except Exception as e:
            logger.error(f"Ошибка получения заголовка {url}: {e}")
            return ''
    
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


class NameFinder:
    """Поиск названий объектов размещения в городе через OSM Overpass/Nominatim."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ResortContactsCollector/1.0 (contact@example.com)'
        })
        self.overpass_endpoints = [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.openstreetmap.ru/api/interpreter"
        ]

    def _overpass_query_by_area(self, city: str) -> str:
        # Ищем административную область города и все объекты размещения внутри
        return f"""
        [out:json][timeout:25];
        area["name"="{city}"]["boundary"="administrative"]["admin_level"~"^(6|7|8|9)$"]->.a;
        (
          node["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|chalet|alpine_hut|camp_site"](area.a);
          way["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|chalet|alpine_hut|camp_site"](area.a);
          relation["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|chalet|alpine_hut|camp_site"](area.a);
          node["amenity"~"hotel|hostel|motel"](area.a);
          way["amenity"~"hotel|hostel|motel"](area.a);
          relation["amenity"~"hotel|hostel|motel"](area.a);
        );
        out tags;
        """.strip()

    def _overpass_query_by_bbox(self, bbox: List[str]) -> str:
        # bbox: [south, north, west, east]
        south, north, west, east = bbox
        return f"""
        [out:json][timeout:25];
        (
          node["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|chalet|alpine_hut|camp_site"]({south},{west},{north},{east});
          way["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|chalet|alpine_hut|camp_site"]({south},{west},{north},{east});
          relation["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|chalet|alpine_hut|camp_site"]({south},{west},{north},{east});
          node["amenity"~"hotel|hostel|motel"]({south},{west},{north},{east});
          way["amenity"~"hotel|hostel|motel"]({south},{west},{north},{east});
          relation["amenity"~"hotel|hostel|motel"]({south},{west},{north},{east});
        );
        out tags;
        """.strip()

    def _overpass_query_around(self, lat: float, lon: float, radius_m: int) -> str:
        # Поиск вокруг точки города с заданным радиусом
        return f"""
        [out:json][timeout:25];
        (
          node(around:{radius_m},{lat},{lon})["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|apartments|chalet|alpine_hut|camp_site"];
          way(around:{radius_m},{lat},{lon})["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|apartments|chalet|alpine_hut|camp_site"];
          relation(around:{radius_m},{lat},{lon})["tourism"~"hotel|guest_house|hostel|motel|resort|apartment|apartments|chalet|alpine_hut|camp_site"];
          node(around:{radius_m},{lat},{lon})["amenity"~"hotel|hostel|motel"];
          way(around:{radius_m},{lat},{lon})["amenity"~"hotel|hostel|motel"];
          relation(around:{radius_m},{lat},{lon})["amenity"~"hotel|hostel|motel"];
          way(around:{radius_m},{lat},{lon})["building"="hotel"];
          relation(around:{radius_m},{lat},{lon})["building"="hotel"];
        );
        out tags;
        """.strip()

    def _fetch_overpass(self, query: str) -> List[str]:
        names: List[str] = []
        for url in self.overpass_endpoints:
            try:
                resp = self.session.post(url, data={"data": query}, timeout=45)
                resp.raise_for_status()
                data = resp.json()
                for el in data.get("elements", []):
                    tags = el.get("tags") or {}
                    name = tags.get("name") or tags.get("name:ru") or tags.get("name:en")
                    if name:
                        names.append(name.strip())
                if names:
                    break
            except Exception as e:
                logger.warning(f"Overpass error via {url}: {e}")
                continue
        return names

    def _geocode_city_bbox(self, city: str) -> Optional[List[str]]:
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": city, "format": "json", "limit": 1}
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            bbox = data[0].get("boundingbox")
            if bbox and len(bbox) == 4:
                # boundingbox: [south, north, west, east]
                return [str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3])]
            return None
        except Exception as e:
            logger.warning(f"Nominatim error: {e}")
            return None

    def _geocode_city_center(self, city: str) -> Optional[Dict[str, float]]:
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": city, "format": "json", "limit": 1}
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
        except Exception as e:
            logger.warning(f"Nominatim center error: {e}")
            return None

    def find_accommodation_names(self, city: str, limit: int = 200) -> List[str]:
        """Возвращает список названий объектов размещения в городе."""
        if not city or len(city.strip()) < 2:
            return []

        # 1) Пытаемся через область города в Overpass
        query_area = self._overpass_query_by_area(city.strip())
        names = self._fetch_overpass(query_area)

        # 2) Если ничего не нашли — пробуем по bbox города через Nominatim
        if not names:
            bbox = self._geocode_city_bbox(city.strip())
            if bbox:
                query_bbox = self._overpass_query_by_bbox(bbox)
                names = self._fetch_overpass(query_bbox)

        # 3) Если все еще пусто — ищем вокруг геоцентра города на растущем радиусе
        if not names:
            center = self._geocode_city_center(city.strip())
            if center:
                for radius in [3000, 7000, 15000, 25000]:
                    query_around = self._overpass_query_around(center["lat"], center["lon"], radius)
                    names = self._fetch_overpass(query_around)
                    if names:
                        break

        # Нормализуем список
        unique = []
        seen = set()
        for n in names:
            k = n.strip()
            if not k:
                continue
            if k in seen:
                continue
            seen.add(k)
            unique.append(k)

        if limit and len(unique) > limit:
            unique = unique[:limit]

        return unique

# Глобальный экземпляр для поиска названий
name_finder = NameFinder()
