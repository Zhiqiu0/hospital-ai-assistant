"""DICOM → JPEG 本地渲染服务（services/dicom_renderer.py）

定位：上传时用 pydicom + Pillow 在 backend 进程内直接把 DCM 渲染成 JPEG，
存到 Redis。后续浏览缩略图 / DicomViewer 直接从 Redis 读字节，不再走
Orthanc 渲染管线。

为什么不只用 Orthanc：
  - Orthanc 渲染单张 ~150-600ms（GDCM/dcmtk 解码 + libpng 编码）
  - pydicom + Pillow 渲染单张 ~30-80ms（直接窗位映射 + JPEG）
  - backend 渲染省一次 HTTP 往返；和 STOW 用 asyncio.gather 并行
  - 这是 R1 之前的实现，医院 PACS Web 端的标配做法

这里渲染**不替代** Orthanc——Orthanc 仍然作为 DICOM 标准存储 + 未来 CT 机
直传 + cornerstone3D 等高级功能的入口。本模块只是为"快速浏览"提供加速。

输出两个尺寸：
  - 256x256 (quality 70) → 缩略图列表用，~3-8KB
  - 1024x1024 (quality 85) → DicomViewer 主区用，~30-80KB
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import numpy as np
import pydicom
from PIL import Image

logger = logging.getLogger(__name__)

# 缩略图尺寸（列表用，要小要快）
THUMB_SIZE = 256
THUMB_QUALITY = 70

# 高清预览尺寸（DicomViewer 主区用，质量优先）
PREVIEW_SIZE = 1024
PREVIEW_QUALITY = 85


def render_dcm_to_jpeg(
    dcm_bytes: bytes,
    *,
    max_size: int,
    quality: int,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> Optional[bytes]:
    """单张 DCM bytes → JPEG bytes。

    渲染步骤：
      1. pydicom 解析 + 读 pixel_array（含 RescaleSlope/Intercept 处理）
      2. 应用窗位窗宽（参数优先 → DICOM 标签 → 自动从像素值估算）
      3. 8-bit 灰度归一化
      4. 等比缩放到 max_size 内（保持比例，避免拉伸）
      5. JPEG 编码

    参数：
      dcm_bytes: 一个 .dcm 文件的二进制内容
      max_size:  输出 JPEG 长边最大像素（256 缩略图 / 1024 高清预览）
      quality:   JPEG 质量 1-100
      window_center / window_width: 自定义窗位窗宽（None 时自动）

    返回：JPEG 字节流；DCM 解析失败时返回 None（调用方按"渲染失败"处理）。
    """
    try:
        ds = pydicom.dcmread(io.BytesIO(dcm_bytes))
    except Exception as e:
        logger.warning("pydicom 解析失败: %s", e)
        return None

    try:
        arr = ds.pixel_array.astype(np.float32)
    except Exception as e:
        logger.warning("读 pixel_array 失败: %s", e)
        return None

    # RescaleSlope/Intercept：DICOM 像素 → 真实物理值（HU 等）
    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    arr = arr * slope + intercept

    # 窗位窗宽：参数优先 → DICOM 标签 → 像素估算
    if window_center is None or window_width is None:
        if hasattr(ds, "WindowCenter") and hasattr(ds, "WindowWidth"):
            try:
                wc_raw = ds.WindowCenter
                ww_raw = ds.WindowWidth
                # 多值情况（MultiValue），取第一个
                window_center = float(wc_raw[0] if hasattr(wc_raw, "__iter__") else wc_raw)
                window_width = float(ww_raw[0] if hasattr(ww_raw, "__iter__") else ww_raw)
            except Exception:
                window_center = window_width = None
        if window_center is None or window_width is None:
            window_center = float(np.median(arr))
            window_width = float(arr.max() - arr.min()) or 1.0

    lo = window_center - window_width / 2
    hi = window_center + window_width / 2
    arr = np.clip(arr, lo, hi)
    arr = ((arr - lo) / max(hi - lo, 1e-6) * 255).astype(np.uint8)

    # MONOCHROME1 是反转灰度（一些 X 光），翻一下
    if str(getattr(ds, "PhotometricInterpretation", "") or "") == "MONOCHROME1":
        arr = 255 - arr

    img = Image.fromarray(arr)
    # 等比缩到 max_size 内（thumbnail 是 in-place 操作）
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=False)
    return buf.getvalue()


def render_thumbnail(
    dcm_bytes: bytes,
    *,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> Optional[bytes]:
    """渲染列表用缩略图（256×256, quality 70）。"""
    return render_dcm_to_jpeg(
        dcm_bytes,
        max_size=THUMB_SIZE,
        quality=THUMB_QUALITY,
        window_center=window_center,
        window_width=window_width,
    )


def render_preview(
    dcm_bytes: bytes,
    *,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> Optional[bytes]:
    """渲染 DicomViewer 主区高清预览（1024×1024, quality 85）。"""
    return render_dcm_to_jpeg(
        dcm_bytes,
        max_size=PREVIEW_SIZE,
        quality=PREVIEW_QUALITY,
        window_center=window_center,
        window_width=window_width,
    )
