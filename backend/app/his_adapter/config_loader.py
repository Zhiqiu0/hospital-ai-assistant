"""HIS 字段映射 YAML 加载器（config_loader.py）

桌面 Agent 启动时调 /api/v1/desktop/config 拉取自己医院对应的 YAML。
后端按 hospital_code 路由到对应的 *.yaml 文件。

加载策略：
  - 模块启动时一次性加载所有 *_map.yaml 到内存
  - 改 YAML 后重启后端生效（医院字段映射不会频繁变）
"""

from pathlib import Path
from typing import Any

import yaml

# 本目录下所有 *_map.yaml 都自动加载
_MAP_DIR = Path(__file__).parent
_loaded_maps: dict[str, dict[str, Any]] = {}


def _load_all_maps() -> None:
    """启动时扫 *_map.yaml 一次性加载，按 hospital.code 索引。"""
    for yaml_file in _MAP_DIR.glob("*_map.yaml"):
        with yaml_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or "hospital" not in data:
            continue
        code = data["hospital"].get("code")
        if code:
            _loaded_maps[code] = data


def get_map(hospital_code: str) -> dict[str, Any] | None:
    """按医院编码取字段映射配置。"""
    if not _loaded_maps:
        _load_all_maps()
    return _loaded_maps.get(hospital_code)


def list_supported_hospitals() -> list[dict[str, str]]:
    """列出所有已配置的医院（管理后台展示用）。"""
    if not _loaded_maps:
        _load_all_maps()
    return [
        {
            "code": code,
            "name": m["hospital"].get("name", ""),
            "his_brand": m["hospital"].get("his_brand", ""),
        }
        for code, m in _loaded_maps.items()
    ]
