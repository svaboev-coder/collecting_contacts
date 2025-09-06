import json
import logging
from typing import List, Dict, Any, Tuple

try:
    # Запуск из директории backend (python backend/main.py)
    from utils import contact_extractor, scraper
except ImportError:
    # Запуск как пакет (uvicorn backend.main:app)
    from backend.utils import contact_extractor, scraper

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


