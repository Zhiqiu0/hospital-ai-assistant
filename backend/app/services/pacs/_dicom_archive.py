# -*- coding: utf-8 -*-
"""
PACS 压缩包识别与解压（services/pacs/_dicom_archive.py）

从 dicom_service.py 拆出的压缩包处理逻辑（纯文件操作，不碰 DB / 请求上下文）：
  - 7-Zip 可执行文件定位（module 加载时一次）+ 模块级缓存 SEVENZIP_PATH
  - detect_archive_kind ：按后缀识别压缩类型（双后缀优先）
  - extract_archive     ：ZIP 走标准库、其余走 7-Zip subprocess
  - extract_and_scan_dcm：落盘 → 解压 → 扫描 .dcm 路径

历史行为（原样保留，调用方路由依赖）：
  - extract_archive 解压失败直接抛 HTTPException(400)
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
from fastapi import HTTPException

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings

logger = logging.getLogger(__name__)


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
