import requests
from bs4 import BeautifulSoup
import re
from typing import Optional, Dict, Any, List, Tuple
import os
import time
import logging
from urllib.parse import urljoin, urlparse, parse_qs, unquote

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


class WebSearchEngine:
    """Простой веб-поиск по DuckDuckGo и Bing с фильтрацией агрегаторов.

    Не требует API-ключей. Использует HTML-страницы поиска, поэтому
    селекторы могут со временем меняться. В этом случае логируем и
    возвращаем наилучшее из доступного.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36'
        })

        # Домены агрегаторов и соцсетей, которые обычно не являются "официальными сайтами"
        self.aggregator_domains = {
            'booking.com', 'ostrovok.ru', 'ostrovok.com', '101hotels.com', '101hotels.ru',
            'tripadvisor.com', 'tripadvisor.ru', 'hotels.com', 'expedia.com', 'airbnb.com',
            'yandex.ru', 'travel.yandex.ru', 'maps.yandex.ru', 'google.com', 'maps.google.com',
            'vk.com', 'instagram.com', 'facebook.com', 'ok.ru', 't.me', 'telegram.me',
            'bronevik.com', 'onetwotrip.com', 'sutochno.ru', 'tutu.ru', 'twoyu.ru',
            'turizm.ru', 'turbina.ru', 'turbaza.ru', 'kudago.com', 'avito.ru', 'irr.ru',
            'flamp.ru', 'zoon.ru', '2gis.ru', 'gidgid.ru', 'afisha.ru', 'go-zima.ru',
            'broniryem.ru', 'otelgtk.ru'
        }

    def _cleanup_search_url(self, url: str) -> str:
        """Разворачивает редиректные ссылки (например, DDG ud-dg) и нормализует URL."""
        try:
            parsed = urlparse(url)
            # DuckDuckGo: /l/?kh=-1&uddg=<encoded>
            if parsed.netloc.endswith('duckduckgo.com') and parsed.path.startswith('/l/'):
                qs = parse_qs(parsed.query)
                if 'uddg' in qs:
                    real = qs.get('uddg', [''])[0]
                    return unquote(real)
            return url
        except Exception:
            return url

    def _is_useful_candidate(self, url: str) -> bool:
        if not url or not url.startswith('http'):
            return False
        domain = self._extract_domain(url)
        if not domain:
            return False
        if domain in self.aggregator_domains:
            return False
        # Отсекаем поисковые страницы и трекеры
        bad_parts = ['google.', '/search?', 'yandex.', 'utm_', 'clid=']
        low = url.lower()
        if any(bp in low for bp in bad_parts):
            return False
        return True

    def _extract_domain(self, url: str) -> str:
        try:
            netloc = urlparse(url).netloc.lower()
            if netloc.startswith('www.'):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return ''

    def _search_duckduckgo(self, query: str, max_results: int) -> List[str]:
        try:
            resp = self.session.get('https://duckduckgo.com/html', params={'q': query}, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            candidates: List[str] = []
            # Классический селектор DDG HTML-версии
            for a in soup.select('a.result__a, a.result__url'):
                href = a.get('href')
                if not href:
                    continue
                href = self._cleanup_search_url(href)
                if self._is_useful_candidate(href):
                    candidates.append(href)
                if len(candidates) >= max_results:
                    break
            return candidates
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")
            return []

    def _search_bing(self, query: str, max_results: int) -> List[str]:
        try:
            resp = self.session.get('https://www.bing.com/search', params={'q': query}, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            candidates: List[str] = []
            for a in soup.select('li.b_algo h2 a, h2 a'):
                href = a.get('href')
                if not href:
                    continue
                if self._is_useful_candidate(href):
                    candidates.append(href)
                if len(candidates) >= max_results:
                    break
            return candidates
        except Exception as e:
            logger.warning(f"Bing search failed: {e}")
            return []

    def search(self, query: str, max_results: int = 8) -> List[str]:
        """Возвращает объединённый и дедуплицированный список URL кандидатов."""
        results: List[str] = []
        seen: set = set()
        for provider in (self._search_duckduckgo, self._search_bing):
            for url in provider(query, max_results=max_results):
                key = self._extract_domain(url), urlparse(url).path
                if key in seen:
                    continue
                seen.add(key)
                results.append(url)
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
        return results


# Глобальный экземпляр веб‑поиска
web_search = WebSearchEngine()


class YandexOrgSearch:
    """Клиент для Яндекс Поиска по организациям (Search API v1). Возвращает официальный сайт, если есть.

    Документация: https://yandex.ru/dev/maps/geosearch/
    """

    def __init__(self):
        # Поддержим оба варианта названия переменной на всякий случай
        self.api_key = (
            os.getenv('YANDEX_SEARCH_API_KEY') or
            os.getenv('YANDEX_Search__API_KEY') or
            ''
        )
        self.base_url = 'https://search-maps.yandex.ru/v1/'
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'ResortContactsCollector/1.0'})
        # Храним последние отладочные сообщения
        self.last_debug: List[str] = []
        self.last_status_code: Optional[int] = None
        self.last_error: str = ''

    def _is_enabled(self) -> bool:
        return bool(self.api_key)

    def _root_domain(self, url: str) -> str:
        try:
            host = urlparse(url).netloc.lower()
            if host.startswith('www.'):
                host = host[4:]
            parts = host.split('.')
            if len(parts) >= 2:
                return '.'.join(parts[-2:])
            return host
        except Exception:
            return ''

    def _expand_abbreviations(self, text: str) -> str:
        try:
            import re as _re
            rules = [
                (r"\bпанс\.?\b", "пансионат"),
                (r"\bгост\.?\b", "гостевой дом"),
                (r"\bсан\.?\b", "санаторий"),
                (r"\bб\/о\b", "база отдыха"),
                (r"\bб\.о\.?\b", "база отдыха"),
            ]
            result = text or ""
            for pat, repl in rules:
                result = _re.sub(pat, repl, result, flags=_re.IGNORECASE)
            return result
        except Exception:
            return text

    def _name_tokens(self, text: str) -> List[str]:
        low = ''.join(ch.lower() for ch in (text or '') if ch.isalnum() or ch.isspace()).strip()
        tokens = [t for t in low.split() if len(t) > 2]
        stop = {"пансионат", "гостевой", "гостевая", "дом", "гостиница", "отель", "санаторий", "база", "отдыха"}
        return [t for t in tokens if t not in stop]

    def _extract_url_from_meta(self, meta: Dict[str, Any]) -> Optional[str]:
        # Прямое поле
        url = (meta.get('url') or meta.get('URL') or '').strip()
        if url:
            return url
        # Возможные альтернативные поля/контейнеры
        for key in ('Links', 'links', 'site', 'website', 'webSite', 'web', 'sites'):
            val = meta.get(key)
            if isinstance(val, str) and val.startswith('http'):
                return val.strip()
            if isinstance(val, dict):
                # Популярные варианты: { main: '...', ... }
                for subk in ('main', 'primary', 'official', 'site', 'url'):
                    v = val.get(subk)
                    if isinstance(v, str) and v.startswith('http'):
                        return v.strip()
                # Или перебор всех вложенных строк
                for v in val.values():
                    if isinstance(v, str) and v.startswith('http'):
                        return v.strip()
                    if isinstance(v, list):
                        for it in v:
                            if isinstance(it, str) and it.startswith('http'):
                                return it.strip()
                            if isinstance(it, dict):
                                for vv in it.values():
                                    if isinstance(vv, str) and vv.startswith('http'):
                                        return vv.strip()
            if isinstance(val, list):
                for it in val:
                    if isinstance(it, str) and it.startswith('http'):
                        return it.strip()
                    if isinstance(it, dict):
                        for vv in it.values():
                            if isinstance(vv, str) and vv.startswith('http'):
                                return vv.strip()
        return None

    def _get_bbox(self, location: str) -> Optional[str]:
        """Возвращает bbox в формате lon1,lat1~lon2,lat2 для Яндекс API по данным Nominatim."""
        try:
            if not location:
                return None
            headers = {'User-Agent': 'ResortContactsCollector/1.0 (bbox)'}
            resp = self.session.get('https://nominatim.openstreetmap.org/search', params={'q': location, 'format': 'json', 'limit': 1}, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            bbox = data[0].get('boundingbox')
            if not bbox or len(bbox) != 4:
                return None
            south, north, west, east = bbox  # lat_s, lat_n, lon_w, lon_e
            # Яндекс ждёт lon1,lat1~lon2,lat2
            return f"{west},{south}~{east},{north}"
        except Exception:
            return None

    def find_website(self, name: str, location: str, aggregator_domains: Optional[List[str]] = None) -> Optional[str]:
        if not self._is_enabled():
            self.last_debug = ["YANDEX API KEY missing"]
            self.last_status_code = None
            self.last_error = 'no_key'
            return None
        try:
            self.last_debug = []
            self.last_status_code = None
            self.last_error = ''
            queries = [f"{name} {location}"]
            expanded = self._expand_abbreviations(name)
            if expanded.lower() != (name or '').lower():
                queries.append(f"{expanded} {location}")

            norm_loc = ''.join(ch.lower() for ch in (location or '') if ch.isalnum() or ch.isspace()).strip()
            name_tokens = self._name_tokens(expanded)
            bbox = self._get_bbox(location)
            if bbox:
                self.last_debug.append(f"bbox resolved: {bbox}")

            for q in queries:
                params = {
                    'apikey': self.api_key,
                    'text': q,
                    'type': 'biz',
                    'lang': 'ru_RU',
                    'results': 30,
                }
                if bbox:
                    params['bbox'] = bbox
                    params['rspn'] = 1
                self.last_debug.append(f"query: {q} (with bbox={bool(bbox)})")
                try:
                    resp = self.session.get(self.base_url, params=params, timeout=15)
                    self.last_status_code = resp.status_code
                    resp.raise_for_status()
                except Exception as e:
                    # Сохраним детали и попробуем без bbox, если был
                    self.last_error = str(e)
                    self.last_debug.append(f"error: {e}")
                    if params.get('bbox'):
                        try:
                            p2 = dict(params)
                            p2.pop('bbox', None)
                            p2.pop('rspn', None)
                            self.last_debug.append("retry without bbox")
                            r2 = self.session.get(self.base_url, params=p2, timeout=15)
                            self.last_status_code = r2.status_code
                            r2.raise_for_status()
                            resp = r2
                        except Exception as e2:
                            self.last_error = str(e2)
                            self.last_debug.append(f"error2: {e2}")
                            continue
                data = resp.json()
                feats = data.get('features') or []
                self.last_debug.append(f"features: {len(feats)}")
                for f in feats:
                    props = (f.get('properties') or {})
                    meta = (props.get('CompanyMetaData') or {})
                    url = self._extract_url_from_meta(meta) or ''
                    if not url:
                        self.last_debug.append("no url in meta, skip")
                        continue
                    rd = self._root_domain(url)
                    if aggregator_domains and rd in aggregator_domains:
                        self.last_debug.append(f"skip aggregator: {url}")
                        continue
                    # Проверка адреса и названия в карточке
                    addr = (meta.get('address') or '').lower()
                    norm_addr = ''.join(ch for ch in addr if ch.isalnum() or ch.isspace()).strip()
                    meta_name = (meta.get('name') or props.get('name') or '').lower()
                    # Условие соответствия: либо адрес содержит город, либо в названии/URL встречаются важные токены
                    good_by_location = bool(norm_loc and norm_loc in norm_addr)
                    good_by_name = any(t in meta_name or t in url.lower() for t in name_tokens) if name_tokens else False
                    if good_by_location or good_by_name:
                        self.last_debug.append(f"picked: {url}")
                        return url
            return None
        except Exception as e:
            self.last_debug.append(f"error: {e}")
            return None


# Глобальный экземпляр Яндекс‑поиска
yandex_search = YandexOrgSearch()


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
        # Таймауты
        self.overpass_timeout_s = 15
        self.nominatim_timeout_s = 10

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
                resp = self.session.post(url, data={"data": query}, timeout=self.overpass_timeout_s)
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
            resp = self.session.get(url, params=params, timeout=self.nominatim_timeout_s)
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
            resp = self.session.get(url, params=params, timeout=self.nominatim_timeout_s)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
        except Exception as e:
            logger.warning(f"Nominatim center error: {e}")
            return None

    def find_accommodation_names(self, city: str, limit: int = 200, max_duration_s: int = 35) -> List[str]:
        """Возвращает список названий объектов размещения в городе."""
        if not city or len(city.strip()) < 2:
            return []

        deadline = time.time() + max_duration_s

        # 1) Пытаемся через область города в Overpass
        query_area = self._overpass_query_by_area(city.strip())
        names = self._fetch_overpass(query_area)
        if time.time() > deadline:
            return list(dict.fromkeys([n.strip() for n in names if n.strip()]))[: limit or None]

        # 2) Если ничего не нашли — пробуем по bbox города через Nominatim
        if not names:
            bbox = self._geocode_city_bbox(city.strip())
            if bbox:
                query_bbox = self._overpass_query_by_bbox(bbox)
                names = self._fetch_overpass(query_bbox)
        if time.time() > deadline:
            return list(dict.fromkeys([n.strip() for n in names if n.strip()]))[: limit or None]

        # 3) Если все еще пусто — ищем вокруг геоцентра города на растущем радиусе
        if not names:
            center = self._geocode_city_center(city.strip())
            if center:
                for radius in [3000, 7000, 15000, 25000]:
                    if time.time() > deadline:
                        break
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
