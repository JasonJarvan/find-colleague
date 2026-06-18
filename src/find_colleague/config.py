"""配置加载：env 优先，其次仓库根 config.toml。"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

# 仓库根 = 本文件的 src/find_colleague/ 上溯两层
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.toml"

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_EMBED_MODEL = "qwen/qwen3-embedding-8b"
DEFAULT_DB_PATH = "data/find_colleague.db"


@dataclass
class Config:
    api_key: str | None
    base_url: str
    embed_model: str
    db_path: Path
    provider_llm: str | None = None  # v3 service 抽取/清洗用的 chat 模型；v2 用 subagent 不读它

    def require_key(self) -> str:
        if not self.api_key:
            raise SystemExit(
                "未找到 OpenRouter key。请二选一：\n"
                "  1) 设环境变量：export OPENROUTER_API_KEY=sk-or-...\n"
                f"  2) 复制 config.example.toml 为 {CONFIG_PATH.name} 并填 [openrouter].api_key\n"
            )
        return self.api_key


def load_config() -> Config:
    file_cfg: dict = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            file_cfg = tomllib.load(f)

    orc = file_cfg.get("openrouter", {})
    storage = file_cfg.get("storage", {})
    provider = file_cfg.get("provider", {})

    # env 优先
    api_key = os.environ.get("OPENROUTER_API_KEY") or orc.get("api_key")
    base_url = os.environ.get("OPENROUTER_BASE_URL") or orc.get("base_url") or DEFAULT_BASE_URL
    embed_model = os.environ.get("FC_EMBED_MODEL") or orc.get("embed_model") or DEFAULT_EMBED_MODEL
    db_path_raw = os.environ.get("FC_DB_PATH") or storage.get("db_path") or DEFAULT_DB_PATH

    db_path = Path(db_path_raw)
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path

    provider_llm = os.environ.get("FC_PROVIDER_LLM") or provider.get("llm")

    return Config(
        api_key=api_key, base_url=base_url, embed_model=embed_model,
        db_path=db_path, provider_llm=provider_llm,
    )
