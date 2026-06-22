"""
配置加载工具。

敏感信息只从环境变量或本地 .env 读取，不写入 settings.yaml。
"""

import os
from pathlib import Path
from typing import Any

import yaml

from .models import ModelConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODEL_ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "QWEN_API_KEY",
    "kimi": "KIMI_API_KEY",
}


def load_dotenv(path: Path | None = None) -> None:
    """加载本地 .env；已存在的环境变量优先。"""
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: Path | None = None) -> dict[str, Any]:
    """读取 settings.yaml，并用环境变量覆盖运行时路径。"""
    load_dotenv()
    config_path = path or PROJECT_ROOT / "config" / "settings.yaml"
    with config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if os.environ.get("DATABASE_PATH"):
        config.setdefault("database", {})["path"] = os.environ["DATABASE_PATH"]
    if os.environ.get("IMAGE_CACHE_DIR"):
        config.setdefault("images", {})["cache_dir"] = os.environ["IMAGE_CACHE_DIR"]
    if os.environ.get("OUTPUT_DIR"):
        config.setdefault("report", {})["output_dir"] = os.environ["OUTPUT_DIR"]

    return config


def load_model_configs(config: dict[str, Any]) -> dict[str, ModelConfig]:
    """将模型元数据与环境变量中的 API Key 合并为 ModelConfig。"""
    model_configs = {}
    for name, cfg in config.get("api_keys", {}).items():
        env_key = MODEL_ENV_KEYS.get(name, f"{name.upper()}_API_KEY")
        api_key = os.environ.get(env_key, cfg.get("api_key", ""))
        model_configs[name] = ModelConfig(
            name=name,
            api_key=api_key,
            base_url=cfg["base_url"],
            model=cfg["model"],
            weight=cfg.get("weight", 1.0),
        )
    return model_configs
