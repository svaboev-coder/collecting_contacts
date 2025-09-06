import httpx
import json
import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class ProxyAPIClient:
    """Клиент для работы с ProxyAPI"""
    
    def __init__(self):
        self.api_key = os.getenv("PROXYAPI_KEY")
        # Разрешаем задавать базовый URL через .env, по умолчанию используем proxyapi.ru
        self.base_url = os.getenv("PROXYAPI_BASE_URL", "https://api.proxyapi.ru").rstrip("/")
        
        if not self.api_key:
            raise ValueError("PROXYAPI_KEY не найден в переменных окружения")
        
        logger.info(f"ProxyAPI клиент инициализирован с ключом: {self.api_key[:10]}...")
    
    async def chat_completion(
        self,
        model: str,
        messages: list,
        max_tokens: int = 1000,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Отправка запроса к AI модели через ProxyAPI
        
        Args:
            model: Название модели (например, "gpt-3.5-turbo", "claude-3-sonnet")
            messages: Список сообщений в формате OpenAI
            max_tokens: Максимальное количество токенов
            temperature: Температура генерации
            
        Returns:
            Ответ от API в формате словаря
        """
        
        # Определяем провайдера по модели
        provider = self._get_provider_by_model(model)
        
        # Формируем URL для конкретного провайдера (с несколькими вариантами путей)
        provider_paths = []
        if provider == "openai":
            provider_paths = [
                "/openai/v1/chat/completions",
                "/v1/chat/completions",
            ]
        elif provider == "anthropic":
            # ProxyAPI RU: стабильно работает только этот путь
            provider_paths = [
                "/anthropic/v1/messages",
            ]
        else:
            raise ValueError(f"Неподдерживаемая модель: {model}")

        last_error: Optional[Exception] = None
        
        # Формируем заголовки
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        if provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        
        # Формируем тело запроса
        if provider == "openai":
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
        elif provider == "anthropic":
            # Конвертируем OpenAI формат в Anthropic формат
            anthropic_messages = []
            for msg in messages:
                if msg["role"] == "user":
                    anthropic_messages.append({"role": "user", "content": msg["content"]})
                elif msg["role"] == "assistant":
                    anthropic_messages.append({"role": "assistant", "content": msg["content"]})
                elif msg["role"] == "system":
                    # Anthropic не поддерживает system role, добавляем в user
                    if anthropic_messages and anthropic_messages[0]["role"] == "user":
                        anthropic_messages[0]["content"] = f"{msg['content']}\n\n{anthropic_messages[0]['content']}"
                    else:
                        anthropic_messages.insert(0, {"role": "user", "content": msg["content"]})
            
            payload = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
        
        try:
            logger.info(f"Отправляем запрос к ProxyAPI провайдер={provider}, base={self.base_url}")
            logger.info(f"Модель: {model}")
            logger.info(f"Промпт: {messages[-1]['content'][:200]}...")
            
            async with httpx.AsyncClient() as client:
                for path in provider_paths:
                    url = f"{self.base_url}{path}"
                    try:
                        logger.info(f"Отправляем запрос к ProxyAPI ({provider}): {url}")
                        response = await client.post(
                            url,
                            headers=headers,
                            json=payload,
                            timeout=60.0
                        )
                        logger.info(f"ProxyAPI ответ получен: HTTP {response.status_code} для {url}")
                        if response.status_code == 200:
                            response_data = response.json()
                            logger.info(f"ProxyAPI ответ: {response_data}")
                            if provider == "openai":
                                return self._convert_openai_response(response_data)
                            elif provider == "anthropic":
                                return self._convert_anthropic_response(response_data)
                        else:
                            logger.warning(f"Неуспешный ответ с {url}: {response.status_code} - {response.text}")
                            last_error = Exception(f"HTTP {response.status_code}: {response.text}")
                            continue
                    except Exception as e:
                        logger.warning(f"Ошибка запроса к {url}: {e}")
                        last_error = e
                        continue
                # Если ни один путь не сработал
                raise Exception(f"ProxyAPI запрос не удался для всех путей {provider_paths}: {last_error}")
                    
        except Exception as e:
            logger.error(f"Ошибка запроса к ProxyAPI: {str(e)}")
            raise
    
    def _get_provider_by_model(self, model: str) -> str:
        """Определяет провайдера по названию модели"""
        if model.startswith("gpt-") or model.startswith("text-"):
            return "openai"
        elif model.startswith("claude-"):
            return "anthropic"
        else:
            # По умолчанию используем OpenAI
            return "openai"
    
    def _convert_openai_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Конвертирует ответ OpenAI в стандартный формат"""
        return response_data
    
    def _convert_anthropic_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Конвертирует ответ Anthropic в формат OpenAI"""
        # Anthropic возвращает другой формат, конвертируем в OpenAI формат
        if "content" in response_data and len(response_data["content"]) > 0:
            message_content = response_data["content"][0].get("text", "")
            
            converted_response = {
                "choices": [
                    {
                        "message": {
                            "content": message_content,
                            "role": "assistant"
                        },
                        "finish_reason": "stop",
                        "index": 0
                    }
                ],
                "model": response_data.get("model", "unknown"),
                "usage": response_data.get("usage", {})
            }
            
            return converted_response
        else:
            raise Exception("Неверный формат ответа от Anthropic")
