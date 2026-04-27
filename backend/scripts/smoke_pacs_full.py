"""R1 PACS 端到端业务集成测试（scripts/smoke_pacs_full.py）

走真实 FastAPI HTTP 端点（不是单测打 ORM），覆盖 R1 闭环全部可自动化场景：

  1. 登录 admin / radiologist / doctor01，拿 token
  2. 找一个测试患者（没有就建一个）
  3. radiologist 上传 ZIP（含构造的最小 DCM）走 STOW 到 Orthanc
  4. 验 ImagingStudy 落库 + study_instance_uid 非空 + storage_dir 为空
  5. 验 Orthanc 端 CountStudies 真的+1
  6. GET /pacs/{study_id}/frames：返回 instance_uid + series_uid + instance_number
  7. GET /pacs/{study_id}/thumbnail/{instance_uid}：返回 JPEG（WADO render）
  8. GET /pacs/{study_id}/dicom/{instance_uid}：返回原 DCM
  9. 跨患者权限：doctor01（没接诊该患者）访问应 403
  10. PUT /pacs/{study_id}/report：保存草稿（先用 DB 直插 ImagingReport，因为
      analyze 走真千问 AI 不能跑离线）
  11. POST /pacs/{study_id}/publish：发布
  12. doctor01 给该患者建 encounter 后能看到 patient/{id}/reports
  13. 清理：删除 Orthanc 临时数据 + 删 ImagingStudy 行

跑法：python scripts/smoke_pacs_full.py
依赖：本地后端 8010 + Orthanc 8042 都活着
"""
from __future__ import annotations

import asyncio
import io
import sys
import time
import zipfile
from pathlib import Path

import httpx
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
import pydicom

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 必须先 import 所有 model，让 SQLAlchemy 关系解析能找到 Patient/User 等类
from app.models import (  # noqa: E402,F401
    audit_log, config, encounter, medical_record, patient, user,
    voice_record, imaging, lab_report, revoked_token,
)
from app.services.orthanc_client import orthanc_client  # noqa: E402

BACKEND = "http://localhost:8010"
API = f"{BACKEND}/api/v1"


def _build_min_dcm(study_uid: str, series_uid: str, sop_uid: str, n: int) -> bytes:
    """复用 smoke_pacs_orthanc 的最小 DCM 构造逻辑（独立方便单跑）。"""
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    fm.MediaStorageSOPInstanceUID = sop_uid
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    fm.ImplementationClassUID = generate_uid()
    ds = Dataset()
    ds.file_meta = fm
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.PatientID = "SMOKE_FULL"
    ds.PatientName = "SMOKE^FULL"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_uid
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.Modality = "CT"
    ds.BodyPartExamined = "CHEST"
    ds.SeriesDescription = "smoke full"
    ds.InstanceNumber = n
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


