# -*- coding: utf-8 -*-
# 2026-06-11 Round 5 迁移：以下函数从 app/api/v1/pacs.py 原样搬入（纯函数搬家，行为零改变）
"""
PACS AI 分析服务（services/pacs/analysis_service.py）

职责：
  - 千问 VL（阿里云 DashScope OpenAI 兼容接口）统一调用入口
  - modality 自适应采样上限（CT/MR 18、X 光 4、超声 6 等）
  - AI 分析前从 Orthanc 拉取选中帧 JPEG（series 反向索引 + WADO render）

历史行为说明（原样保留，调用方路由依赖这些语义）：
  - call_qwen_vl 上游非 200 / 网络异常时直接抛 HTTPException(500)
  - fetch_frames_for_analysis 单帧失败只记 warning 跳过，全失败返回空列表，
    由路由层决定抛 400
"""
import base64
import logging

from typing import Optional

import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.orthanc_client import orthanc_client
from app.services.pacs.dicom_service import AUTO_SAMPLE_COUNT

logger = logging.getLogger(__name__)

# AI 分析单帧 JPEG 质量（85 兼顾清晰度与 token 消耗）
AI_FRAME_JPEG_QUALITY = 85


async def call_qwen_vl(
    prompt: str,
    images: list[tuple[bytes, str]],
    max_tokens: int = 1000,
) -> str:
    """统一的千问 VL（阿里云 DashScope OpenAI 兼容接口）调用入口。

    抽取自原 analyze_study / analyze_image 两份重复代码，作用：
      - 统一 messages 构造（system 用 prompt，user content 是图像数组）
      - 统一 base64 + dataurl 拼装（不同 mime 共用同一段逻辑）
      - 统一异常处理（HTTP 非 200 / 网络异常都转 HTTPException 500）

    参数:
      prompt     : 用户级文本提示（已含放射科结构化模板，参见 prompts_pacs）
      images     : [(image_bytes, mime), ...] 列表；mime 形如 "image/jpeg"
      max_tokens : 生成上限。study 多帧默认 1000；image 单图原本 800

    返回: 模型文本响应（一般是结构化报告字符串）

    异常: HTTPException(500) — 上游 API 非 200 / 网络异常 / 解析失败
    """
    images_content = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{base64.b64encode(b).decode()}"
            },
        }
        for b, mime in images
    ]
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt}] + images_content,
        }
    ]
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.aliyun_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.aliyun_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.aliyun_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                },
            )
            if resp.status_code != 200:
                raise HTTPException(500, f"AI 分析失败: {resp.text}")
            return resp.json()["choices"][0]["message"]["content"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"AI 服务异常: {e}")


# Modality 自适应采样上限：CT/MR 切片多取 18 帧、X 光本就 1-3 张全取、超声中等
MODALITY_FRAME_CAP = {
    "CT": 18,
    "MR": 18,
    "MRI": 18,
    "PT": 18,   # PET
    "US": 6,    # 超声
    "DR": 4,    # 数字 X 线
    "DX": 4,
    "CR": 4,    # 计算机 X 线
    "XA": 6,    # 血管造影
    "MG": 4,    # 乳腺
}


def frame_cap_for(modality: Optional[str]) -> int:
    """按 modality 决定一次 AI 分析最多送几帧。未知类型默认 18。"""
    if not modality:
        return AUTO_SAMPLE_COUNT
    return MODALITY_FRAME_CAP.get(modality.upper(), AUTO_SAMPLE_COUNT)


async def fetch_frames_for_analysis(
    study_instance_uid: str,
    selected: list[str],
) -> list[tuple[bytes, str]]:
    """从 Orthanc 拉取选中帧的 JPEG 像素（送千问 VL 分析用）。

    流程（与 R1 改造后 analyze_study 路由内的原实现完全一致）：
      1. 一次性查所有 series + instance UID 反向索引（避免每帧都重新 QIDO）
      2. 逐帧走 Orthanc WADO render 拉 JPEG（已 JPEG 编码，省一次本地转码）

    单帧失败（不在 study 内 / 网络错误）只记 warning 跳过；
    全部失败返回空列表，由路由层抛 400。
    """
    # 一次性查所有 series + instance UID 反向索引（避免每帧都重新 QIDO）
    instance_to_series: dict[str, str] = {}
    for series in await orthanc_client.find_series(study_instance_uid):
        s_uid = (series.get("0020000E", {}).get("Value") or [None])[0]
        if not s_uid:
            continue
        for inst in await orthanc_client.find_instances(study_instance_uid, s_uid):
            i_uid = (inst.get("00080018", {}).get("Value") or [None])[0]
            if i_uid:
                instance_to_series[i_uid] = s_uid

    # 从 Orthanc 拉每帧 JPEG（保留质量，给千问 VL 看）
    images: list[tuple[bytes, str]] = []
    for instance_uid in selected:
        series_uid = instance_to_series.get(instance_uid)
        if not series_uid:
            logger.warning("pacs.analyze: instance_not_in_study instance=%s study=%s 跳过", instance_uid, study_instance_uid)
            continue
        try:
            jpeg_bytes = await orthanc_client.get_instance_rendered(
                study_instance_uid,
                series_uid,
                instance_uid,
                quality=AI_FRAME_JPEG_QUALITY,
            )
        except httpx.HTTPError as e:
            logger.warning("pacs.analyze: frame_fetch_failed instance=%s err=%s", instance_uid, e)
            continue
        images.append((jpeg_bytes, "image/jpeg"))
    return images
