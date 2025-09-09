import requests
import json
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

    def get_raw_html(self, url: str) -> Optional[str]:
        """Возвращает сырой HTML страницы без очистки."""
        try:
            self.session.headers.update({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': url
            })
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            return resp.text
        except Exception as e:
            logger.error(f"Ошибка получения HTML {url}: {e}")
            return None

    def extract_emails(self, text: str) -> list:
        """Извлечение email адресов из текста"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        return list(set(emails))  # Убираем дубликаты

    def extract_emails_from_html(self, html: str) -> list:
        """Извлечение email из mailto и JSON-LD в HTML."""
        if not html:
            return []
        emails: set = set()
        try:
            soup = BeautifulSoup(html, 'html.parser')
            # mailto:
            for a in soup.find_all('a', href=True):
                href = a.get('href') or ''
                if href.lower().startswith('mailto:'):
                    addr = href.split(':', 1)[1]
                    addr = addr.split('?', 1)[0]
                    from urllib.parse import unquote as _unquote
                    addr = _unquote(addr)
                    addr = addr.strip()
                    if addr:
                        emails.add(addr)
            # JSON-LD blocks
            for sc in soup.find_all('script'):
                t = (sc.get('type') or '').lower()
                if 'ld+json' in t and sc.string:
                    try:
                        data = json.loads(sc.string)
                    except Exception:
                        continue
                    # рекурсивный обход
                    stack = [data]
                    while stack:
                        node = stack.pop()
                        if isinstance(node, dict):
                            for k, v in node.items():
                                if isinstance(v, (dict, list)):
                                    stack.append(v)
                                elif isinstance(v, str) and '@' in v:
                                    for m in re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', v):
                                        emails.add(m)
                        elif isinstance(node, list):
                            for it in node:
                                stack.append(it)
        except Exception as e:
            logger.warning(f"extract_emails_from_html failed: {e}")
        return list(emails)

    def extract_postal_addresses_from_jsonld(self, html: str) -> list:
        """Достаёт адреса из JSON-LD (schema.org PostalAddress) и склеивает в строку."""
        if not html:
            return []
        out: list = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for sc in soup.find_all('script'):
                t = (sc.get('type') or '').lower()
                if 'ld+json' not in t or not sc.string:
                    continue
                try:
                    data = json.loads(sc.string)
                except Exception:
                    continue
                stack = [data]
                while stack:
                    node = stack.pop()
                    if isinstance(node, dict):
                        atype = (node.get('@type') or node.get('type') or '')
                        if isinstance(atype, list):
                            atype = ' '.join(atype)
                        if isinstance(atype, str) and 'postaladdress' in atype.lower():
                            parts = []
                            for key in ['postalCode','addressCountry','addressRegion','addressLocality','streetAddress']:
                                val = node.get(key)
                                if isinstance(val, str) and val.strip():
                                    parts.append(val.strip())
                            addr = ', '.join(parts)
                            if addr:
                                out.append(addr)
                        for v in node.values():
                            if isinstance(v, (dict, list)):
                                stack.append(v)
                    elif isinstance(node, list):
                        for it in node:
                            stack.append(it)
        except Exception as e:
            logger.warning(f"extract_postal_addresses_from_jsonld failed: {e}")
        # дедуп
        uniq = []
        seen = set()
        for a in out:
            if a in seen:
                continue
            seen.add(a)
            uniq.append(a)
        return uniq
    
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
        # Уточнённые паттерны для российских адресов (улица/дом), допускаем префиксы города/края
        address_patterns = [
            r'(?:г\.?\s*[А-ЯЁа-яё\-\s]+,\s*)?(?:[А-ЯЁа-яё\-\s]+,\s*)?(?:ул\.|улица|просп\.|проспект|пер\.|переулок|шоссе|наб\.|набережная|бульвар|б\-р|проезд)\s+[А-ЯЁа-яё0-9\-\s]+,?\s*(?:д\.|дом)?\s*\d+[А-Яа-яA-Za-z0-9\-\/]*',
            r'(?:край|область|респ\.|республика|г\.|город)\s*[А-ЯЁа-яё\-\s]+,\s*[А-ЯЁа-яё\-\s]+,\s*\d+[А-Яа-яA-Za-z0-9\-\/]*',
        ]
        
        addresses: list = []
        for pattern in address_patterns:
            try:
                found = re.findall(pattern, text)
                for a in found:
                    s = a.strip()
                    if '@' in s:
                        continue
                    if 8 <= len(s) <= 200:
                        addresses.append(s)
            except Exception:
                continue
        
        # Убираем дубликаты, сохраняя порядок
        uniq = []
        seen = set()
        for a in addresses:
            if a in seen:
                continue
            seen.add(a)
            uniq.append(a)
        return uniq

    def extract_addresses_from_html(self, html: str) -> list:
        """Ищет адреса в HTML рядом с метками 'Адрес'/'Address'."""
        if not html:
            return []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            texts = []
            # элементы, где явно встречается слово 'Адрес'
            cand = soup.find_all(string=lambda t: isinstance(t, str) and 'адрес' in t.lower())
            for t in cand:
                # текущий и соседние элементы
                node = t.parent
                ctx = [node.get_text(" ", strip=True)]
                prev = node.find_previous(string=True)
                if prev:
                    ctx.append(prev.strip())
                nxt = node.find_next(string=True)
                if nxt:
                    ctx.append(nxt.strip())
                for piece in ctx:
                    if piece and len(piece) <= 240:
                        texts.append(piece)
            # Если нет меток — ничего не отдаём (чтобы не ловить мусор)
            acc = []
            for snippet in texts:
                # вытащим из кусочков по regex
                for a in self.extract_addresses(snippet):
                    acc.append(a)
            # Дедуп
            uniq = []
            seen = set()
            for a in acc:
                if a in seen:
                    continue
                seen.add(a)
                uniq.append(a)
            return uniq
        except Exception as e:
            logger.warning(f"extract_addresses_from_html failed: {e}")
            return []
    
    def clean_text(self, text: str) -> str:
        """Очистка текста от лишних символов"""
        if not text:
            return ""
        
        # Удаление лишних пробелов
        text = re.sub(r'\s+', ' ', text)
        
        # Удаление специальных символов, но сохраняем символы важные для e-mail/URL: @ + : / ;
        # Также сохраняем дефис/точку/скобки/запятые/воскл/вопр для адресов
        text = re.sub(r'[^\w\s@+\-\.,!?():/;]', '', text)
        
        # Ограничение длины
        if len(text) > 5000:
            text = text[:5000] + "..."
        
        return text.strip()

class ContactExtractor:
    """Класс для извлечения контактной информации"""
    
    def __init__(self):
        self.scraper = WebScraper()
    
    def _normalize_email_words(self, text: str) -> str:
        """Заменяет обфускации вида (at)/(dot)/[at]/[dot]/'собака'/'точка' на @ и ."""
        if not text:
            return ''
        s = text
        # унификация пробелов
        s = re.sub(r'\s+', ' ', s)
        # английские варианты
        patterns = [
            (r'\b\(\s*at\s*\)|\[\s*at\s*\]|\s+at\s+|\s*\{\s*at\s*\}\s*', '@'),
            (r'\b\(\s*dot\s*\)|\[\s*dot\s*\]|\s+dot\s+|\s*\{\s*dot\s*\}\s*', '.'),
        ]
        # русские варианты
        patterns += [
            (r'\bсобак[а-я]\b', '@'),
            (r'\bточк[а-я]\b', '.'),
        ]
        for pat, repl in patterns:
            try:
                s = re.sub(pat, repl, s, flags=re.IGNORECASE)
            except Exception:
                pass
        return s
    
    def extract_contacts_from_text(self, text: str) -> Dict[str, Any]:
        """Извлечение всех типов контактов из текста"""
        if not text:
            return {}
        
        cleaned_text = self.scraper.clean_text(text)
        normalized_text = self._normalize_email_words(cleaned_text)
        
        return {
            'emails': self.scraper.extract_emails(normalized_text),
            'phones': self.scraper.extract_phones(cleaned_text),
            'coordinates': self.scraper.extract_coordinates(cleaned_text),
            'addresses': self.scraper.extract_addresses(cleaned_text),
            'cleaned_text': cleaned_text
        }
    
    def extract_contacts_from_url(self, url: str) -> Dict[str, Any]:
        """Извлечение контактов с веб-страницы"""
        content = self.scraper.get_page_content(url)
        html = self.scraper.get_raw_html(url) or ''
        data_from_text = self.extract_contacts_from_text(content or '') if content else {}
        emails_from_html = self.scraper.extract_emails_from_html(html)
        addrs_from_html = self.scraper.extract_addresses_from_html(html)
        addrs_from_jsonld = self.scraper.extract_postal_addresses_from_jsonld(html)
        # объединяем
        emails = set(data_from_text.get('emails', [])) if data_from_text else set()
        for e in emails_from_html:
            emails.add(e)
        addresses = list(data_from_text.get('addresses', [])) if data_from_text else []
        # приоритет адресов из JSON-LD и HTML-меток
        for a in addrs_from_jsonld:
            if a not in addresses:
                addresses.insert(0, a)
        for a in addrs_from_html:
            if a not in addresses:
                addresses.insert(0, a)
        result = dict(data_from_text) if data_from_text else {}
        result['emails'] = list(emails)
        result['addresses'] = addresses
        return result
    
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

    def find_contacts(self, name: str, location: str) -> Tuple[Optional[str], Optional[str], List[str]]:
        """Ищет контакты (email и адрес) напрямую в карточках Яндекс организаций."""
        logs: List[str] = []
        email = None
        address = None
        
        if not self._is_enabled():
            logs.append("YANDEX API KEY missing")
            return email, address, logs
            
        try:
            queries = [f"{name} {location}"]
            expanded = self._expand_abbreviations(name)
            if expanded.lower() != (name or '').lower():
                queries.append(f"{expanded} {location}")

            norm_loc = ''.join(ch.lower() for ch in (location or '') if ch.isalnum() or ch.isspace()).strip()
            name_tokens = self._name_tokens(expanded)
            bbox = self._get_bbox(location)
            
            logs.append(f"Поиск контактов для '{name}' в '{location}'")

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
                    
                logs.append(f"Запрос: {q}")
                try:
                    resp = self.session.get(self.base_url, params=params, timeout=15)
                    resp.raise_for_status()
                except Exception as e:
                    logs.append(f"Ошибка запроса: {e}")
                    continue
                    
                data = resp.json()
                feats = data.get('features') or []
                logs.append(f"Найдено организаций: {len(feats)}")
                
                for f in feats:
                    props = (f.get('properties') or {})
                    meta = (props.get('CompanyMetaData') or {})
                    
                    # Проверяем соответствие организации
                    addr = (meta.get('address') or '').lower()
                    norm_addr = ''.join(ch for ch in addr if ch.isalnum() or ch.isspace()).strip()
                    meta_name = (meta.get('name') or props.get('name') or '').lower()
                    
                    good_by_location = bool(norm_loc and norm_loc in norm_addr)
                    good_by_name = any(t in meta_name for t in name_tokens) if name_tokens else False
                    
                    if good_by_location or good_by_name:
                        logs.append(f"Найдена подходящая организация: {meta.get('name', 'Без названия')}")
                        
                        # Извлекаем адрес
                        if addr:
                            address = addr
                            logs.append(f"Адрес из Яндекс: {address}")
                        
                        # Ищем email в CompanyMetaData
                        email_fields = ['email', 'Email', 'EMAIL', 'mail', 'Mail', 'MAIL', 'contact', 'Contact', 'CONTACT']
                        
                        # Сначала проверим основные поля
                        for field in email_fields:
                            email_val = meta.get(field)
                            if email_val and '@' in email_val:
                                email = email_val.strip()
                                logs.append(f"Email из Яндекс ({field}): {email}")
                                break
                        
                        # Если не нашли, проверим все поля на наличие @
                        if not email:
                            logs.append("Проверяем все поля CompanyMetaData на наличие email...")
                            for key, value in meta.items():
                                if isinstance(value, str) and '@' in value and '.' in value:
                                    # Проверяем, что это похоже на email
                                    if len(value.split('@')) == 2 and len(value.split('@')[1].split('.')) >= 2:
                                        email = value.strip()
                                        logs.append(f"Email найден в поле '{key}': {email}")
                                        break
                        
                        # Если все еще не нашли, проверим другие части ответа
                        if not email:
                            logs.append("Проверяем другие части ответа Яндекс...")
                            # Проверяем properties
                            for key, value in props.items():
                                if isinstance(value, str) and '@' in value and '.' in value:
                                    if len(value.split('@')) == 2 and len(value.split('@')[1].split('.')) >= 2:
                                        email = value.strip()
                                        logs.append(f"Email найден в properties['{key}']: {email}")
                                        break
                        
                        # Если все еще не нашли, выведем все доступные поля для отладки
                        if not email:
                            logs.append("Доступные поля в CompanyMetaData:")
                            for key, value in meta.items():
                                if isinstance(value, str) and len(value) < 100:  # Только короткие строки
                                    logs.append(f"  {key}: {value}")
                            
                            logs.append("Доступные поля в properties:")
                            for key, value in props.items():
                                if isinstance(value, str) and len(value) < 100:  # Только короткие строки
                                    logs.append(f"  {key}: {value}")
                        
                        # Если нашли хотя бы один контакт - возвращаем
                        if email or address:
                            logs.append(f"Контакты найдены: email={email}, address={address}")
                            return email, address, logs
                            
            logs.append("Контакты в Яндекс карточках не найдены")
            return email, address, logs
            
        except Exception as e:
            logs.append(f"Ошибка поиска контактов: {e}")
            return email, address, logs


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


# =========================
# Контактный краулер сайта
# =========================

class TextExtractorAgent:
    """Агент для извлечения чистого текста с сайта."""
    
    def __init__(self):
        self.scraper = scraper
    
    def extract_text_from_site(self, base_url: str, max_pages: int = 12, max_depth: int = 2) -> Tuple[str, List[str]]:
        """Извлекает весь текстовый контент с сайта."""
        logs: List[str] = []
        all_text_parts = []
        
        try:
            if not base_url or not base_url.startswith(('http://', 'https://')):
                logs.append("⚠️ Пустой или некорректный URL сайта")
                return "", logs
                
            parsed = urlparse(base_url)
            base_netloc = parsed.netloc
            
            # Очередь URL для обхода
            from collections import deque
            queue = deque()
            visited = set()

            def enqueue(u: str, depth: int):
                if (u, depth) in visited:
                    return
                if not self._same_scope(base_netloc, u):
                    return
                visited.add((u, depth))
                queue.append((u, depth))

            # Стартовые точки: главная и типичные контактные страницы
            base = f"{parsed.scheme}://{parsed.netloc}"
            start_candidates = [base_url, urljoin(base, '/contacts'), urljoin(base, '/contact'), urljoin(base, '/контакты'), urljoin(base, '/about')]
            seen_seed = set()
            for s in start_candidates:
                if s in seen_seed:
                    continue
                seen_seed.add(s)
                enqueue(s, 0)

            pages_scanned = 0
            while queue and pages_scanned < max_pages:
                url, depth = queue.popleft()
                pages_scanned += 1
                logs.append(f"📄 Извлекаем текст: {url} (глубина {depth})")
                
                text = self.scraper.get_page_content(url) or ''
                if text:
                    all_text_parts.append(text)
                    logs.append(f"✅ Получено {len(text)} символов с {url}")

                # Расширяем обход
                if depth < max_depth:
                    links = self.scraper.get_links(url, max_links=20)
                    # приоритезируем контактные
                    links_sorted = sorted(links, key=lambda l: (0 if self._is_contact_like(urlparse(l).path) else 1, len(l)))
                    for l in links_sorted:
                        if self._same_scope(base_netloc, l):
                            enqueue(l, depth + 1)

            # Объединяем весь текст
            combined_text = '\n\n'.join(all_text_parts)
            logs.append(f"📊 Итого извлечено: {len(combined_text)} символов с {pages_scanned} страниц")
            return combined_text, logs
            
        except Exception as e:
            logs.append(f"❌ Ошибка извлечения текста: {e}")
            return "", logs
    
    def _root_domain(self, host: str) -> str:
        try:
            netloc = host.lower()
            if netloc.startswith('www.'):
                netloc = netloc[4:]
            parts = netloc.split('.')
            if len(parts) >= 2:
                return '.'.join(parts[-2:])
            return netloc
        except Exception:
            return ''

    def _same_scope(self, base_netloc: str, candidate_url: str) -> bool:
        try:
            cand = urlparse(candidate_url)
            if cand.scheme not in ('http', 'https'):
                return False
            base_rd = self._root_domain(base_netloc)
            cand_rd = self._root_domain(cand.netloc)
            return bool(base_rd and cand_rd and base_rd == cand_rd)
        except Exception:
            return False

    def _is_contact_like(self, url_path: str) -> bool:
        low = (url_path or '').lower()
        keys = ['contact', 'contacts', 'kontact', 'kontakty', 'контакт', 'контакты', 'about', 'о-компании', 'o-kompanii', 'o-kompany', 'о_компании', 'o-nas', 'о нас']
        return any(k in low for k in keys)


class ContactFinderAgent:
    """Агент для поиска контактов в тексте с помощью LLM."""
    
    def __init__(self):
        pass
    
    def find_contacts_in_text(self, proxy_client, text: str, location: str) -> Tuple[Optional[str], Optional[str], str]:
        """Ищет контакты в тексте с помощью LLM."""
        logger.info(f"🤖 ContactFinderAgent: начинаем поиск в тексте длиной {len(text)} символов")
        try:
            if not proxy_client:
                logger.warning("🤖 ContactFinderAgent: proxy_client отсутствует")
                return None, None, ''
            
            # Разбиваем текст на части для лучшего анализа
            text_length = len(text)
            if text_length <= 4000:
                text_parts = [text]
            else:
                # Разбиваем на конец и начало (конец приоритетнее)
                start_part = text[:4000]
                end_part = text[-4000:] if text_length > 4000 else text[4000:]
                text_parts = [end_part, start_part]
            
            prompt_template = (
                "ТЫ ДОЛЖЕН НАЙТИ e-mail и адрес организации в тексте ниже. БУДЬ ОЧЕНЬ ВНИМАТЕЛЬНЫМ!\n"
                "ИНСТРУКЦИИ:\n"
                "1. ИЩИ email ВЕЗДЕ: в футере, контактах, формах, боковых панелях, даже в мелком тексте\n"
                "2. ИЩИ адрес ВЕЗДЕ: полный адрес, город+регион, или просто город\n"
                "3. Email должен содержать @ и домен (например: info@hotel.ru, booking@resort.com)\n"
                "4. Адрес может быть любой длины: от 'г. Сочи' до полного адреса с улицей\n"
                "5. Если видишь телефон рядом с контактами - игнорируй телефон, бери только email/адрес\n"
                "6. Если данные слиты (например '79284134067Emailsvtkolom@yandex.ru') - раздели их\n"
                "7. НЕ ПРОПУСКАЙ НИЧЕГО! Проверь весь текст внимательно\n"
                "8. Если нашел хотя бы один контакт - обязательно верни его\n"
                "\n"
                "Верни строго JSON: {{\"email\": \"найденный_email\", \"address\": \"найденный_адрес\"}}\n"
                "Если ничего не найдено: {{\"email\": \"\", \"address\": \"\"}}\n\n"
                "ТЕКСТ ДЛЯ АНАЛИЗА:\n{text_part}"
            )
            
            import asyncio as _asyncio
            
            logger.info(f"🤖 ContactFinderAgent: разбили текст на {len(text_parts)} частей")
            
            # Анализируем каждую часть текста
            logger.info(f"🤖 ContactFinderAgent: начинаем цикл анализа {len(text_parts)} частей")
            for i, text_part in enumerate(text_parts):
                logger.info(f"🤖 ContactFinderAgent: обрабатываем часть {i+1}/{len(text_parts)}, длина: {len(text_part)} символов")
                prompt = prompt_template.format(text_part=text_part)
                logger.info(f"🤖 Отправляем запрос к LLM (часть {i+1}/{len(text_parts)})...")
                try:
                    # Используем существующий ProxyAPIClient
                    import asyncio as _asyncio
                    
                    logger.info(f"🤖 Отправляем запрос к LLM через ProxyAPIClient...")
                    resp = _asyncio.run(proxy_client.chat_completion(
                        model='claude-3-5-sonnet-20240620',
                        messages=[{'role': 'user', 'content': prompt}],
                        max_tokens=500,
                        temperature=0.1
                    ))
                    logger.info(f"🤖 LLM запрос выполнен успешно")
                        
                except Exception as e:
                    logger.warning(f"Ошибка LLM запроса: {e}")
                    continue
                content = resp["choices"][0]["message"]["content"] if isinstance(resp, dict) else ""
                logger.info(f"🤖 LLM ответ: {content[:200]}...")
                
                try:
                    logger.info(f"🤖 Пытаемся распарсить JSON: {content[:100]}...")
                    data = json.loads(content)
                    raw_email = (data.get('email') or '').strip()
                    raw_addr = (data.get('address') or '').strip()
                    
                    # Если нашли контакты в этой части - возвращаем их
                    if raw_email or raw_addr:
                        # Санитизация
                        email = None
                        if raw_email:
                            ems = contact_extractor.scraper.extract_emails(raw_email)
                            email = ems[0] if ems else None
                        address = None
                        if raw_addr:
                            ads = contact_extractor.scraper.extract_addresses(raw_addr)
                            address = ads[0] if ads else (raw_addr if len(raw_addr) >= 3 else None)
                        
                        # Добавляем информацию о том, в какой части нашли
                        part_info = f" (часть {i+1})" if len(text_parts) > 1 else ""
                        content_with_info = content + part_info
                        
                        return (email or None), (address or None), content_with_info
                except Exception:
                    continue
            
            # Если ни в одной части не нашли контакты
            return None, None, "Контакты не найдены ни в одной части текста"
            
        except Exception as e:
            logger.warning(f"ContactFinderAgent error: {e}")
            logger.warning(f"🤖 Полный текст для анализа: {text[:500]}...")
            return None, None, ''


class ContactsCrawler:
    """Обход сайта и извлечение e-mail и почтовых адресов с использованием двух агентов.

    - TextExtractorAgent извлекает чистый текст с сайта
    - ContactFinderAgent ищет контакты в тексте с помощью LLM
    """

    def __init__(self):
        self.text_extractor = TextExtractorAgent()
        self.contact_finder = ContactFinderAgent()

    def _root_domain(self, host: str) -> str:
        try:
            netloc = host.lower()
            if netloc.startswith('www.'):
                netloc = netloc[4:]
            parts = netloc.split('.')
            if len(parts) >= 2:
                return '.'.join(parts[-2:])
            return netloc
        except Exception:
            return ''

    def _same_scope(self, base_netloc: str, candidate_url: str) -> bool:
        try:
            cand = urlparse(candidate_url)
            if cand.scheme not in ('http', 'https'):
                return False
            base_rd = self._root_domain(base_netloc)
            cand_rd = self._root_domain(cand.netloc)
            return bool(base_rd and cand_rd and base_rd == cand_rd)
        except Exception:
            return False

    def _is_contact_like(self, url_path: str) -> bool:
        low = (url_path or '').lower()
        keys = ['contact', 'contacts', 'kontact', 'kontakty', 'контакт', 'контакты', 'about', 'о-компании', 'o-kompanii', 'o-kompany', 'о_компании', 'o-nas', 'о нас']
        return any(k in low for k in keys)



    def extract_from_site(self,
                          base_url: str,
                          location: str,
                          *,
                          allow_subdomains: bool = True,
                          max_pages: int = 12,
                          max_depth: int = 2,
                          proxy_client: Optional[object] = None) -> Tuple[Dict[str, str], List[str]]:
        """Извлекает контакты с сайта используя двухагентную архитектуру."""
        logs: List[str] = []
        result: Dict[str, str] = {"email": "", "address": ""}
        
        try:
            if not base_url or not base_url.startswith(('http://', 'https://')):
                logs.append("⚠️ Пустой или некорректный URL сайта")
                return result, logs
            
            logs.append(f"🚀 Начинаем извлечение контактов с {base_url}")
            
            # Шаг 0: Сначала пытаемся найти контакты в Яндекс карточках
            logs.append("🔍 Этап 0: Поиск контактов в Яндекс карточках...")
            yandex_email, yandex_address, yandex_logs = yandex_search.find_contacts(base_url, location)
            logs.extend(yandex_logs)
            
            # Яндекс нашел адрес - сохраняем его, но продолжаем искать email через LLM
            if yandex_address:
                logs.append(f"✅ Адрес найден в Яндекс: {yandex_address}")
                result['address'] = yandex_address
            
            # Если Яндекс нашел email - используем его, иначе ищем через LLM
            if yandex_email:
                logs.append(f"✅ Email найден в Яндекс: {yandex_email}")
                result['email'] = yandex_email
                # Если нашли и email и адрес в Яндекс - возвращаемся
                if yandex_address:
                    return result, logs
            
            # Шаг 1: TextExtractorAgent извлекает весь текст с сайта
            logs.append("📄 Этап 1: Извлечение текста с сайта...")
            extracted_text, extract_logs = self.text_extractor.extract_text_from_site(base_url, max_pages, max_depth)
            logs.extend(extract_logs)
            
            if not extracted_text:
                logs.append("❌ Не удалось извлечь текст с сайта")
                return result, logs
            
            logs.append(f"✅ Текст извлечен: {len(extracted_text)} символов")
            
            # Шаг 2: ContactFinderAgent ищет email в тексте (если еще не найден)
            if proxy_client and not result.get('email'):
                logs.append("🤖 Этап 2: Поиск email в тексте с помощью LLM...")
                logs.append(f"🤖 ProxyClient доступен: {type(proxy_client)}")
                email, address, raw_response = self.contact_finder.find_contacts_in_text(proxy_client, extracted_text, location)
                
                # Используем email от LLM только если Яндекс его не нашел
                if email:
                    result['email'] = email
                    logs.append(f"🤖 LLM нашел email: {email}")
                else:
                    logs.append("🤖 LLM не нашел email в тексте")
                
                if raw_response:
                    logs.append(f"🤖 LLM ответ: {raw_response[:200]}")
            elif result.get('email'):
                logs.append("✅ Email уже найден в Яндекс, пропускаем LLM")
            else:
                logs.append("❌ ProxyClient недоступен, пропускаем LLM")
            
            logs.append(f"✅ Итог: email='{result['email'] or '—'}', address='{(result['address'] or '—')[:80]}'")
            return result, logs
            
        except Exception as e:
            logs.append(f"❌ Ошибка извлечения контактов: {e}")
            return result, logs


# Глобальный экземпляр краулера
contacts_crawler = ContactsCrawler()