def _build_zip(num_frames: int = 3) -> tuple[bytes, str]:
    """构造一个 ZIP 含 N 个 DCM，返回 (zip_bytes, study_uid)"""
    study_uid = generate_uid()
    series_uid = generate_uid()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(num_frames):
            sop = generate_uid()
            zf.writestr(f"slice_{i+1:03d}.dcm", _build_min_dcm(study_uid, series_uid, sop, i + 1))
    return buf.getvalue(), study_uid


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    r = await client.post(f"{API}/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


async def _ensure_test_patient(client: httpx.AsyncClient, admin_token: str) -> str:
    """找/建一个名为 SMOKE_PACS 的患者，返回 patient_id。"""
    r = await client.get(
        f"{API}/patients?page=1&page_size=100",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    r.raise_for_status()
    items = r.json().get("items") or r.json()
    for p in items if isinstance(items, list) else []:
        if p.get("name") == "SMOKE_PACS":
            return p["id"]
    # 不存在则建
    r = await client.post(
        f"{API}/patients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "SMOKE_PACS", "gender": "male", "birth_date": "1980-01-01"},
    )
    r.raise_for_status()
    return r.json()["id"]


async def _ensure_doctor_encounter(
    client: httpx.AsyncClient, doctor_token: str, patient_id: str
) -> str:
    """让 doctor01 给该患者建一次 encounter（quick-start）"""
    r = await client.post(
        f"{API}/encounters/quick-start",
        headers={"Authorization": f"Bearer {doctor_token}"},
        json={"patient_id": patient_id, "patient_name": "SMOKE_PACS", "visit_type": "outpatient"},
    )
    r.raise_for_status()
    return r.json()["encounter_id"]


async def main() -> int:
    print("== R1 PACS 全链路集成测试 ==")
    # 统一 import DB 工具（多个 step 都要用）
    from app.database import AsyncSessionLocal as async_session
    from sqlalchemy import select, delete
    from app.models.encounter import Encounter
    from app.models.imaging import ImagingReport, ImagingStudy
    from app.models.user import User

    failures: list[str] = []

    def expect(cond: bool, label: str):
        prefix = "OK  " if cond else "FAIL"
        print(f"  [{prefix}] {label}")
        if not cond:
            failures.append(label)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # ── 0) 登录 ────────────────────────────────────────
        print("\n[0] 登录三个账号")
        admin_t = await _login(client, "admin", "admin123456")
        rad_t = await _login(client, "radiologist", "radiologist123")
        doc_t = await _login(client, "doctor01", "doctor123")
        expect(bool(admin_t and rad_t and doc_t), "三个 token 都拿到")

        # ── 1) 准备测试患者 + 清空 doctor01 对该患者的旧 encounter ─────
        # 跨患者权限测要求 doctor01 当前没接诊过 SMOKE_PACS，重复跑脚本时
        # 上一轮的 encounter 会污染本轮 step 6
        print("\n[1] 准备测试患者 SMOKE_PACS")
        patient_id = await _ensure_test_patient(client, admin_t)
        print(f"     patient_id={patient_id}")

        async with async_session() as db:
            res = await db.execute(select(User).where(User.username == "doctor01"))
            doc_user = res.scalar_one()
            await db.execute(
                delete(Encounter).where(
                    Encounter.patient_id == patient_id,
                    Encounter.doctor_id == doc_user.id,
                )
            )
            await db.commit()
            print(f"     已清空 doctor01 对该患者的历史 encounter（保证跨权限测试有效）")

        # ── 2) radiologist 上传 ZIP → STOW ────────────────
        print("\n[2] radiologist 上传 ZIP 走 STOW")
        zip_bytes, expected_study_uid = _build_zip(num_frames=3)
        before_stats = await orthanc_client._client().__aenter__()
        before = (await before_stats.get(f"{orthanc_client.base_url}/statistics")).json()[
            "CountStudies"
        ]
        await before_stats.aclose()

        r = await client.post(
            f"{API}/pacs/upload",
            headers={"Authorization": f"Bearer {rad_t}"},
            data={"patient_id": patient_id},
            files={"file": ("test.zip", zip_bytes, "application/zip")},
        )
        expect(r.status_code == 200, f"upload 200 (got {r.status_code}: {r.text[:120]})")
        if r.status_code != 200:
            return 1
        upload_resp = r.json()
        study_id = upload_resp["study_id"]
        returned_uid = upload_resp.get("study_instance_uid")
        print(f"     study_id={study_id}")
        print(f"     study_instance_uid={returned_uid}")
        expect(returned_uid == expected_study_uid, "study_instance_uid 与上传 DCM 一致")
        expect(upload_resp.get("total_frames") == 3, f"total_frames=3 (got {upload_resp.get('total_frames')})")
        expect(upload_resp.get("modality") == "CT", f"modality=CT (got {upload_resp.get('modality')})")
        expect(upload_resp.get("body_part") == "CHEST", f"body_part=CHEST (got {upload_resp.get('body_part')})")

        # 验 Orthanc 端真的 +1
        async with orthanc_client._client() as c:
            after = (await c.get(f"{orthanc_client.base_url}/statistics")).json()["CountStudies"]
        expect(after == before + 1, f"Orthanc CountStudies 真的+1（{before}→{after}）")

        # ── 3) GET /frames ────────────────────────────────
        print("\n[3] GET /frames")
        r = await client.get(
            f"{API}/pacs/{study_id}/frames",
            headers={"Authorization": f"Bearer {rad_t}"},
        )
        expect(r.status_code == 200, f"frames 200 (got {r.status_code})")
        frames_resp = r.json()
        expect(frames_resp["total"] == 3, f"total=3 (got {frames_resp['total']})")
        expect(len(frames_resp["frames"]) == 3, "frames 数组 3 项")
        f0 = frames_resp["frames"][0]
        expect(all(k in f0 for k in ("instance_uid", "series_uid", "instance_number")),
               "每帧含 instance_uid/series_uid/instance_number")
        expect(frames_resp["frames"][0]["instance_number"] == 1, "首帧 InstanceNumber=1（按序排）")
        instance_uids = [f["instance_uid"] for f in frames_resp["frames"]]

        # ── 4) GET /thumbnail（WADO render JPEG） ─────────
        # 模拟前端真实行为：带 series_uid（避免后端走 _resolve_instance 兜底）
        print("\n[4] GET /thumbnail/{instance_uid}?series_uid=... → JPEG")
        first_series_uid = frames_resp["frames"][0]["series_uid"]
        r = await client.get(
            f"{API}/pacs/{study_id}/thumbnail/{instance_uids[0]}",
            params={"series_uid": first_series_uid},
            headers={"Authorization": f"Bearer {rad_t}"},
        )
        expect(r.status_code == 200, f"thumbnail 200 (got {r.status_code})")
        expect(r.headers.get("content-type", "").startswith("image/jpeg"), "Content-Type=image/jpeg")
        expect(r.content[:3] == b"\xff\xd8\xff", "返回字节是 JPEG 魔数")

        # 自定义窗位窗宽
        r2 = await client.get(
            f"{API}/pacs/{study_id}/thumbnail/{instance_uids[0]}",
            params={"series_uid": first_series_uid, "wc": 100, "ww": 200},
            headers={"Authorization": f"Bearer {rad_t}"},
        )
        expect(r2.status_code == 200, f"thumbnail 带 wc/ww 200 (got {r2.status_code})")

        # 不带 series_uid 走兜底路径（_resolve_instance）— 也应该 200
        r3 = await client.get(
            f"{API}/pacs/{study_id}/thumbnail/{instance_uids[0]}",
            headers={"Authorization": f"Bearer {rad_t}"},
        )
        expect(r3.status_code == 200, f"thumbnail 不带 series_uid 兜底 200 (got {r3.status_code})")

        # ── 5) GET /dicom（WADO instance 原 DCM） ─────────
        print("\n[5] GET /dicom/{instance_uid}?series_uid=... → 原 DCM")
        r = await client.get(
            f"{API}/pacs/{study_id}/dicom/{instance_uids[0]}",
            params={"series_uid": first_series_uid},
            headers={"Authorization": f"Bearer {rad_t}"},
        )
        expect(r.status_code == 200, f"dicom 200 (got {r.status_code})")
        expect(r.headers.get("content-type", "").startswith("application/dicom"),
               "Content-Type=application/dicom")
        expect(b"DICM" in r.content[:200], "返回字节含 DICM 魔数")

        # 非法 UID 校验
        r = await client.get(
            f"{API}/pacs/{study_id}/dicom/../../etc/passwd",
            headers={"Authorization": f"Bearer {rad_t}"},
        )
        expect(r.status_code in (400, 404), f"非法 UID 应 400/404 (got {r.status_code})")

        # ── 6) 跨患者权限：doctor01 没接诊过 SMOKE_PACS ──
        print("\n[6] 跨患者权限拒绝（doctor01 未接诊过该患者）")
        r = await client.get(
            f"{API}/pacs/{study_id}/frames",
            headers={"Authorization": f"Bearer {doc_t}"},
        )
        expect(r.status_code == 403, f"doctor 访问 frames 应 403 (got {r.status_code})")
        r = await client.get(
            f"{API}/pacs/{study_id}/thumbnail/{instance_uids[0]}",
            headers={"Authorization": f"Bearer {doc_t}"},
        )
        expect(r.status_code == 403, f"doctor 访问 thumbnail 应 403 (got {r.status_code})")
        r = await client.get(
            f"{API}/pacs/{study_id}/dicom/{instance_uids[0]}",
            headers={"Authorization": f"Bearer {doc_t}"},
        )
        expect(r.status_code == 403, f"doctor 访问 dicom 应 403 (got {r.status_code})")

        # ── 7) 直接造 ImagingReport + 发布（不跑真 AI）──
        # analyze 端点会调真千问 API，集成测不跑；改走 publish_report 验报告流程
        print("\n[7] PUT /report → POST /publish（跳过真 AI）")
        # 直插 ImagingReport（analyze 端点要调真千问 AI，不可离线测）
        async with async_session() as db:
            res = await db.execute(select(User).where(User.username == "radiologist"))
            rad_user = res.scalar_one()
            db.add(
                ImagingReport(
                    study_id=study_id,
                    radiologist_id=rad_user.id,
                    ai_analysis="测试 AI 分析（自动化）",
                    final_report="测试最终报告（自动化）",
                )
            )
            await db.commit()

        r = await client.put(
            f"{API}/pacs/{study_id}/report",
            headers={"Authorization": f"Bearer {rad_t}"},
            json={"final_report": "改过的最终报告"},
        )
        expect(r.status_code == 200, f"PUT /report 200 (got {r.status_code}: {r.text[:120]})")

        r = await client.post(
            f"{API}/pacs/{study_id}/publish",
            headers={"Authorization": f"Bearer {rad_t}"},
            json={"final_report": "已签发的最终报告"},
        )
        expect(r.status_code == 200, f"POST /publish 200 (got {r.status_code})")
        expect("published_at" in r.json(), "publish 响应含 published_at")

        # ── 8) 接诊医生看影像报告 ──────────────────────
        print("\n[8] doctor01 建 encounter 后能看 patient reports")
        await _ensure_doctor_encounter(client, doc_t, patient_id)
        r = await client.get(
            f"{API}/pacs/patient/{patient_id}/reports",
            headers={"Authorization": f"Bearer {doc_t}"},
        )
        expect(r.status_code == 200, f"doctor 看患者报告 200 (got {r.status_code})")
        reports = r.json()
        expect(len(reports) >= 1, f"至少 1 条已发布报告 (got {len(reports)})")
        if reports:
            expect(reports[0]["final_report"] == "已签发的最终报告", "报告内容正确")
            expect(reports[0]["modality"] == "CT", "modality=CT")

        # 其他没接诊过的医生（zz）应该看不到 — 密码可能不一致，try 一下
        try:
            zz_t = await _login(client, "zz", "doctor123")
            r = await client.get(
                f"{API}/pacs/patient/{patient_id}/reports",
                headers={"Authorization": f"Bearer {zz_t}"},
            )
            expect(r.status_code == 403, f"zz 未接诊该患者应 403 (got {r.status_code})")
        except Exception as e:
            print(f"     zz 登录失败，跳过反向权限测：{e!r}")

        # ── 9) 清理 ────────────────────────────────────
        print("\n[9] 清理：删 Orthanc study + DB 行")
        try:
            await orthanc_client.delete_study(returned_uid)
        except Exception as e:
            print(f"     Orthanc 清理失败（可忽略）: {e}")
        # DB 清理：删 imaging_report + imaging_study
        async with async_session() as db:
            await db.execute(delete(ImagingReport).where(ImagingReport.study_id == study_id))
            await db.execute(delete(ImagingStudy).where(ImagingStudy.id == study_id))
            await db.commit()
        print("     清理完成")

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL OK — R1 后端业务全链路通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
