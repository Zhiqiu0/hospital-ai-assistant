# -*- coding: utf-8 -*-
# 2026-06-11 Round 5 迁移：以下函数从 app/api/v1/pacs.py 原样搬入（纯函数搬家，行为零改变）
"""
PACS DICOM 文件处理服务（services/pacs/dicom_service.py）

职责（均为纯文件 / 元数据处理，不碰 DB、不碰请求上下文）：
  - 智能非均匀抽帧索引计算（头尾稀疏、中段密集）
  - 上传包内 DCM 文件的 pydicom 元数据解析
    （幂等快路径预检读 StudyInstanceUID / 全量帧 SOPInstanceUID 等）

拆分（超标文件拆分：296 行 → 本门面 + _dicom_archive）：
  - _dicom_archive ：7-Zip 定位 / 压缩包识别 / 解压 / 扫描 .dcm
兼容：压缩相关符号（AUTO 不涉及）从本模块 re-export，
      既有 `from app.services.pacs.dicom_service import detect_archive_kind...`
      与 `dicom_service.extract_and_scan_dcm(...)` 用法保持可用。

历史行为说明（原样保留，调用方路由依赖这些语义）：
  - parse_dicom_files 单文件解析失败只记 warning 跳过，全失败返回空列表，
    由路由层决定抛 400
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from pathlib import Path
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import pydicom  # 仅用于读 DICOM metadata（不做像素渲染）— 上传幂等快路径需要

# ── 本地模块（re-export：压缩包处理拆到 _dicom_archive，保持原导入路径可用） ──
from app.services.pacs._dicom_archive import (  # noqa: F401
    ARCHIVE_EXTENSIONS,
    SEVENZIP_PATH,
    detect_archive_kind,
    extract_and_scan_dcm,
    extract_archive,
)

logger = logging.getLogger(__name__)

# 自动抽帧：instance 数超过此值才需要前端选帧
AUTO_ANALYZE_THRESHOLD = 18
# 自动抽帧目标帧数
AUTO_SAMPLE_COUNT = 18


def smart_sample_indices(total: int, n: int = AUTO_SAMPLE_COUNT) -> list[int]:
    """
    非均匀智能抽帧（按索引返回）：头尾各取少量，中间 60% 区域集中取样。
    适合脊柱/颈椎 CT 等关键病变集中在中段的序列。

    分配比例（n=18 为例）：
      头部 0-20%  → 3 帧
      中部 20-80% → 12 帧（密集）
      尾部 80-100%→ 3 帧

    返回索引列表（升序、去重），调用方拿索引去 instance 列表里取对应 UID。
    R1 之前接受文件名列表；R1 后接受 total + 返回索引，调用方自由映射，
    避免把"文件名"这个本地概念漏到 Orthanc 时代。
    """
    if total <= n:
        return list(range(total))

    n_edge = max(2, n // 6)       # 头尾各抽约 3 帧
    n_mid = n - 2 * n_edge        # 中间约 12 帧

    mid_start = int(total * 0.20)
    mid_end = int(total * 0.80)

    # 头部：0 ~ mid_start 均匀取 n_edge 个索引
    head = [int(mid_start * i / n_edge) for i in range(n_edge)]

    # 中部：mid_start ~ mid_end 均匀取 n_mid 个索引（密集）
    mid_span = mid_end - mid_start
    middle = [
        mid_start + int(mid_span * i / max(n_mid - 1, 1))
        for i in range(n_mid)
    ]

    # 尾部：mid_end ~ total-1 均匀取 n_edge 个索引
    tail_span = (total - 1) - mid_end
    tail = [
        mid_end + int(tail_span * i / max(n_edge - 1, 1))
        for i in range(n_edge)
    ]

    seen: set[int] = set()
    result: list[int] = []
    for idx in head + middle + tail:
        if idx not in seen and idx < total:
            seen.add(idx)
            result.append(idx)
    return sorted(result)[:n]


# ─── 上传包内 DCM 元数据解析（pydicom，仅 metadata 不读 pixel） ─────────────

def read_preflight_study_uid(dcm_path: Path) -> Optional[str]:
    """⚡ 幂等快路径预检：只读第一个 DCM 的 metadata 拿 StudyInstanceUID。

    调用方拿返回值去 DB 查重，命中已存在 → 立即返回原 study_id，
    不读其他文件、不上传 Orthanc（重传 537 帧 study 从分钟级降到亚秒级）。
    读取失败返回 None（跳过幂等快路径，不阻断上传主流程）。
    """
    try:
        ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=True)
        return str(ds.StudyInstanceUID) if hasattr(ds, "StudyInstanceUID") else None
    except Exception as e:
        logger.warning("pacs.upload: preflight_metadata_read_failed 跳过幂等快路径 err=%s", e)
        return None


def parse_dicom_files(
    dcm_paths: list[Path],
) -> tuple[list[bytes], list[str], list[dict]]:
    """读所有 DCM 文件字节 + pydicom 解析每个 SOPInstanceUID/SeriesInstanceUID/InstanceNumber。

    （仅 metadata 不读 pixel，单张 ~5ms）

    返回 (dicom_bytes_list, instance_uids, frames_meta)：
      - dicom_bytes_list : 每个有效 DCM 的原始字节（供 STOW + 本地渲染）
      - instance_uids    : 对应的 SOPInstanceUID 列表（与 bytes 一一对应）
      - frames_meta      : 每帧的 instance_uid + series_uid + instance_number，
        用于 /frames 端点的 Redis 缓存（避免实时查 Orthanc QIDO 慢 5-10s），
        已按 instance_number 排序（DICOM 切片顺序）

    单文件解析失败只记 warning 跳过；全部失败时返回三个空列表，
    由调用方（路由层）决定抛 400。
    """
    import io as _io
    dicom_bytes_list: list[bytes] = []
    instance_uids: list[str] = []
    frames_meta: list[dict] = []
    for f in dcm_paths:
        try:
            b = f.read_bytes()
            ds = pydicom.dcmread(_io.BytesIO(b), stop_before_pixels=True)
            sop_uid = str(getattr(ds, "SOPInstanceUID", "") or "")
            ser_uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
            inst_num = getattr(ds, "InstanceNumber", 0) or 0
            if not sop_uid:
                continue
            dicom_bytes_list.append(b)
            instance_uids.append(sop_uid)
            frames_meta.append({
                "instance_uid": sop_uid,
                "series_uid": ser_uid,
                "instance_number": int(inst_num) if str(inst_num).isdigit() else 0,
            })
        except Exception as e:
            logger.warning("pacs.upload: dicom_parse_failed file=%s err=%s", f, e)
    # 按 instance_number 排序（DICOM 切片顺序）
    frames_meta.sort(key=lambda x: x["instance_number"])
    return dicom_bytes_list, instance_uids, frames_meta
