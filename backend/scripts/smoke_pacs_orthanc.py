"""R1 PACS 迁移端到端 smoke：直接调 orthanc_client + pacs.py 的 helper。

不经过 FastAPI 路由，专测 R1 切换后的"业务层 ↔ Orthanc"链路是否真通。
覆盖：STOW 上传、StudyInstanceUID 抽取、元数据聚合、实例列表、WADO 渲染、清理。

跑法：python scripts/smoke_pacs_orthanc.py
依赖：本地 Orthanc 已起（docker compose up -d orthanc），本机能访问 8042。
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

# 让脚本能直接 import app.* （PYTHONPATH 加 backend 根）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from app.api.v1.pacs import (  # type: ignore
    _extract_study_uid_from_stow_response,
    _fetch_study_metadata,
    _list_study_instances,
    _resolve_instance,
    _smart_sample_indices,
)
from app.services.orthanc_client import orthanc_client


def _build_minimal_dcm(study_uid: str, series_uid: str, sop_uid: str, instance_number: int) -> bytes:
    """构造一个最小合法 DCM（8x8 灰度图），返回字节流。

    Orthanc 接收的最小要求：File Meta + Patient + Study + Series + Instance + 像素数据。
    """
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"  # Secondary Capture
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    ds = Dataset()
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    # 必填 patient/study/series 标识
    ds.PatientID = "SMOKE001"
    ds.PatientName = "SMOKE^TEST"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_uid
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.Modality = "OT"  # Other
    ds.BodyPartExamined = "TEST"
    ds.SeriesDescription = "smoke series"
    ds.InstanceNumber = instance_number

    # 像素：8x8 单帧 8-bit
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = 8
    ds.Columns = 8
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(range(64))

    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds, write_like_original=False)
    return buf.getvalue()


async def main() -> int:
    print("== R1 PACS smoke ==")

    # 1) 健康检查
    alive = await orthanc_client.health_check()
    print(f"[1] Orthanc health: {alive}")
    if not alive:
        print("FAIL: Orthanc 未启动或认证失败")
        return 1

    # 2) 构造 3 帧最小 DCM
    study_uid = generate_uid()
    series_uid = generate_uid()
    sop_uids = [generate_uid() for _ in range(3)]
    dcm_list = [_build_minimal_dcm(study_uid, series_uid, sop, idx + 1) for idx, sop in enumerate(sop_uids)]
    print(f"[2] Built {len(dcm_list)} minimal DCM, study_uid={study_uid[:32]}...")

    # 3) STOW 上传
    stow_resp = await orthanc_client.stow_instances(dcm_list)
    print(f"[3] STOW response keys: {list(stow_resp.keys())}")

    # 4) 从响应抽 study_uid（验证 _extract_study_uid_from_stow_response）
    extracted_uid = _extract_study_uid_from_stow_response(stow_resp)
    print(f"[4] Extracted study UID: {extracted_uid}")
    assert extracted_uid == study_uid, f"UID 不一致！期望 {study_uid}，实际 {extracted_uid}"

    try:
        # 5) 元数据聚合
        meta = await _fetch_study_metadata(study_uid)
        print(f"[5] Metadata: {meta}")
        assert meta["modality"] == "OT", f"modality 解析错: {meta}"
        assert meta["body_part"] == "TEST", f"body_part 解析错: {meta}"
        assert meta["total_instances"] == 3, f"实例数错: {meta}"

        # 6) 实例列表（验证 _list_study_instances）
        instances = await _list_study_instances(study_uid)
        print(f"[6] Instance list ({len(instances)} 条):")
        for inst in instances:
            print(f"     - InstanceNumber={inst['instance_number']} uid={inst['instance_uid'][:30]}...")
        assert len(instances) == 3
        # 验证按 InstanceNumber 排序
        nums = [i["instance_number"] for i in instances]
        assert nums == sorted(nums), f"排序失败: {nums}"

        # 7) 智能抽帧（small total → 全返回）
        idx_small = _smart_sample_indices(3)
        print(f"[7a] Small sample (total=3): {idx_small}")
        assert idx_small == [0, 1, 2]
        # 大样本测试
        idx_big = _smart_sample_indices(100)
        print(f"[7b] Big sample (total=100, n=18): {idx_big} (count={len(idx_big)})")
        assert len(idx_big) <= 18
        assert all(0 <= i < 100 for i in idx_big)
        assert idx_big == sorted(idx_big)

        # 8) 反查 series_uid（验证 _resolve_instance）
        resolved = await _resolve_instance(study_uid, sop_uids[0])
        print(f"[8] Resolved series for first instance: {resolved}")
        assert resolved == series_uid

        # 9) WADO render：拉第一帧 JPEG
        jpeg = await orthanc_client.get_instance_rendered(study_uid, series_uid, sop_uids[0])
        print(f"[9] WADO rendered JPEG: {len(jpeg)} bytes (前 4 字节={jpeg[:4]!r})")
        assert jpeg[:3] == b"\xff\xd8\xff", "返回的不是 JPEG"

        # 10) WADO instance：拉原始 DCM
        raw = await orthanc_client.get_instance_dicom(study_uid, series_uid, sop_uids[0])
        print(f"[10] WADO instance DCM: {len(raw)} bytes")
        assert b"DICM" in raw[:200], "返回的不是 DICOM 文件"

        print("\nALL OK")
        return 0
    finally:
        # 11) 清理（重要：smoke 完后必须删，不污染环境）
        deleted = await orthanc_client.delete_study(study_uid)
        print(f"[cleanup] delete_study: {deleted}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
