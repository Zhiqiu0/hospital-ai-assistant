# -*- coding: utf-8 -*-
# 2026-06-11 Round 5 迁移：以下函数从 app/api/v1/pacs.py 原样搬入（纯函数搬家，行为零改变）
"""
PACS DICOM 文件处理服务（services/pacs/dicom_service.py）

职责（均为纯文件 / 元数据处理，不碰 DB、不碰请求上下文）：
  - 7-Zip 可执行文件定位（module 加载时一次）+ 压缩包解压
    （ZIP 走 Python 标准库 zipfile，RAR/7Z/TAR/ISO 等走 7-Zip subprocess）
  - 上传包内 DCM 文件的 pydicom 元数据解析
    （幂等快路径预检读 StudyInstanceUID / 全量帧 SOPInstanceUID 等）
  - 智能非均匀抽帧索引计算（头尾稀疏、中段密集）

历史行为说明（原样保留，调用方路由依赖这些语义）：
  - extract_archive 解压失败时直接抛 HTTPException(400)
  - parse_dicom_files 单文件解析失败只记 warning 跳过，全失败返回空列表，
    由路由层决定抛 400
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import pydicom  # 仅用于读 DICOM metadata（不做像素渲染）— 上传幂等快路径需要
from fastapi import HTTPException

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings

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


# ─── 压缩包识别与解压（ZIP 标准库 / 其余 7-Zip） ───────────────────────────

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


def detect_archive_kind(filename: str) -> Optional[str]:
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


def extract_archive(archive_path: Path, dest_dir: Path, archive_kind: str) -> None:
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


def extract_and_scan_dcm(archive_bytes: bytes, work_dir: Path, archive_kind: str) -> list[Path]:
    """落盘压缩包 → 解压 → 扫描所有 .dcm 文件路径（只扫路径，不读字节）。

    上传路由"解析"阶段的前半段（Round 6 下沉）：
      1) 用原始扩展名落盘，让 7-Zip 自动识别格式
      2) 解压到 work_dir/extracted（解压失败由 extract_archive 抛 HTTPException 400）
      3) rglob 找出全部 .dcm 路径返回（找不到时返回空列表，由路由层抛 400）
    """
    archive_path = work_dir / f"source.{archive_kind}"
    archive_path.write_bytes(archive_bytes)
    extract_dir = work_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_archive(archive_path, extract_dir, archive_kind)
    return [
        f for f in extract_dir.rglob("*")
        if f.is_file() and f.suffix.lower() == ".dcm"
    ]


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
