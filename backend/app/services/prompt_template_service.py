"""
LLM 配置服务（app/services/prompt_template_service.py）

2026-06-11 Round 5 迁移：业务逻辑从 app/api/v1/admin/prompts.py 和
app/api/v1/admin/model_configs.py 下沉到 service 层，路由层只保留
请求解析 + 鉴权 + 调 service，行为零改变。

两类配置同属"管理后台 LLM 配置"（模型都在 app/models/config.py），内聚性强，
合并在一个文件里、用两个 service 类分别封装：

PromptTemplateService（Prompt 模板）：
  - list_templates : 按创建时间倒序列出全部模板
  - create         : 新建模板（写库后失效该 scene 的激活模板缓存）
  - update         : 更新模板字段（写库后失效缓存）
  - delete         : 删除模板（写库后失效缓存）

ModelConfigService（按场景的模型参数配置）:
  - list_configs   : 列出全部场景配置（首次访问自动 seed 默认行）
  - update         : 更新指定 scene 的模型参数（写库后失效模型配置缓存）

缓存失效设计：
  激活的 prompt 模板与模型参数都有进程内/Redis 缓存（每次 AI 调用前查），
  任何写操作后必须立即调用对应的 invalidate_* 让新配置生效。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.config import ModelConfig, PromptTemplate
from app.schemas.config import PromptTemplateCreate, PromptTemplateUpdate
from app.services.ai.ai_utils import invalidate_active_prompt
from app.services.ai.model_options import invalidate_model_options

# 模型配置的默认场景清单：首次访问列表时自动 seed，保证管理后台总能看到全部场景
SCENE_DEFAULTS = [
    {"scene": "generate", "description": "病历生成（AI 起草病历）"},
    {"scene": "polish", "description": "病历润色（AI 优化措辞）"},
    {"scene": "qc", "description": "质控分析（AI 检查病历质量）"},
    {"scene": "inquiry", "description": "问诊建议（AI 补充追问要点）"},
    {"scene": "exam", "description": "检查推荐（AI 推荐辅助检查）"},
]


class PromptTemplateService:
    """Prompt 模板数据访问服务，封装模板 CRUD 及激活缓存失效逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_templates(self) -> list[PromptTemplate]:
        """按创建时间倒序列出全部 Prompt 模板。"""
        result = await self.db.execute(
            select(PromptTemplate).order_by(PromptTemplate.created_at.desc())
        )
        return result.scalars().all()

    async def create(self, data: PromptTemplateCreate) -> PromptTemplate:
        """新建 Prompt 模板，写库后失效该 scene 的激活模板缓存。

        version 未传时默认 'v1'（与历史行为一致）。
        """
        template = PromptTemplate(
            name=data.name,
            scene=data.scene,
            content=data.content,
            version=data.version or "v1",
        )
        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)
        # 该 scene 下激活模板可能变了，立即失效缓存让新配置生效
        await invalidate_active_prompt(template.scene)
        return template

    async def update(self, prompt_id: str, data: PromptTemplateUpdate) -> PromptTemplate:
        """更新 Prompt 模板（只更新非 None 字段），写库后失效缓存。

        Raises:
            HTTPException(404): 模板不存在。
        """
        result = await self.db.execute(
            select(PromptTemplate).where(PromptTemplate.id == prompt_id)
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(template, field, value)
        await self.db.commit()
        await self.db.refresh(template)
        await invalidate_active_prompt(template.scene)
        return template

    async def delete(self, prompt_id: str) -> None:
        """删除 Prompt 模板，写库后失效该 scene 的激活模板缓存。

        Raises:
            HTTPException(404): 模板不存在。
        """
        result = await self.db.execute(
            select(PromptTemplate).where(PromptTemplate.id == prompt_id)
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        scene = template.scene
        await self.db.delete(template)
        await self.db.commit()
        await invalidate_active_prompt(scene)


class ModelConfigService:
    """模型配置数据访问服务，封装按场景的 LLM 参数 CRUD 及缓存失效逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _ensure_defaults(self) -> None:
        """为所有默认场景补齐配置行（不存在才插入），保证列表完整。"""
        for item in SCENE_DEFAULTS:
            result = await self.db.execute(
                select(ModelConfig).where(ModelConfig.scene == item["scene"])
            )
            if not result.scalar_one_or_none():
                self.db.add(ModelConfig(
                    scene=item["scene"],
                    model_name="deepseek-chat",
                    temperature=0.3,
                    max_tokens=4096,
                    is_active=True,
                    description=item["description"],
                ))
        await self.db.commit()

    async def list_configs(self) -> list[dict]:
        """列出全部场景的模型配置（按 scene 排序，首次访问自动 seed 默认行）。"""
        await self._ensure_defaults()
        result = await self.db.execute(select(ModelConfig).order_by(ModelConfig.scene))
        configs = result.scalars().all()
        return [
            {
                "id": c.id,
                "scene": c.scene,
                "model_name": c.model_name,
                "temperature": c.temperature,
                "max_tokens": c.max_tokens,
                "is_active": c.is_active,
                "description": c.description,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in configs
        ]

    async def update(
        self,
        scene: str,
        *,
        model_name: str,
        temperature: float,
        max_tokens: int,
        is_active: bool,
        description: Optional[str] = None,
    ) -> dict:
        """更新指定 scene 的模型配置（不存在则新建），写库后失效模型配置缓存。

        description 为 None 时保留旧值（与历史行为一致）。
        """
        await self._ensure_defaults()
        result = await self.db.execute(select(ModelConfig).where(ModelConfig.scene == scene))
        config = result.scalar_one_or_none()
        if not config:
            config = ModelConfig(scene=scene)
            self.db.add(config)
        config.model_name = model_name
        config.temperature = temperature
        config.max_tokens = max_tokens
        config.is_active = is_active
        if description is not None:
            config.description = description
        await self.db.commit()
        await self.db.refresh(config)
        # 失效该 scene 的模型配置缓存（每次 AI 调用前都查这个）
        await invalidate_model_options(config.scene)
        return {"message": "保存成功", "scene": config.scene}
