"""
模型调用参数（app/services/ai/model_options.py）

提供 ``get_model_options`` 返回指定场景的 LLM 调用参数（模型名 / 温度 /
最大输出 token），供所有 AI 路由及服务统一取用，避免各处散写魔法数字。

历史：2026-08-18 之前这里从 model_configs 表读、admin 后台可按场景改模型与
温度。撤掉的原因：只有 DeepSeek 一家两个模型，reasoner 时延不适合医生
实时场景；温度/token 属技术调参项，医院管理员既不懂也不该动，改错直接
影响病历质量。现在参数归代码维护——要换模型改 .env 的 DEEPSEEK_MODEL，
要按场景微调就在本文件按 scene 加分支，走 PR review。
"""

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.services.ai.llm_client import llm_client

# 全场景统一默认：与 llm_client 各方法的默认形参一致
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 4096


def get_model_options(scene: str) -> dict:
    """返回指定场景的 LLM 调用参数。

    Args:
        scene: 场景标识（'generate' / 'qc' / 'inquiry' / 'exam' / 'polish'），
               当前所有场景共用一套默认值，保留形参便于日后按场景差异化。

    Returns:
        包含 model_name / temperature / max_tokens 的配置字典。
    """
    return {
        "model_name": llm_client.model,
        "temperature": _DEFAULT_TEMPERATURE,
        "max_tokens": _DEFAULT_MAX_TOKENS,
    }
