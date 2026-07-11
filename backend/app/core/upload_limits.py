"""上传大小限制（core/upload_limits.py）

各上传端点原本直接 `await file.read()` 把整个文件读进内存、无任何上限，
几十 MB 的长录音 / 大 DICOM 压缩包会一次性吃满内存并阻塞事件循环。
这里统一提供「分块读取 + 超限即拒」的 helper：读到超过上限立刻抛 413，
不把超大文件整体载入内存。nginx 侧已有 client_max_body_size 兜底，这是应用层双保险。
"""
from fastapi import HTTPException, UploadFile

# 各类上传的体积上限（字节）
MAX_AUDIO_BYTES = 50 * 1024 * 1024      # 录音：50MB（够一次长问诊）
MAX_LAB_BYTES = 20 * 1024 * 1024        # 检验报告图片/PDF：20MB
MAX_DICOM_BYTES = 100 * 1024 * 1024     # DICOM 压缩包：100MB

_CHUNK = 1024 * 1024  # 每次读 1MB


async def read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """分块读取上传文件，累计超过 max_bytes 立即抛 413，不整体载入超大文件。

    Args:
        file:      FastAPI UploadFile。
        max_bytes: 允许的最大字节数。

    Returns:
        文件完整字节内容（未超限时）。

    Raises:
        HTTPException(413): 超过上限。
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，上限 {max_bytes // (1024 * 1024)}MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)
