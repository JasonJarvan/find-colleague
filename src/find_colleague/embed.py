"""OpenRouter embeddings 客户端（stdlib urllib，OpenAI 兼容 schema）。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import Config


def _post(url: str, payload: dict, api_key: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "find-colleague",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"OpenRouter embeddings 请求失败 HTTP {e.code}: {body}") from e


def embed_texts(cfg: Config, texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """批量 embedding，返回与 texts 等长的向量列表。"""
    api_key = cfg.require_key()
    url = f"{cfg.base_url}/embeddings"
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        resp = _post(url, {"model": cfg.embed_model, "input": chunk}, api_key)
        # OpenAI 兼容：data 按 index 排序
        items = sorted(resp["data"], key=lambda d: d["index"])
        out.extend(item["embedding"] for item in items)
    return out


def embed_one(cfg: Config, text: str) -> list[float]:
    return embed_texts(cfg, [text])[0]


def list_models(cfg: Config) -> list[dict]:
    """GET /embeddings/models —— 列出可用 embedding 模型。"""
    api_key = cfg.require_key()
    req = urllib.request.Request(
        f"{cfg.base_url}/embeddings/models",
        method="GET",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"列模型失败 HTTP {e.code}: {body}") from e
    return payload.get("data", payload if isinstance(payload, list) else [])
