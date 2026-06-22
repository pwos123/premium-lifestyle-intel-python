"""
统一 LLM 调用封装 — 支持 DeepSeek / MiMo / Kimi
三个模型均兼容 OpenAI 接口协议，使用 openai SDK + 不同 base_url
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    name: str
    api_key: str
    base_url: str
    model: str
    weight: float = 1.0


@dataclass
class ModelResponse:
    model_name: str
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    raw_text: str = ""


class LLMCaller:
    """统一的 LLM 调用器，支持多模型并行分析"""

    def __init__(self, configs: dict[str, ModelConfig]):
        """
        configs: {"deepseek": ModelConfig, "mimo": ModelConfig, "kimi": ModelConfig}
        """
        self.clients: dict[str, tuple[OpenAI, ModelConfig]] = {}
        for name, cfg in configs.items():
            if cfg.api_key and not cfg.api_key.startswith("YOUR_"):
                client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
                self.clients[name] = (client, cfg)
                logger.info(f"已初始化模型: {name} ({cfg.model})")
            else:
                logger.warning(f"跳过未配置的模型: {name}")

    @property
    def available_models(self) -> list[str]:
        return list(self.clients.keys())

    def call_model(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        timeout: int = 60,
    ) -> ModelResponse:
        """调用单个模型"""
        if model_name not in self.clients:
            return ModelResponse(
                model_name=model_name,
                success=False,
                error=f"模型 {model_name} 未配置",
            )

        client, cfg = self.clients[model_name]
        try:
            response = client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            msg = response.choices[0].message
            raw_text = (msg.content or "").strip()
            
            # deepseek-reasoner puts answer in reasoning_content, content may be empty
            if not raw_text and hasattr(msg, 'model_extra') and msg.model_extra:
                reasoning = msg.model_extra.get('reasoning_content', '')
                if reasoning:
                    raw_text = reasoning.strip()
            
            data = self._parse_json_response(raw_text)
            return ModelResponse(
                model_name=model_name, success=True, data=data, raw_text=raw_text
            )
        except Exception as e:
            logger.error(f"模型 {model_name} 调用失败: {e}")
            return ModelResponse(
                model_name=model_name, success=False, error=str(e)
            )

    def call_all_models(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        timeout: int = 60,
    ) -> dict[str, ModelResponse]:
        """调用所有可用模型，返回结果字典"""
        results = {}
        for name in self.available_models:
            logger.info(f"调用模型: {name}")
            results[name] = self.call_model(
                name, system_prompt, user_prompt, temperature, max_tokens, timeout
            )
        return results

    @staticmethod
    def _parse_json_response(text: str) -> Optional[dict]:
        """从模型输出中提取 JSON,兼容 deepseek-reasoner 思考模式"""
        def parse_candidate(candidate: str) -> Optional[dict]:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

            lines = candidate.splitlines()
            if any(re.match(r'\s*"title"\s*:', line) for line in lines):
                without_title = "\n".join(
                    line for line in lines
                    if not re.match(r'\s*"title"\s*:', line)
                )
                try:
                    return json.loads(without_title)
                except json.JSONDecodeError:
                    pass

            return None

        # 尝试直接解析
        parsed = parse_candidate(text)
        if parsed is not None:
            return parsed

        # 尝试提取 ```json ... ``` 块
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            parsed = parse_candidate(text[start:end].strip())
            if parsed is not None:
                return parsed

        # 尝试提取最后一个完整的 { ... } 块(兼容思考模式在JSON后的文字)
        if "{" in text and "}" in text:
            # 找最后一个 { 和对应的 }
            last_brace = text.rfind("}")
            # 从后往前找匹配的 {
            depth = 0
            start = -1
            for i in range(last_brace, -1, -1):
                if text[i] == "}":
                    depth += 1
                elif text[i] == "{":
                    depth -= 1
                    if depth == 0:
                        start = i
                        break
            if start >= 0:
                parsed = parse_candidate(text[start:last_brace+1])
                if parsed is not None:
                    return parsed

        logger.warning(f"无法解析 JSON 响应: {text[:200]}...")
        return None
