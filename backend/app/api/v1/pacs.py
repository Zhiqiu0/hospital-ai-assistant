# -*- coding: utf-8 -*-
"""
PACS 影像管理路由（/api/v1/pacs/*）

R1 迁移后职责变化：
  本模块不再持有任何本地 DICOM 解析/渲染代码，所有 DICOM 操作（存储/查询/
  缩略图渲染/原图返回）全部委托给 Orthanc DICOM 服务器（DICOMweb 标准协议）。
  本模块只负责：上传适配、鉴权、AI 调用编排、报告流程、与业务表 ImagingStudy/
  ImagingReport 的关联维护。

端点列表：
  POST /upload                    上传 DICOM ZIP/RAR，解压后 STOW 到 Orthanc
  GET  /{study_id}/frames         返回该 study 的 instance UID 列表 + 智能抽帧建议
  GET  /{study_id}/thumbnail/{i}  通过 WADO 渲染缩略图（支持自定义窗宽窗位）
  GET  /{study_id}/dicom/{i}      通过 WADO 返回原始 DCM 文件（供前端 viewer 加载）
  POST /{study_id}/analyze        从 Orthanc 拉关键帧 → 千问 VL 分析
  PUT  /{study_id}/report         保存（草稿）影像报告
  POST /{study_id}/publish        发布影像报告（正式签发）
  GET  /patient/{patient_id}/reports  获取患者已发布的影像报告列表
  POST /analyze-image             临床医生上传单张 JPG/PNG 直接分析（不入库）
  GET  /studies                   影像科工作列表

权限分层：
  普通医生（doctor）: 只能访问自己有接诊的患者的已发布报告 + 单图分析
  影像科医生（radiologist）/ 管理员: 全量影像列表、AI 分析、发布报告

URL 路径中的 study_id 是业务表 ImagingStudy.id（自生成 UUID），
不是 DICOM StudyInstanceUID——前者用于前端引用稳定，后者用于 Orthanc 检索。
端点内部从 DB 查到 study.study_instance_uid 后再转发到 Orthanc。

端点路径里的 {filename} 历史上是 DCM 文件名，R1 后改为 Orthanc 的
SOPInstanceUID（一个 instance 唯一标识）；前端从 /frames 拿到 UID 列表后
直接用作后续端点的路径参数即可。
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import base64
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import httpx
import pydicom  # 仅用于读 DICOM metadata（不做像素渲染）— 上传幂等快路径需要
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.core.security import get_current_user
from app.core.authz import PACS_WRITE_ROLES, assert_pacs_write, assert_patient_access
from app.database import get_db
from app.models.encounter import Encounter
from app.models.imaging import ImagingReport, ImagingStudy
from app.services.orthanc_client import orthanc_client
from app.services.redis_cache import redis_cache
from app.services.dicom_renderer import render_thumbnail, render_preview
from app.services.ai.prompts_pacs import build_study_prompt, build_image_prompt

logger = logging.getLogger(__name__)

router = APIRouter()

# 临时解压目录：仅在 upload 期间存在，STOW 到 Orthanc 后立刻清理
# 不再像 R1 之前那样长期持有 DICOM 文件
TEMP_UPLOAD_DIR = Path(tempfile.gettempdir()) / "mediscribe_pacs_upload"
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 自动抽帧：instance 数超过此值才需要前端选帧
AUTO_ANALYZE_THRESHOLD = 18
# 自动抽帧目标帧数
AUTO_SAMPLE_COUNT = 18

# AI 分析单帧 JPEG 质量（85 兼顾清晰度与 token 消耗）
AI_FRAME_JPEG_QUALITY = 85


def _smart_sample_indices(total: int, n: int = AUTO_SAMPLE_COUNT) -> list[int]:
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


# ─── 上传 ZIP/RAR → STOW 到 Orthanc ────────────────────────────────────────

def _find_sevenzip() -> Optional[str]:
    """定位 7-Zip 可执行文件（仅在 module 加载时调用一次）。

    查找顺序（任一命中即返回）：
      1. settings.sevenzip_path（用户在 .env 显式指定，最优先）
      2. 系统 PATH 里的 7z / 7za
      3. Windows 常见安装位置：Program Files / 用户自定义目录（C:\\APP 等）
      4. Linux 常见路径：/usr/bin/7z / /usr/local/bin/7z

    全盘 glob 太慢且权限受限，因此只搜常见父目录的两层深度。
    结果会缓存在 module-level `SEVENZIP_PATH`，请求路径不要再调本函数。
    """
    # 1) 配置优先
    if settings.sevenzip_path and os.path.exists(settings.sevenzip_path):
        return settings.sevenzip_path

    # 2) PATH
    exe = shutil.which("7z") or shutil.which("7za")
    if exe:
        return exe

    # 3+4) 常见安装位置（Windows + Linux）
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        "/usr/bin/7z",
        "/usr/local/bin/7z",
        "/opt/homebrew/bin/7z",
    ]
    # 国内用户常见自定义安装路径模式：<盘符>:\APP|Tools|App|Software\...
    import glob as _glob
    for drive in "CDEF":
        for parent in ("APP", "App", "Tools", "ToolApp", "Software", "Apps", "Program"):
            # 限定 2 层深度：drive:\<parent>\.../7-Zip/7z.exe
            candidates += _glob.glob(rf"{drive}:\{parent}\*\7-Zip\7z.exe")
            candidates += _glob.glob(rf"{drive}:\{parent}\7-Zip\7z.exe")

    return next((p for p in candidates if os.path.exists(p)), None)


# Module 加载时一次性定位 7-Zip，避免每次 RAR 上传都触发全盘 glob（慢 + 泄露目录结构）。
# 未检测到时记 warn（不阻塞启动；解压 RAR 等格式时再 HTTPException 400）。
SEVENZIP_PATH: Optional[str] = _find_sevenzip()
if SEVENZIP_PATH:
    logger.info("pacs.sevenzip: detected path=%s", SEVENZIP_PATH)
else:
    logger.warning(
        "pacs.sevenzip: 未检测到 7-Zip，仅 ZIP 上传可用；"
        "RAR/7Z/TAR/ISO 等格式将在上传时返回 400"
    )


# 支持的压缩/打包格式（医院 PACS 真实场景常见）：
#   ZIP  - Windows 默认
#   RAR  - 国内医生常用
#   7Z   - 国内医生常用
#   TAR/TAR.GZ/TGZ/TAR.BZ2/TBZ - Linux 系统下科室自动归档
#   ISO  - CT/MR 设备直接刻盘的 DICOMDIR 光盘镜像
#
# 注：.tar.gz / .tar.bz2 是双后缀，必须先匹配再 fallback 到单后缀
ARCHIVE_EXTENSIONS = (
    ".tar.gz", ".tar.bz2", ".tar.xz",  # 双后缀（必须先匹配）
    ".zip", ".rar", ".7z",
    ".tar", ".tgz", ".tbz", ".tbz2", ".txz",
    ".iso", ".gz", ".bz2", ".xz",
)


def _detect_archive_kind(filename: str) -> Optional[str]:
    """按文件名后缀识别压缩类型，返回内部 kind 标识；未识别返回 None。"""
    fn = filename.lower()
    # 双后缀优先匹配
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if fn.endswith(ext):
            return ext.lstrip(".")  # "tar.gz"
    # 单后缀
    for ext in (".zip", ".rar", ".7z", ".tar", ".tgz", ".tbz", ".tbz2", ".txz",
                ".iso", ".gz", ".bz2", ".xz"):
        if fn.endswith(ext):
            return ext.lstrip(".")
    return None


def _extract_archive(archive_path: Path, dest_dir: Path, archive_kind: str) -> None:
    """解压任意支持的格式到目标目录。

    - ZIP 走 Python 标准库 zipfile（无外部依赖）
    - 其余全部走 7-Zip（一个工具吃掉 RAR/7Z/TAR/GZ/BZ2/XZ/ISO 等十来种）
    """
    if archive_kind == "zip":
        with zipfile.ZipFile(str(archive_path), "r") as zf:
            zf.extractall(str(dest_dir))
        return
    # 7-Zip 兜底：覆盖 RAR / 7Z / TAR.* / ISO / GZ 等
    # SEVENZIP_PATH 在 module 加载时已检测一次，请求路径不再 glob
    if not SEVENZIP_PATH:
        raise HTTPException(
            400, f"服务器未安装 7-Zip，无法解压 {archive_kind.upper()} 文件"
        )
    sevenzip = SEVENZIP_PATH
    # tar.gz / tar.bz2 这种双层格式，7z 单次只能解一层（先解 .gz → 得到 .tar），
    # 因此双后缀格式跑两遍 7z：第一遍解外层得到 tar，第二遍把 tar 解成文件
    rounds = 2 if archive_kind in {"tar.gz", "tar.bz2", "tar.xz", "tgz", "tbz", "tbz2", "txz", "gz", "bz2", "xz"} else 1
    current_input = archive_path
    for round_idx in range(rounds):
        # 中间产物放到一个隔离目录，避免污染最终输出
        round_out = dest_dir if round_idx == rounds - 1 else (dest_dir.parent / f"_inter_{round_idx}")
        round_out.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sevenzip, "x", str(current_input), f"-o{round_out}", "-y"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise HTTPException(
                400, f"{archive_kind.upper()} 解压失败: {result.stderr or result.stdout}"
            )
        # 下一轮的输入：解出来的第一个 tar 文件（双后缀场景）
        if round_idx < rounds - 1:
            tars = list(round_out.rglob("*.tar"))
            if not tars:
                # 没有 tar，说明是单层 .gz/.bz2/.xz（如单文件压缩），直接结束
                break
            current_input = tars[0]


@router.post("/upload")
async def upload_study(
    patient_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """上传 ZIP/RAR 压缩包 → 解压 → STOW 到 Orthanc → 写 ImagingStudy 索引。

    R1 迁移要点：
      - 不再持久化 DICOM 文件到本地（uploads/pacs 目录），所有文件直接 STOW
        到 Orthanc，本地只在 STOW 完成前的临时目录里短暂存在
      - ImagingStudy.storage_dir 不再写入（保留 NULL，向后兼容旧数据）
      - 新增 study_instance_uid 字段：从 STOW 响应里抽出 DICOM 标准 UID，
        后续所有 Orthanc 调用都用它索引
    """
    # 只允许影像科医生 + 管理员上传；临床医生看影像走只读路径
    assert_pacs_write(current_user)
    archive_kind = _detect_archive_kind(file.filename or "")
    if not archive_kind:
        raise HTTPException(
            400,
            "不支持的压缩格式，请使用：ZIP / RAR / 7Z / TAR / TAR.GZ / TGZ / "
            "TAR.BZ2 / TBZ / TAR.XZ / ISO 之一",
        )

    # 临时工作目录：STOW 完成或异常后立即清理
    work_dir = TEMP_UPLOAD_DIR / f"upload_{datetime.now().timestamp():.6f}".replace(".", "")
    work_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = work_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1) 落盘压缩包（用原始扩展名让 7-Zip 自动识别格式）
        archive_path = work_dir / f"source.{archive_kind}"
        archive_path.write_bytes(await file.read())

        # 2) 解压（按格式自动选择 zipfile 或 7-Zip）
        _extract_archive(archive_path, extract_dir, archive_kind)

        # 3) 找所有 DCM 文件路径（先扫一遍，不读字节）
        dcm_paths = [
            f for f in extract_dir.rglob("*")
            if f.is_file() and f.suffix.lower() == ".dcm"
        ]
        if not dcm_paths:
            raise HTTPException(400, "压缩包中未找到 DCM 文件")

        # 3.5) ⚡ 幂等快路径：只读第一个 DCM 的 metadata 拿 StudyInstanceUID 查 DB
        #      命中已存在 → 立即返回原 study_id，不读其他文件、不上传 Orthanc
        #      重传 537 帧 study 从分钟级降到亚秒级
        try:
            ds = pydicom.dcmread(str(dcm_paths[0]), stop_before_pixels=True)
            preflight_study_uid = (
                str(ds.StudyInstanceUID) if hasattr(ds, "StudyInstanceUID") else None
            )
        except Exception as e:
            logger.warning("读取首个 DCM metadata 失败，跳过幂等快路径: %s", e)
            preflight_study_uid = None

        if preflight_study_uid:
            existing_q = await db.execute(
                select(ImagingStudy).where(
                    ImagingStudy.study_instance_uid == preflight_study_uid
                )
            )
            existing_study = existing_q.scalar_one_or_none()
            if existing_study:
                if existing_study.patient_id != patient_id:
                    raise HTTPException(
                        409,
                        f"该影像已归属其他患者，不能再绑定到当前患者（已有 study_id={existing_study.id}）。"
                        "请先在 PACS 列表中处理原记录，或选择正确的患者。",
                    )
                return {
                    "study_id": existing_study.id,
                    "study_instance_uid": preflight_study_uid,
                    "total_frames": existing_study.total_frames,
                    "modality": existing_study.modality,
                    "body_part": existing_study.body_part,
                    "auto_select": (existing_study.total_frames or 0) <= AUTO_ANALYZE_THRESHOLD,
                    "duplicate": True,
                    "message": "该影像之前已上传过，已为你定位到原记录",
                }

        # 3.6) 不重复 → 读所有文件字节 + pydicom 解析每个 SOPInstanceUID/SeriesInstanceUID/InstanceNumber
        # （仅 metadata 不读 pixel，单张 ~5ms）
        import io as _io
        dicom_bytes_list: list[bytes] = []
        instance_uids: list[str] = []
        # frames_meta: 每帧的 instance_uid + series_uid + instance_number，用于
        # /frames 端点的 Redis 缓存（避免实时查 Orthanc QIDO 慢 5-10s）
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
                logger.warning("读取/解析 DICOM 失败 [%s]: %s", f, e)
        if not dicom_bytes_list:
            raise HTTPException(400, "DCM 文件读取失败")
        # 按 instance_number 排序（DICOM 切片顺序）
        frames_meta.sort(key=lambda x: x["instance_number"])

        # 4) ⚡ 并行：STOW 到 Orthanc + pydicom 本地渲染 256/1024 JPEG → Redis
        # 优化 3 核心：backend 渲染每张 ~3ms × 537 / 8 路 ≈ 0.2s
        # STOW 单 instance 并发 8 路 ≈ 5-15s（Orthanc 写盘 + 索引）
        # 用 asyncio.gather 同时跑，总时间 = max(两者) ≈ STOW 时间，渲染白送
        target_study_uid = preflight_study_uid
        instances_for_render = list(zip(instance_uids, dicom_bytes_list))

        async def _do_stow():
            return await orthanc_client.stow_instances(dicom_bytes_list)

        async def _do_render():
            if target_study_uid:
                await _render_and_cache_all(target_study_uid, instances_for_render)

        import asyncio as _asyncio
        stow_resp, _ = await _asyncio.gather(_do_stow(), _do_render())

        # 5) 从 STOW 响应取 StudyInstanceUID（preflight 拿到的优先）
        study_uid = target_study_uid or _extract_study_uid_from_stow_response(stow_resp)
        if not study_uid:
            raise HTTPException(500, "Orthanc 上传成功但未返回 StudyInstanceUID")

        # 5.5) 把 frames_meta 存到 Redis，让 /frames 端点免去实时查 Orthanc QIDO
        # 一次 SET，后续 /frames 调用 < 50ms（vs 实时查 ~2-10s）
        import json as _json
        await redis_cache.set_bytes(
            f"pacs:frames:{study_uid}",
            _json.dumps(frames_meta).encode("utf-8"),
            ttl=settings.thumbnail_cache_ttl,
        )

        # 6) 幂等性检查：同一份 DICOM 包（同 study_instance_uid）二次上传时不再
        #    重复创建业务行，避免触发 unique 约束 IntegrityError 500。
        #    医院真实场景：医生误操作重传 / 网络重试 / 同包发给多人审核都很常见。
        existing = await db.execute(
            select(ImagingStudy).where(ImagingStudy.study_instance_uid == study_uid)
        )
        existing_study = existing.scalar_one_or_none()
        if existing_study:
            if existing_study.patient_id != patient_id:
                # 跨患者重复：DICOM UID 全局唯一，几乎一定是医生选错患者
                raise HTTPException(
                    409,
                    f"该影像已归属其他患者，不能再绑定到当前患者（已有 study_id={existing_study.id}）。"
                    "请先在 PACS 列表中处理原记录，或选择正确的患者。",
                )
            # 同患者重复 → 幂等：返回原 study_id 让前端跳转
            return {
                "study_id": existing_study.id,
                "study_instance_uid": study_uid,
                "total_frames": existing_study.total_frames,
                "modality": existing_study.modality,
                "body_part": existing_study.body_part,
                "auto_select": (existing_study.total_frames or 0) <= AUTO_ANALYZE_THRESHOLD,
                "duplicate": True,
                "message": "该影像之前已上传过，已为你定位到原记录",
            }

        # 7) 取 study 元数据（modality / body_part / series_description / 实例总数）
        meta = await _fetch_study_metadata(study_uid)

        # 8) 写业务表 ImagingStudy
        study = ImagingStudy(
            patient_id=patient_id,
            uploaded_by=current_user.id,
            study_instance_uid=study_uid,
            modality=meta.get("modality"),
            body_part=meta.get("body_part"),
            series_description=meta.get("series_description"),
            total_frames=meta.get("total_instances", 0),
            storage_dir=None,  # R1 后不再使用本地存储
            status="pending",
        )
        db.add(study)
        await db.commit()
        await db.refresh(study)

        # 注：上面 asyncio.gather 已经把所有 instance 的缩略图 + 高清预览
        # 用 pydicom 本地渲染并写入 Redis 完毕。此处不再额外预热。

        return {
            "study_id": study.id,
            "study_instance_uid": study_uid,
            "total_frames": meta.get("total_instances", 0),
            "modality": meta.get("modality"),
            "body_part": meta.get("body_part"),
            "auto_select": meta.get("total_instances", 0) <= AUTO_ANALYZE_THRESHOLD,
            "duplicate": False,
        }
    finally:
        # 无论成功失败都清理临时目录
        shutil.rmtree(str(work_dir), ignore_errors=True)


def _extract_study_uid_from_stow_response(stow_resp: dict) -> Optional[str]:
    """从 STOW-RS 响应解析 StudyInstanceUID。

    DICOM JSON 中 ReferencedSOPSequence (0008,1199) 是数组，每个元素的
    RetrieveURL (0008,1190) 形如 .../studies/{study_uid}/series/.../instances/...
    所有 instance 都属于同一个 study（一次上传一个 study），取第一个即可。
    """
    refs = stow_resp.get("00081199", {}).get("Value", [])
    if not refs:
        return None
    retrieve_url = refs[0].get("00081190", {}).get("Value", [None])[0]
    if not retrieve_url:
        return None
    # URL 格式: http://host/dicom-web/studies/{study_uid}/series/{s_uid}/instances/{i_uid}
    parts = retrieve_url.split("/studies/")
    if len(parts) != 2:
        return None
    return parts[1].split("/")[0]


async def _render_and_cache_all(
    study_uid: str,
    instances_with_bytes: list[tuple[str, bytes]],
    concurrency: int = 8,
) -> None:
    """用 pydicom 本地渲染所有 instance 的 256 缩略图 + 1024 高清预览，写 Redis。

    这是优化 3 的核心：替代之前调 Orthanc 渲染（每张 ~150-600ms），改用
    backend 进程内 pydicom + Pillow 渲染（每张 ~3-5ms），快 30 倍。

    instances_with_bytes: [(instance_uid, dcm_bytes), ...]
    并发度通过 ThreadPoolExecutor 控制（pydicom + Pillow 释放 GIL，真并行）。

    Redis key 约定：
      pacs:thumb:{study_uid}:{instance_uid}    → 256 缩略图（列表用）
      pacs:preview:{study_uid}:{instance_uid}  → 1024 高清预览（DicomViewer 主区用）
    """
    import asyncio as _asyncio

    if not instances_with_bytes:
        return

    loop = _asyncio.get_event_loop()
    sem = _asyncio.Semaphore(concurrency)

    async def _one(iuid: str, dcm_bytes: bytes) -> None:
        async with sem:
            # 在线程池里跑 pydicom（CPU 密集，run_in_executor 释放 event loop）
            try:
                thumb_jpeg = await loop.run_in_executor(None, render_thumbnail, dcm_bytes)
                preview_jpeg = await loop.run_in_executor(None, render_preview, dcm_bytes)
            except Exception as e:
                logger.warning("渲染失败 [%s]: %s", iuid, e)
                return
            if thumb_jpeg:
                await redis_cache.set_bytes(
                    f"pacs:thumb:{study_uid}:{iuid}",
                    thumb_jpeg,
                    ttl=settings.thumbnail_cache_ttl,
                )
            if preview_jpeg:
                await redis_cache.set_bytes(
                    f"pacs:preview:{study_uid}:{iuid}",
                    preview_jpeg,
                    ttl=settings.thumbnail_cache_ttl,
                )

    await _asyncio.gather(
        *[_one(iuid, dcm) for iuid, dcm in instances_with_bytes],
        return_exceptions=True,
    )
    logger.info(
        "[RENDER] study=%s 完成本地渲染 %d 帧（缩略+预览）",
        study_uid[-12:],
        len(instances_with_bytes),
    )


async def _fetch_study_metadata(study_uid: str) -> dict:
    """从 Orthanc 拉 study 主要元数据：modality / body_part / series_description / 实例总数。

    取所有 series 后聚合：modality 取第一个非空值，body_part 取第一个非空值，
    series_description 拼接所有 series（去重）。

    QIDO-RS 默认不返回 BodyPartExamined / NumberOfSeriesRelatedInstances，
    必须显式 includefield。
    """
    series_list = await orthanc_client.find_series(
        study_uid,
        include_fields=["BodyPartExamined", "NumberOfSeriesRelatedInstances"],
    )
    modality = None
    body_part = None
    series_descs: list[str] = []
    total_instances = 0
    for s in series_list:
        # DICOM JSON 字段：00080060=Modality 00180015=BodyPartExamined 0008103E=SeriesDescription
        m = (s.get("00080060", {}).get("Value") or [None])[0]
        bp = (s.get("00180015", {}).get("Value") or [None])[0]
        sd = (s.get("0008103E", {}).get("Value") or [None])[0]
        # 00201209 = Number of Series Related Instances
        n = (s.get("00201209", {}).get("Value") or [0])[0]
        if m and not modality:
            modality = str(m)
        if bp and not body_part:
            body_part = str(bp)
        if sd and sd not in series_descs:
            series_descs.append(str(sd))
        try:
            total_instances += int(n)
        except (TypeError, ValueError):
            pass
    return {
        "modality": modality,
        "body_part": body_part,
        "series_description": " / ".join(series_descs)[:200] if series_descs else None,
        "total_instances": total_instances,
    }


# ─── 获取切片列表（QIDO 查 Orthanc）───────────────────────────────────────

async def _list_study_instances(study_uid: str) -> list[dict]:
    """返回 study 下所有 instance 的精简信息（按 InstanceNumber 排序）。

    每条形如 {"instance_uid": "...", "series_uid": "...", "instance_number": 1}
    """
    raw = await orthanc_client.find_all_instances_in_study(study_uid)
    result = []
    for inst in raw:
        # 00080018 = SOPInstanceUID; 00200013 = InstanceNumber
        instance_uid = (inst.get("00080018", {}).get("Value") or [None])[0]
        instance_number = (inst.get("00200013", {}).get("Value") or [0])[0]
        if not instance_uid:
            continue
        result.append({
            "instance_uid": instance_uid,
            "series_uid": inst.get("_seriesInstanceUID"),
            "instance_number": int(instance_number) if instance_number else 0,
        })
    return result


@router.get("/{study_id}/frames")
async def get_frames(
    study_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """返回该 study 全部 instance UID 列表 + 智能抽帧建议（用 instance_uid 标识）。

    R1 后前端不再使用文件名访问 DICOM——改为传 instance_uid 给后续端点。
    """
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    # 跨患者权限校验：放射科/管理员直通；普通医生必须对该患者有过接诊
    await assert_patient_access(db, study.patient_id, current_user)
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    # ⚡ 优先从 Redis 读 frames 元数据（上传时已写入），免去实时查 Orthanc QIDO
    import json as _json
    cache_key = f"pacs:frames:{study.study_instance_uid}"
    cached = await redis_cache.get_bytes(cache_key)
    if cached:
        try:
            instances = _json.loads(cached.decode("utf-8"))
        except Exception:
            instances = await _list_study_instances(study.study_instance_uid)
    else:
        # 老 study（R1 预热前上传的）走 Orthanc QIDO 兜底，并把结果回写 Redis
        instances = await _list_study_instances(study.study_instance_uid)
        if instances:
            await redis_cache.set_bytes(
                cache_key,
                _json.dumps(instances).encode("utf-8"),
                ttl=settings.thumbnail_cache_ttl,
            )

    total = len(instances)

    # 智能非均匀抽样（按索引→映射回 instance_uid）
    suggested_indices = _smart_sample_indices(total, AUTO_SAMPLE_COUNT)
    suggested = [instances[i]["instance_uid"] for i in suggested_indices]

    return {
        "study_id": study_id,
        "study_instance_uid": study.study_instance_uid,
        "total": total,
        "frames": instances,  # 每项含 instance_uid + series_uid + instance_number
        "suggested": suggested,
    }


# ─── 缩略图服务（WADO render，Orthanc 自带 GDCM 渲染）─────────────────────

async def _resolve_instance(study_uid: str, instance_uid: str) -> Optional[str]:
    """通过 instance_uid 反查 series_uid（O(1) 走 Orthanc 私有 REST）。

    历史 bug：曾经遍历该 study 所有 series + 所有 instance（O(N²) 网络往返），
    537 帧 study 单张缩略图加载耗时 12 秒，整个列表加载预计 107 分钟。
    现在改用 `tools/find Level=Instance` 一次定位 instance + 一次拿 series UID，
    总共 2 次 Orthanc 调用，与帧数无关。

    更优做法：前端从 /frames 响应里就已经有 series_uid，调 thumbnail/dicom
    端点时一并传过来，免去本函数调用。本函数只在前端没传时兜底。
    """
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(
            auth=(settings.orthanc_username, settings.orthanc_password),
            timeout=10.0,
        ) as c:
            # 1) 用 SOPInstanceUID 找 Orthanc 内部 instance id
            r = await c.post(
                f"{settings.orthanc_base_url.rstrip('/')}/tools/find",
                json={
                    "Level": "Instance",
                    "Query": {
                        "StudyInstanceUID": study_uid,
                        "SOPInstanceUID": instance_uid,
                    },
                },
            )
            r.raise_for_status()
            ids = r.json()
            if not ids:
                return None
            # 2) 拿 instance 详情，里面有 ParentSeries（Orthanc 内部 series id）
            r = await c.get(f"{settings.orthanc_base_url.rstrip('/')}/instances/{ids[0]}")
            r.raise_for_status()
            parent_series = r.json().get("ParentSeries")
            if not parent_series:
                return None
            # 3) 拿 series 详情，里面有 SeriesInstanceUID（DICOM 标准 UID）
            r = await c.get(f"{settings.orthanc_base_url.rstrip('/')}/series/{parent_series}")
            r.raise_for_status()
            return r.json().get("MainDicomTags", {}).get("SeriesInstanceUID")
    except _httpx.HTTPError:
        return None


@router.get("/{study_id}/thumbnail/{instance_uid}")
async def get_thumbnail(
    study_id: str,
    instance_uid: str,
    wc: Optional[float] = None,
    ww: Optional[float] = None,
    series_uid: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """缩略图服务（含 PHI，必须鉴权）。

    instance_uid 是 SOPInstanceUID（DICOM 标准全局唯一），不是文件名。
    Orthanc 用 GDCM 实时渲染 + 应用窗位窗宽，无需本地缓存目录。

    series_uid 是性能优化：前端从 /frames 响应里已经拿到 series_uid，
    调本端点时一并带上，后端可免去一次反查（537 帧 study 加载从分钟级降到秒级）。

    历史漏洞修复（保留说明）：曾完全无鉴权——任何人拿到 study_id+filename
    即可下载缩略图（属于 PHI 泄露级漏洞）。已接入 assert_patient_access。
    """
    # instance_uid 是 DICOM UID，只允许数字和点号，防注入
    if not all(c.isdigit() or c == "." for c in instance_uid):
        raise HTTPException(400, "非法 instance UID")
    if series_uid and not all(c.isdigit() or c == "." for c in series_uid):
        raise HTTPException(400, "非法 series UID")
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    await assert_patient_access(db, study.patient_id, current_user)
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    # 优先用前端传的 series_uid（0 次 Orthanc 调用），没传才走兜底反查
    resolved_series = series_uid or await _resolve_instance(
        study.study_instance_uid, instance_uid
    )
    if not resolved_series:
        raise HTTPException(404, "影像帧不存在")

    # ⚡ 优化 3：Redis 优先，没命中走 pydicom 本地渲染（不再走 Orthanc 渲染）
    # 自定义窗位窗宽不缓存（key 空间无穷），实时渲染
    is_default_window = wc is None and ww is None
    cache_key = f"pacs:thumb:{study.study_instance_uid}:{instance_uid}" if is_default_window else None

    if cache_key:
        cached = await redis_cache.get_bytes(cache_key)
        if cached:
            return Response(
                content=cached,
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=86400", "X-Cache": "HIT"},
            )

    # 没命中 / 自定义窗位 → 拉 raw DCM + pydicom 渲染
    try:
        dcm_bytes = await orthanc_client.get_instance_dicom(
            study.study_instance_uid, resolved_series, instance_uid
        )
    except httpx.HTTPError as e:
        logger.error("拉 DCM 失败 [%s]: %s", instance_uid, e)
        raise HTTPException(502, "影像加载失败")

    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()
    jpeg_bytes = await loop.run_in_executor(
        None,
        lambda: render_thumbnail(dcm_bytes, window_center=wc, window_width=ww),
    )
    if not jpeg_bytes:
        raise HTTPException(500, "DICOM 渲染失败")

    # 默认窗位窗宽 → 异步写缓存（不阻塞响应）
    if cache_key:
        _asyncio.create_task(
            redis_cache.set_bytes(cache_key, jpeg_bytes, ttl=settings.thumbnail_cache_ttl)
        )

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Cache": "MISS",
        },
    )


# ─── 高清预览 JPEG（DicomViewer 主区用，1024 quality 85）─────────────────

@router.get("/{study_id}/preview/{instance_uid}")
async def get_preview(
    study_id: str,
    instance_uid: str,
    wc: Optional[float] = None,
    ww: Optional[float] = None,
    series_uid: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """高清预览 JPEG（1024×1024 quality 85，~30-80KB）。

    DicomViewer 主区 <img> 直接加载本端点 URL。比 raw DICOM (~860KB +
    cornerstone3D 客户端解码) 快得多——浏览器原生 JPEG 渲染，秒级出图。

    数据来源：
      - 上传时 backend pydicom 已渲染好高清版，存 Redis key `pacs:preview:{}:{}`
      - 没命中走 Orthanc 拉 raw DCM + pydicom 实时渲染（写回 Redis）

    自定义窗位窗宽（wc/ww）：实时渲染，不缓存。
    """
    if not all(c.isdigit() or c == "." for c in instance_uid):
        raise HTTPException(400, "非法 instance UID")
    if series_uid and not all(c.isdigit() or c == "." for c in series_uid):
        raise HTTPException(400, "非法 series UID")
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    await assert_patient_access(db, study.patient_id, current_user)
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    is_default_window = wc is None and ww is None
    cache_key = (
        f"pacs:preview:{study.study_instance_uid}:{instance_uid}"
        if is_default_window
        else None
    )

    if cache_key:
        cached = await redis_cache.get_bytes(cache_key)
        if cached:
            return Response(
                content=cached,
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=86400", "X-Cache": "HIT"},
            )

    resolved_series = series_uid or await _resolve_instance(
        study.study_instance_uid, instance_uid
    )
    if not resolved_series:
        raise HTTPException(404, "影像帧不存在")

    try:
        dcm_bytes = await orthanc_client.get_instance_dicom(
            study.study_instance_uid, resolved_series, instance_uid
        )
    except httpx.HTTPError as e:
        logger.error("拉 DCM 失败 [%s]: %s", instance_uid, e)
        raise HTTPException(502, "影像加载失败")

    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()
    jpeg_bytes = await loop.run_in_executor(
        None,
        lambda: render_preview(dcm_bytes, window_center=wc, window_width=ww),
    )
    if not jpeg_bytes:
        raise HTTPException(500, "DICOM 渲染失败")

    if cache_key:
        _asyncio.create_task(
            redis_cache.set_bytes(cache_key, jpeg_bytes, ttl=settings.thumbnail_cache_ttl)
        )

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Cache": "MISS",
        },
    )


# ─── 原始 DCM 文件服务（WADO instance，保留供 cornerstone3D 高级 viewer 用）──

@router.get("/{study_id}/dicom/{instance_uid}")
async def get_dicom_file(
    study_id: str,
    instance_uid: str,
    series_uid: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """原始 DCM 文件下载（供前端 cornerstone.js / OHIF 加载，含完整 PHI，必须鉴权）。

    R1 后从 Orthanc WADO instance 透传，FastAPI 不再持有任何 DCM 文件。
    series_uid 同 thumbnail 端点：可选，传上来免一次反查。
    """
    import time as _time
    perf_start = _time.perf_counter()
    perf = {}

    if not all(c.isdigit() or c == "." for c in instance_uid):
        raise HTTPException(400, "非法 instance UID")
    if series_uid and not all(c.isdigit() or c == "." for c in series_uid):
        raise HTTPException(400, "非法 series UID")

    t0 = _time.perf_counter()
    study = await db.get(ImagingStudy, study_id)
    perf["db_get_study"] = _time.perf_counter() - t0
    if not study:
        raise HTTPException(404, "检查不存在")

    t0 = _time.perf_counter()
    await assert_patient_access(db, study.patient_id, current_user)
    perf["assert_patient_access"] = _time.perf_counter() - t0

    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    if not series_uid:
        t0 = _time.perf_counter()
        series_uid = await _resolve_instance(study.study_instance_uid, instance_uid)
        perf["resolve_instance"] = _time.perf_counter() - t0
    if not series_uid:
        raise HTTPException(404, "影像帧不存在")

    try:
        t0 = _time.perf_counter()
        dcm_bytes = await orthanc_client.get_instance_dicom(
            study.study_instance_uid, series_uid, instance_uid
        )
        perf["orthanc_fetch"] = _time.perf_counter() - t0
    except httpx.HTTPError as e:
        logger.error("WADO instance 获取失败 [%s]: %s", instance_uid, e)
        raise HTTPException(502, "影像下载失败")

    total = _time.perf_counter() - perf_start
    if total > 1.0:  # 只记录慢请求避免日志刷屏
        logger.warning(
            "[PERF] dicom %s: total=%.3fs %s",
            instance_uid[-12:],
            total,
            " ".join(f"{k}={v:.3f}" for k, v in perf.items()),
        )

    return Response(content=dcm_bytes, media_type="application/dicom")


# ─── AI 分析（从 Orthanc 拉关键帧 → 千问 VL）────────────────────────────────

async def _call_qwen_vl(
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


class AnalyzeRequest(BaseModel):
    """前端传选中的 instance UID 列表（R1 后不再用文件名）。"""
    selected_frames: List[str]


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


def _frame_cap_for(modality: Optional[str]) -> int:
    """按 modality 决定一次 AI 分析最多送几帧。未知类型默认 18。"""
    if not modality:
        return AUTO_SAMPLE_COUNT
    return MODALITY_FRAME_CAP.get(modality.upper(), AUTO_SAMPLE_COUNT)


@router.post("/{study_id}/analyze")
async def analyze_study(
    study_id: str,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """从 Orthanc 拉选中帧 → 千问 VL 分析 → 写报告。

    R1 改造：
      - 选中帧由 instance UID 标识（不再是文件名）
      - 帧数上限按 modality 自适应（CT/MR 18、X 光 4、超声 6 等）
      - 帧像素从 Orthanc WADO render 拉（已 JPEG 编码，省一次本地转码）
    """
    assert_pacs_write(current_user)
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持分析")

    cap = _frame_cap_for(study.modality)
    selected = body.selected_frames[:cap]
    if not selected:
        raise HTTPException(400, "未选中任何影像帧")

    # 一次性查所有 series + instance UID 反向索引（避免每帧都重新 QIDO）
    instance_to_series: dict[str, str] = {}
    for series in await orthanc_client.find_series(study.study_instance_uid):
        s_uid = (series.get("0020000E", {}).get("Value") or [None])[0]
        if not s_uid:
            continue
        for inst in await orthanc_client.find_instances(study.study_instance_uid, s_uid):
            i_uid = (inst.get("00080018", {}).get("Value") or [None])[0]
            if i_uid:
                instance_to_series[i_uid] = s_uid

    # 从 Orthanc 拉每帧 JPEG（保留质量，给千问 VL 看）
    images: list[tuple[bytes, str]] = []
    for instance_uid in selected:
        series_uid = instance_to_series.get(instance_uid)
        if not series_uid:
            logger.warning("AI 分析：instance %s 不属于 study %s，跳过", instance_uid, study.study_instance_uid)
            continue
        try:
            jpeg_bytes = await orthanc_client.get_instance_rendered(
                study.study_instance_uid,
                series_uid,
                instance_uid,
                quality=AI_FRAME_JPEG_QUALITY,
            )
        except httpx.HTTPError as e:
            logger.warning("AI 分析：拉帧失败 %s: %s", instance_uid, e)
            continue
        images.append((jpeg_bytes, "image/jpeg"))

    if not images:
        raise HTTPException(400, "没有可分析的影像帧")

    # 构建 prompt + 调千问 VL（统一走 _call_qwen_vl，与单图分析共用代码路径）
    prompt = build_study_prompt(study.modality, study.body_part)
    ai_result = await _call_qwen_vl(prompt, images, max_tokens=1000)

    # 保存到数据库（unique 约束保证一个 study 至多一条 report）
    result = await db.execute(select(ImagingReport).where(ImagingReport.study_id == study_id))
    report = result.scalar_one_or_none()

    if report:
        report.selected_frames = selected
        report.ai_analysis = ai_result
        report.final_report = ai_result
    else:
        report = ImagingReport(
            study_id=study_id,
            radiologist_id=current_user.id,
            selected_frames=selected,
            ai_analysis=ai_result,
            final_report=ai_result,
        )
        db.add(report)

    study.status = "analyzed"
    await db.commit()

    return {"ai_analysis": ai_result}


# ─── 保存 / 发布报告（合并端点） ─────────────────────────────────────────────

class SaveReportRequest(BaseModel):
    """保存影像报告 body。

    - final_report : 报告正文（必填）
    - publish      : True 表示同时签发；False 仅保存草稿
    """
    final_report: str
    publish: bool = False


@router.put("/{study_id}/report")
async def save_report(
    study_id: str,
    body: SaveReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存或同时签发影像报告。

    Audit Round 4 G4：原本拆成 PUT /report（草稿）+ POST /publish（签发）两个端点，
    实际差异只是是否设置 is_published / published_at / published_by 三个字段，
    合并成一个端点更直观——前端只需要传 publish=True 就能签发。

    审计链设计（保持 R1 后行为一致）：
      - radiologist_id : 在 analyze_study 阶段写入，本端点 **绝不覆盖**——
        否则 "A 分析、B 复核签发" 场景会把分析人记成 B。
      - published_by   : 仅在 publish=True 时写入，记录实际签发责任人。
    """
    assert_pacs_write(current_user)
    result = await db.execute(
        select(ImagingReport).where(ImagingReport.study_id == study_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "报告不存在，请先进行 AI 分析")

    report.final_report = body.final_report

    response: dict = {"ok": True}
    if body.publish:
        report.is_published = True
        report.published_at = datetime.utcnow()
        # 关键：只写 published_by，绝不覆盖 radiologist_id（保留分析人审计）
        report.published_by = current_user.id

        study = await db.get(ImagingStudy, study_id)
        if study:
            study.status = "published"

        response["published_at"] = report.published_at.isoformat()

    await db.commit()
    return response


# ─── 获取患者的已发布报告（临床医生用）────────────────────────────────────────

@router.get("/patient/{patient_id}/reports")
async def get_patient_reports(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 普通医生只能访问自己有 encounter 的患者
    if getattr(current_user, "role", "doctor") not in PACS_WRITE_ROLES:
        enc = await db.execute(
            select(Encounter.id).where(
                Encounter.patient_id == patient_id,
                Encounter.doctor_id == current_user.id,
            ).limit(1)
        )
        if not enc.scalar_one_or_none():
            raise HTTPException(403, "无权访问该患者影像资料")

    result = await db.execute(
        select(ImagingStudy, ImagingReport)
        .join(ImagingReport, ImagingReport.study_id == ImagingStudy.id, isouter=True)
        .where(ImagingStudy.patient_id == patient_id)
        .where(ImagingStudy.status == "published")
        .order_by(ImagingStudy.created_at.desc())
    )
    rows = result.all()
    return [
        {
            "study_id": s.id,
            "modality": s.modality,
            "body_part": s.body_part,
            "series_description": s.series_description,
            "total_frames": s.total_frames,
            "created_at": s.created_at.isoformat(),
            "final_report": r.final_report if r else None,
            "published_at": r.published_at.isoformat() if r and r.published_at else None,
        }
        for s, r in rows
    ]


# ─── 临床医生：直接上传 JPG/PNG 分析 ────────────────────────────────────────

@router.post("/analyze-image")
async def analyze_image(
    file: UploadFile = File(...),
    image_type: str = Form(default=""),
    current_user=Depends(get_current_user),
):
    """临床医生上传 JPG/PNG/DCM，直接送千问分析，返回结构化报告"""
    allowed_img = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = file.content_type or ""
    filename = file.filename or ""
    is_dcm = filename.lower().endswith(".dcm") or content_type in {"application/dicom", "application/octet-stream"}

    if not is_dcm and content_type not in allowed_img and not any(filename.lower().endswith(e) for e in [".jpg", ".jpeg", ".png", ".webp"]):
        raise HTTPException(400, "请上传 JPG/PNG/WebP 或 DCM 格式文件")

    raw_bytes = await file.read()

    if is_dcm:
        # DCM → JPEG：临时 STOW 到 Orthanc → WADO render 拿 JPEG → 删除临时 study
        # 这种"分析完即删"模式不污染 Orthanc 索引，也不需要本地 pydicom/PIL 渲染
        temp_study_uid: Optional[str] = None
        try:
            stow_resp = await orthanc_client.stow_instances([raw_bytes])
            temp_study_uid = _extract_study_uid_from_stow_response(stow_resp)
            if not temp_study_uid:
                raise HTTPException(400, "DCM 文件解析失败：Orthanc 未返回 StudyInstanceUID")
            series_list = await orthanc_client.find_series(temp_study_uid)
            if not series_list:
                raise HTTPException(400, "DCM 文件解析失败：未找到 series")
            series_uid = (series_list[0].get("0020000E", {}).get("Value") or [None])[0]
            inst_list = await orthanc_client.find_instances(temp_study_uid, series_uid)
            if not inst_list:
                raise HTTPException(400, "DCM 文件解析失败：未找到 instance")
            instance_uid = (inst_list[0].get("00080018", {}).get("Value") or [None])[0]
            img_bytes = await orthanc_client.get_instance_rendered(
                temp_study_uid, series_uid, instance_uid, quality=AI_FRAME_JPEG_QUALITY,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"DCM 文件解析失败: {e}")
        finally:
            # 无论成功失败都清理 Orthanc 临时数据，避免索引污染
            if temp_study_uid:
                try:
                    await orthanc_client.delete_study(temp_study_uid)
                except Exception as e:
                    logger.warning("清理临时 study 失败 [%s]: %s", temp_study_uid, e)
        mime = "image/jpeg"
    else:
        img_bytes = raw_bytes
        mime = content_type if content_type in allowed_img else "image/jpeg"

    # 构建 prompt + 调千问 VL（与 analyze_study 共用 _call_qwen_vl）
    prompt = build_image_prompt(image_type)
    analysis = await _call_qwen_vl(prompt, [(img_bytes, mime)], max_tokens=800)
    return {"analysis": analysis}


# ─── 删除影像研究 ───────────────────────────────────────────────────────────

@router.delete("/{study_id}")
async def delete_study(
    study_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除影像研究（含 Orthanc 端 + 业务表 + 报告，不可逆）。

    权限：影像科医生 + 管理员。
    业务约束：
      - 已发布（status=published）的 study **禁止删除**——医疗审计合规要求
        发布报告必须保留追溯链。需要修改请走"撤销发布 → 修改 → 重发布"流程
        （撤销发布功能后续 R2 再做）。
      - 未发布的 study（pending / analyzing / analyzed）允许删除。

    级联删除：
      1. Orthanc 端：调用私有 REST 删除整个 study（含所有 series/instances/files）
      2. ImagingReport：手动 DELETE（避免 ORM cascade 配置遗漏）
      3. ImagingStudy：DELETE
    """
    assert_pacs_write(current_user)
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")

    if study.status == "published":
        raise HTTPException(
            409,
            "已发布的报告不能删除（医疗审计合规要求保留追溯链）。"
            "如需修改，请通过撤销发布流程。",
        )

    # 1) 删 Orthanc 端数据（先删 Orthanc 再删 DB；如果 Orthanc 失败 DB 还在，
    #    保留可重试机会；反之 DB 删了 Orthanc 失败会留孤儿数据）
    if study.study_instance_uid:
        try:
            await orthanc_client.delete_study(study.study_instance_uid)
        except Exception as e:
            logger.error("Orthanc 删除失败 [%s]: %s", study.study_instance_uid, e)
            raise HTTPException(502, f"Orthanc 数据清理失败，DB 行未删除: {e}")
        # 清 Redis 里该 study 的所有缓存（frames 元数据 + 缩略图 + 高清预览）
        await redis_cache.delete(f"pacs:frames:{study.study_instance_uid}")
        await redis_cache.delete_prefix(f"pacs:thumb:{study.study_instance_uid}:")
        await redis_cache.delete_prefix(f"pacs:preview:{study.study_instance_uid}:")

    # 2) 删 ImagingReport（如有）
    from sqlalchemy import delete as _sql_delete
    await db.execute(
        _sql_delete(ImagingReport).where(ImagingReport.study_id == study_id)
    )

    # 3) 删 ImagingStudy
    await db.delete(study)
    await db.commit()

    return {"ok": True, "deleted_study_id": study_id}


# ─── 获取影像科工作列表 ──────────────────────────────────────────────────────

@router.get("/studies")
async def list_studies(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 只有放射科医生和管理员可查看全部影像列表
    if getattr(current_user, "role", "doctor") not in PACS_WRITE_ROLES:
        raise HTTPException(403, "仅放射科医生可访问影像列表")

    q = select(ImagingStudy).order_by(ImagingStudy.created_at.desc())
    if status:
        q = q.where(ImagingStudy.status == status)
    result = await db.execute(q)
    studies = result.scalars().all()
    return [
        {
            "study_id": s.id,
            "patient_id": s.patient_id,
            "modality": s.modality,
            "body_part": s.body_part,
            "series_description": s.series_description,
            "total_frames": s.total_frames,
            "status": s.status,
            "created_at": s.created_at.isoformat(),
        }
        for s in studies
    ]
