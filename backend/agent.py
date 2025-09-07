import json
import logging
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import urlparse, urljoin

try:
    # Запуск из директории backend (python backend/main.py)
    from utils import contact_extractor, scraper, web_search, yandex_search
except ImportError:
    # Запуск как пакет (uvicorn backend.main:app)
    from backend.utils import contact_extractor, scraper, web_search, yandex_search

logger = logging.getLogger(__name__)


class ContactAgent:
    """Простой псевдоагент (ReAct-стиль): планирование → действие (инструмент) → наблюдение → рефлексия.

    Инструменты:
    - fetch_url: скачать страницу по URL и извлечь контакты
    - extract_from_text: извлечь контакты из предоставленного текста
    - finalize: вернуть итоговый JSON с контактами
    """

    def __init__(self, proxy_client, model: str = "claude-3-5-sonnet-20240620", max_steps: int = 6):
        self.proxy_client = proxy_client
        self.model = model
        self.max_steps = max_steps

    async def run(self, location: str) -> Tuple[List[Dict[str, str]], List[str]]:
        logs: List[str] = []
        scratchpad: List[Dict[str, Any]] = []
        collected_contacts: List[Dict[str, str]] = []

        system_spec = (
            "Ты — агент по сбору контактов отелей/баз отдыха/санаториев."
            " У тебя есть инструменты: fetch_url, extract_from_text, finalize."
            " Всегда отвечай строго JSON в формате: {\n"
            "  \"action\": \"fetch_url|extract_from_text|finalize\",\n"
            "  \"input\": string или объект,\n"
            "  \"reason\": string\n"
            "}. Без лишнего текста."
        )

        def build_messages() -> List[Dict[str, str]]:
            context = {
                "goal": f"Собрать контакты мест размещения в {location}.",
                "tools": [
                    {"name": "fetch_url", "args": "{url}", "desc": "скачать страницу и извлечь контакты"},
                    {"name": "extract_from_text", "args": "{text}", "desc": "извлечь контакты из текста"},
                    {"name": "finalize", "args": "—", "desc": "вернуть итоговый JSON с контактами"},
                ],
                "history": scratchpad,
            }
            user_prompt = (
                "Контекст:\n" + json.dumps(context, ensure_ascii=False, indent=2) +
                "\nСделай следующий наилучший шаг."
            )
            return [
                {"role": "user", "content": system_spec + "\n\n" + user_prompt},
            ]

        for step in range(1, self.max_steps + 1):
            logs.append(f"🤔 Шаг агента {step}: планирование")
            messages = build_messages()
            try:
                resp = await self.proxy_client.chat_completion(
                    model=self.model,
                    messages=messages,
                    max_tokens=800,
                    temperature=0.2,
                )
                content = resp["choices"][0]["message"]["content"]
                logs.append(f"🧠 План: {content[:200]}...")
                try:
                    decision = json.loads(content)
                except Exception:
                    logs.append("⚠️ Агент вернул не-JSON. Повтор шага.")
                    scratchpad.append({"thought": content})
                    continue

                action = (decision.get("action") or "").strip()
                action_input = decision.get("input")
                reason = decision.get("reason") or ""
                scratchpad.append({"action": action, "input": action_input, "reason": reason})

                if action == "fetch_url":
                    url = (action_input or "").strip()
                    if not url:
                        logs.append("⚠️ Пустой URL у действия fetch_url")
                        continue
                    logs.append(f"🌐 fetch_url: {url}")
                    # Используем ContactExtractor для первичного извлечения
                    try:
                        page_data = contact_extractor.extract_contacts_from_url(url)
                        logs.append(f"🔎 Результат извлечения: {str(page_data)[:200]}...")
                        # Преобразуем в кандидатов контактов (пока только email/адреса)
                        new_candidates = self._contacts_from_extraction(page_data)
                        collected_contacts.extend(new_candidates)
                        scratchpad.append({"observation": {"extracted": page_data, "new_contacts": new_candidates}})
                    except Exception as e:
                        logs.append(f"❌ Ошибка fetch_url: {e}")
                        scratchpad.append({"observation": {"error": str(e)}})

                elif action == "extract_from_text":
                    text = action_input if isinstance(action_input, str) else json.dumps(action_input, ensure_ascii=False)
                    logs.append(f"📝 extract_from_text: {text[:200]}...")
                    extracted = contact_extractor.extract_contacts_from_text(text)
                    new_candidates = self._contacts_from_extraction(extracted)
                    collected_contacts.extend(new_candidates)
                    scratchpad.append({"observation": {"extracted": extracted, "new_contacts": new_candidates}})

                elif action == "finalize":
                    logs.append("✅ Финализация агентом")
                    # Отдаем агрегированные, уникализированные контакты
                    final_contacts = self._dedupe_contacts(collected_contacts)
                    return final_contacts, logs

                else:
                    logs.append(f"⚠️ Неизвестное действие агента: {action}")
                    continue

                # Если после действия ничего не найдено — обходим ссылки на странице (если это URL)
                if action == "fetch_url" and isinstance(action_input, str):
                    base_url = action_input
                    links = scraper.get_links(base_url, max_links=10)
                    if links:
                        logs.append(f"🔗 Найдены ссылки для обхода ({len(links)}): {links[:5]}...")
                        for link in links[:5]:
                            page_data = contact_extractor.extract_contacts_from_url(link)
                            new_candidates = self._contacts_from_extraction(page_data)
                            if new_candidates:
                                # попробуем получить заголовок как имя
                                name = scraper.get_title(link)
                                for nc in new_candidates:
                                    if not nc.get('name'):
                                        nc['name'] = name
                                collected_contacts.extend(new_candidates)
                        scratchpad.append({"observation": {"crawled_links": len(links), "collected": len(collected_contacts)}})

            except Exception as e:
                logs.append(f"❌ Ошибка шага агента: {e}")
                continue

        # Хард-стоп: возвращаем, что нашли
        logs.append("⏹ Достигнут лимит шагов. Возвращаем найденное.")
        return self._dedupe_contacts(collected_contacts), logs

    def _contacts_from_extraction(self, data: Dict[str, Any]) -> List[Dict[str, str]]:
        candidates: List[Dict[str, str]] = []
        emails = data.get("emails") or []
        addresses = data.get("addresses") or []
        websites = data.get("websites") or []
        # Сконструируем кандидатов; имя неизвестно — пропустим, будет заполнено позже LLM'ом на финализации
        for email in emails:
            candidates.append({
                "name": "",
                "address": "",
                "coordinates": "",
                "email": email,
                "website": "",
            })
        for addr in addresses:
            candidates.append({
                "name": "",
                "address": addr,
                "coordinates": "",
                "email": "",
                "website": "",
            })
        for site in websites:
            candidates.append({
                "name": "",
                "address": "",
                "coordinates": "",
                "email": "",
                "website": site,
            })
        return candidates

    def _dedupe_contacts(self, contacts: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen = set()
        unique: List[Dict[str, str]] = []
        for c in contacts:
            key = (c.get("name") or "", c.get("address") or "", c.get("email") or "", c.get("website") or "")
            if key in seen:
                continue
            seen.add(key)
            # Нормализуем поля
            normalized = {
                "name": (c.get("name") or "").strip(),
                "address": (c.get("address") or "").strip(),
                "coordinates": (c.get("coordinates") or "").strip(),
                "email": (c.get("email") or "").strip(),
                "website": (c.get("website") or "").strip(),
            }
            unique.append(normalized)
        return unique



class WebsiteFinderAgent:
    """Агент подбора официальных сайтов по названию и городу.

    Алгоритм (без LLM):
      1) Запросы в веб‑поиск (DuckDuckGo/Bing) по нескольким формулировкам
      2) Фильтрация агрегаторов и нерелевантных доменов
      3) Проверка кандидатов: заголовок/title, наличие страницы контактов, совпадение по токенам названия, упоминание города
      4) Скоинг и выбор лучшего кандидата
    """

    def __init__(self, max_candidates_per_query: int = 12, max_checked_pages: int = 10, proxy_client: Optional[object] = None):
        self.max_candidates_per_query = max_candidates_per_query
        self.max_checked_pages = max_checked_pages
        self.proxy_client = proxy_client

    def _normalize_text(self, text: str) -> str:
        return ''.join(ch.lower() for ch in (text or '') if ch.isalnum() or ch.isspace()).strip()

    def _important_tokens(self, name: str) -> List[str]:
        stop_words = {
            'гостевой', 'дом', 'гостиница', 'hotel', 'hostel', 'гостевойдом', 'отель', 'санаторий',
            'пансионат', 'resort', 'база', 'отдыха', 'апартаменты', 'apartments', 'мини', 'миниотель'
        }
        tokens = [t for t in self._normalize_text(name).split() if t]
        return [t for t in tokens if t not in stop_words and len(t) > 2]

    def _transliterate_ru_to_lat(self, text: str) -> str:
        mapping = {
            'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y',
            'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f',
            'х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
        }
        res = []
        for ch in (text or '').lower():
            res.append(mapping.get(ch, ch))
        return ''.join(res)

    def _score_candidate(self, *,
                         url: str,
                         title: str,
                         page_text: str,
                         location: str,
                         name_tokens: List[str]) -> int:
        score = 0
        low_title = (title or '').lower()
        low_text = (page_text or '').lower()
        low_url = (url or '').lower()

        # 1) Совпадение ключевых токенов названия в домене или тайтле
        for t in name_tokens:
            if t and t in low_title:
                score += 2
            # грубая проверка по URL
            if f"/{t}" in low_url or t in low_url.split('/')[-1]:
                score += 1

        # 2) Город встречается на странице
        if self._normalize_text(location) and self._normalize_text(location) in self._normalize_text(low_text):
            score += 1

        # 2.1) Транслитерация города/названия встречается в домене/URL
        loc_lat = self._transliterate_ru_to_lat(location)
        if loc_lat and loc_lat in low_url:
            score += 3

        # 2.2) "официаль" в заголовке усиливает уверенность
        if 'официал' in low_title or 'official' in low_title:
            score += 2

        # 3) Наличие признаков контактов или реквизитов
        if any(k in low_text for k in ['контакт', 'тел.', 'телефон', 'email', 'почта', 'инн', 'огрн', '©']):
            score += 2

        # 4) Контактные ссылки
        contact_links = scraper.get_links(url, max_links=10, keywords=['contact', 'contacts', 'контакт', 'контакты', 'about', 'о-компании'])
        if contact_links:
            score += 2

        return score

    def _root_domain(self, url: str) -> str:
        try:
            host = urlparse(url).netloc.lower()
            if host.startswith('www.'):
                host = host[4:]
            parts = host.split('.')
            if len(parts) >= 2:
                return '.'.join(parts[-2:])  # второй уровень
            return host
        except Exception:
            return ''

    def _probe_contact_page(self, base_url: str, location: str) -> Tuple[bool, str]:
        """Пробуем найти контактную страницу на домене и убедиться, что там есть город/контакты."""
        try:
            candidates = [
                '/contacts', '/contact', '/kontakty', '/kontact', '/kontaktyi', '/kontaktyi/',
                '/контакты', '/контакт', '/о-компании', '/о_компании', '/about', '/about-us', '/o-kompanii', '/o_kompanii', '/o-nas', '/o_nas'
            ]
            base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
            for path in candidates:
                url = urljoin(base, path)
                text = scraper.get_page_content(url) or ''
                if not text:
                    continue
                low = text.lower()
                if self._normalize_text(location) and self._normalize_text(location) not in self._normalize_text(low):
                    # если нет упоминания города — слабый сигнал, попробуем другие страницы
                    continue
                # есть город — усилим проверкой контактов
                extracted = contact_extractor.extract_contacts_from_text(text)
                has_any = bool((extracted.get('emails') or []) or (extracted.get('phones') or []) or (extracted.get('addresses') or []))
                if has_any:
                    return True, url
            return False, ''
        except Exception:
            return False, ''

    def _llm_pick_best(self, location: str, name: str, details: List[Dict[str, str]], logs: List[str]) -> Optional[str]:
        try:
            if not self.proxy_client:
                return None
            # Составляем краткий список кандидатов для LLM
            items = []
            for d in details[:10]:
                items.append({
                    "url": d.get("url", ""),
                    "title": (d.get("title", "") or "")[:120],
                    "score": d.get("score", 0),
                    "contact_found": bool(d.get("contact_found")),
                })
            prompt = (
                "Ты помогаешь определить официальный сайт организации.\n"
                "Дано: город: '" + location + "', организация: '" + name + "'.\n"
                "Список кандидатов (url/title/score/contact_found).\n"
                "Выбери один официальный сайт и ответь строго JSON вида {\"url\": string, \"reason\": string}.\n"
                "Критерии: домен 2-го уровня, наличие контактной страницы с адресом в этом городе, бренд/название в контенте, исключить агрегаторы."
            )
            messages = [{"role": "user", "content": prompt + "\n\nКандидаты:\n" + json.dumps(items, ensure_ascii=False)}]
            resp = self.proxy_client.chat_completion(
                model="claude-3-5-sonnet-20240620",
                messages=messages,
                max_tokens=250,
                temperature=0
            )
            # Может быть sync/await; наш ProxyAPIClient async. Попробуем синхронный адаптер через getattr
            if hasattr(self.proxy_client, "chat_completion") and callable(getattr(self.proxy_client, "chat_completion")):
                # Возможно выше вызов вернул корутину
                if hasattr(resp, "__await__"):
                    import asyncio
                    resp = asyncio.get_event_loop().run_until_complete(resp)
            content = resp["choices"][0]["message"]["content"] if isinstance(resp, dict) else ""
            try:
                data = json.loads(content)
                url = (data.get("url") or "").strip()
                if url:
                    logs.append(f"🤖 LLM выбрал: {url}")
                    return url
            except Exception:
                logs.append("⚠️ LLM вернул не-JSON")
                return None
            return None
        except Exception as e:
            logs.append(f"⚠️ Ошибка LLM-оценки: {e}")
            return None

    def _pick_best(self, location: str, name: str, candidates: List[str], logs: List[str]) -> Optional[str]:
        name_tokens = self._important_tokens(name)
        best_url: Optional[str] = None
        best_score = -1
        checked = 0
        checked_domains = set()
        details: List[Dict[str, object]] = []
        for url in candidates:
            if checked >= self.max_checked_pages:
                break
            try:
                # Дедуп по корневому домену
                rd = self._root_domain(url)
                if rd and rd in checked_domains:
                    continue
                # Отсечь трёх- и более уровневые домены у агрегаторов
                host = urlparse(url).netloc.lower()
                if host.count('.') >= 2:
                    # если корневой домен известного агрегатора — пропускаем
                    if any(rd.endswith(agg) for agg in ['broniryem.ru', 'booking.com', 'ostrovok.ru', '101hotels.ru', '101hotels.com']):
                        continue
                checked_domains.add(rd)
                title = scraper.get_title(url)
                text = scraper.get_page_content(url) or ''
                score = self._score_candidate(url=url, title=title, page_text=text, location=location, name_tokens=name_tokens)
                # Дополнительная проверка контактной страницы
                is_official, contact_url = self._probe_contact_page(url, location)
                if is_official:
                    score += 6
                    logs.append(f"✅ Контактная страница найдена: {contact_url}")
                logs.append(f"🔎 Проверка {url} | title='{title[:80] if title else ''}' | score={score}")
                details.append({"url": url, "title": title or "", "score": score, "contact_found": is_official})
                if score > best_score:
                    best_score = score
                    best_url = url
            except Exception as e:
                logs.append(f"⚠️ Ошибка проверки {url}: {e}")
            finally:
                checked += 1
        # Порог, чтобы избежать ложных срабатываний
        if best_url and best_score >= 3:
            return best_url
        # Попробуем LLM-дооценку
        llm_choice = self._llm_pick_best(location, ' '.join(name_tokens) or name, details, logs)
        return llm_choice

    def find_official_website(self, location: str, name: str) -> Tuple[Optional[str], List[str]]:
        logs: List[str] = []
        logs.append(f"🔍 Поиск сайта для '{name}' в '{location}' (приоритет: Яндекс)")
        # 1) Сначала Яндекс Search API
        try:
            agg = list(getattr(web_search, 'aggregator_domains', getattr(scraper, 'aggregator_domains', [])) or [])
        except Exception:
            agg = []
        ys = yandex_search.find_website(name, location, aggregator_domains=agg)
        if ys:
            logs.append(f"🟢 Яндекс: официальный сайт найден: {ys}")
            logs.append(f"✅ Выбран сайт: {ys}")
            return ys, logs
        # 2) Если Яндекс вернул 401/403 — фолбэк на веб‑поиск, чтобы не оставаться без результата
        try:
            code = getattr(yandex_search, 'last_status_code', None)
            dbg = getattr(yandex_search, 'last_debug', None)
            if dbg:
                for line in dbg[:20]:
                    logs.append(f"YANDEX DBG: {line}")
            if code in (401, 403):
                logs.append(f"🟠 Яндекс отказал (HTTP {code}). Перехожу к веб‑поиску кандидатов.")
                # Готовим расширенные запросы (включая транслитерацию)
                translit_name = self._transliterate_ru_to_lat(name)
                translit_loc = self._transliterate_ru_to_lat(location)
                q1 = f"{name} {location} официальный сайт"
                q2 = f"{name} официальный сайт {location}"
                q3 = f"{name} {location} сайт"
                q4 = f"{translit_name} {translit_loc} official site"
                q5 = f"{translit_name} {translit_loc} site"
                q6 = f"{translit_name} официальный сайт"
                q7 = f"{location} {name} официальный"
                results: List[str] = []
                seen = set()
                for q in (q1, q2, q3, q4, q5, q6, q7):
                    urls = web_search.search(q, max_results=self.max_candidates_per_query)
                    logs.append(f"🧭 Результаты '{q}': {len(urls)}")
                    for u in urls:
                        key = (u.split('#')[0])
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append(u)
                if results:
                    best = self._pick_best(location, name, results, logs)
                    if best:
                        logs.append(f"✅ Выбран сайт (фолбэк): {best}")
                        return best, logs
                logs.append("❌ Официальный сайт не найден (после фолбэка)")
                return None, logs
        except Exception:
            pass
        logs.append("🟡 Яндекс не вернул официальный сайт. По требованию — прекращаю поиск.")
        logs.append("❌ Официальный сайт не найден")
        return None, logs

    def find_for_names(self, location: str, names: List[str]) -> Tuple[List[Dict[str, str]], List[str]]:
        all_logs: List[str] = []
        results: List[Dict[str, str]] = []
        for name in names:
            site, logs = self.find_official_website(location, name)
            all_logs.extend(logs)
            results.append({"name": name, "website": site or ""})
        return results, all_logs

