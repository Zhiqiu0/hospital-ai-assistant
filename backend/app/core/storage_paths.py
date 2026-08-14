"""上传目录的单一真源（app/core/storage_paths.py）

2026-08-14 第八轮审计新增。起因是一个只靠肉眼极难发现的 bug：

    lab_reports_service.py 在 app/services/ 下（距 backend/ 三层），
    ai_voice_records.py   在 app/api/v1/ 下（距 backend/ 四层），
    两处都写了 `Path(__file__).resolve().parents[3] / "uploads"`。

后者算出 backend/uploads（对），前者算出仓库根 /uploads（错一层）。
容器里 WORKDIR=/app 且代码铺在 /app 下，于是检验报告原图被写到容器根的
`/uploads/...`，而 docker-compose 只挂了 `uploads_data:/app/uploads`：
  · 文件落在容器可写层，**每次 deploy 重建容器全部消失**，
    DB 里的 file_path 从此指向不存在的文件
  · backup.sh 打包的是容器内 /app/uploads，这些原图**一次都没被备份过**，
    异地 OSS 里也没有
  · 目前没有端点回读这些文件（只返回 ocr_text），所以谁都不会发现它们没了

更要命的是那里的路径穿越校验用的是同一个错误的 root，所以它自洽通过、
不报任何错——纯静默写错位置。

「数 parents 层数」这个写法本身就是 bug 源：文件一挪目录、或复制到不同深度，
数字就错，而且错了不会有任何提示。所以统一到这里算一次，谁都不要再自己数。
"""

from pathlib import Path

# 本文件在 backend/app/core/ 下 → parents[2] 即 backend/
BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]

# 所有上传文件的根目录。容器里对应挂载卷 uploads_data:/app/uploads，
# 也是 backup.sh 打包的目录——写到它之外的东西不会被备份、部署即丢。
UPLOADS_ROOT: Path = BACKEND_ROOT / "uploads"


def resolve_upload_path(rel_path: Path | str) -> Path:
    """把相对路径解析成 uploads 下的绝对路径，并确认没有越界。

    Args:
        rel_path: 相对 UPLOADS_ROOT 的路径（如 lab_reports/<eid>/<uuid>.pdf）

    Returns:
        绝对路径。

    Raises:
        ValueError: 解析结果落在 UPLOADS_ROOT 之外（路径穿越）。
    """
    root = UPLOADS_ROOT.resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"路径越界，不在 uploads 之下：{rel_path}")
    return target
