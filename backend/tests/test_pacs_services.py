# -*- coding: utf-8 -*-
"""
services/pacs/ 纯函数单元测试（不依赖 Orthanc / Redis / 网络）

覆盖范围：
  - dicom_service.smart_sample_indices       智能抽帧索引（边界：0/1/少于采样数/大量帧）
  - dicom_service.detect_archive_kind        压缩格式识别（双后缀优先级）
  - dicom_service.read_preflight_study_uid   幂等预检读 StudyInstanceUID（pydicom 造最小 DCM）
  - dicom_service.parse_dicom_files          DCM 元数据批量解析（排序/跳过坏文件）
  - dicom_service.extract_and_scan_dcm       ZIP 解压 + .dcm 路径扫描（Round 6 新增）
  - frame_service.extract_study_uid_from_stow_response  STOW 响应解析（正常/缺字段/畸形）
  - analysis_service.frame_cap_for           modality 自适应帧上限

需要 Orthanc / Redis 的函数（fetch_study_metadata / render_and_cache_all 等）
刻意不在此测试——属于集成测试范畴。
"""
import zipfile

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from app.services.pacs.analysis_service import frame_cap_for
from app.services.pacs.dicom_service import (
    AUTO_SAMPLE_COUNT,
    detect_archive_kind,
    extract_and_scan_dcm,
    parse_dicom_files,
    read_preflight_study_uid,
    smart_sample_indices,
)
from app.services.pacs.frame_service import extract_study_uid_from_stow_response


# ─── 测试工具：用 pydicom 造最小合法 DCM 文件 ────────────────────────────────

def _make_dcm(
    path,
    study_uid="1.2.840.99999.1",
    sop_uid="1.2.840.99999.2",
    series_uid="1.2.840.99999.3",
    instance_number=1,
    include_study_uid=True,
):
    """生成只含元数据的最小合法 DICOM Part-10 文件（无像素数据）。"""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"  # Secondary Capture
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = sop_uid
    if include_study_uid:
        ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.InstanceNumber = instance_number
    ds.save_as(str(path), enforce_file_format=True)
    return path


# ─── smart_sample_indices：智能抽帧索引 ──────────────────────────────────────

class TestSmartSampleIndices:
    def test_零帧返回空列表(self):
        assert smart_sample_indices(0) == []

    def test_单帧返回索引0(self):
        assert smart_sample_indices(1) == [0]

    def test_帧数少于采样数_全取(self):
        # 5 帧 < 默认 18 → 原样返回 0..4
        assert smart_sample_indices(5) == [0, 1, 2, 3, 4]

    def test_帧数恰等于采样数_全取(self):
        assert smart_sample_indices(AUTO_SAMPLE_COUNT) == list(range(AUTO_SAMPLE_COUNT))

    def test_大量帧_数量与范围约束(self):
        result = smart_sample_indices(537)
        # 不超过采样上限、升序、去重、全部在合法索引范围内
        assert len(result) <= AUTO_SAMPLE_COUNT
        assert result == sorted(set(result))
        assert all(0 <= i < 537 for i in result)
        # 从头部（索引 0）开始取
        assert result[0] == 0

    def test_大量帧_中段密集(self):
        # 设计目标：中部 20%-80% 区域取约 2/3 的帧（密集），头尾稀疏
        total = 300
        result = smart_sample_indices(total)
        mid = [i for i in result if total * 0.20 <= i < total * 0.80]
        edge = [i for i in result if i not in mid]
        assert len(mid) > len(edge)

    def test_自定义采样数(self):
        result = smart_sample_indices(100, n=6)
        assert len(result) <= 6
        assert result == sorted(set(result))
        assert all(0 <= i < 100 for i in result)


# ─── detect_archive_kind：压缩格式识别 ───────────────────────────────────────

class TestDetectArchiveKind:
    def test_常见单后缀(self):
        assert detect_archive_kind("study.zip") == "zip"
        assert detect_archive_kind("study.rar") == "rar"
        assert detect_archive_kind("study.7z") == "7z"
        assert detect_archive_kind("disc.iso") == "iso"
        assert detect_archive_kind("pack.tgz") == "tgz"

    def test_大写后缀不区分大小写(self):
        assert detect_archive_kind("STUDY.ZIP") == "zip"
        assert detect_archive_kind("Study.Rar") == "rar"

    def test_双后缀优先匹配(self):
        # .tar.gz 必须识别为 tar.gz（两轮解压），而不是单层 gz
        assert detect_archive_kind("a.tar.gz") == "tar.gz"
        assert detect_archive_kind("a.tar.bz2") == "tar.bz2"
        assert detect_archive_kind("a.tar.xz") == "tar.xz"

    def test_单层gz仍可识别(self):
        assert detect_archive_kind("a.gz") == "gz"

    def test_不支持的格式返回None(self):
        assert detect_archive_kind("image.dcm") is None
        assert detect_archive_kind("report.pdf") is None

    def test_无后缀与空文件名返回None(self):
        assert detect_archive_kind("noext") is None
        assert detect_archive_kind("") is None


# ─── extract_study_uid_from_stow_response：STOW-RS 响应解析 ─────────────────

def _stow_resp(url):
    """构造含单个 ReferencedSOPSequence 项的 STOW-RS DICOM JSON 响应。"""
    return {"00081199": {"Value": [{"00081190": {"Value": [url]}}]}}


class TestExtractStudyUidFromStowResponse:
    def test_正常响应解析出study_uid(self):
        resp = _stow_resp(
            "http://orthanc:8042/dicom-web/studies/1.2.3.4/series/5.6/instances/7.8"
        )
        assert extract_study_uid_from_stow_response(resp) == "1.2.3.4"

    def test_空字典返回None(self):
        assert extract_study_uid_from_stow_response({}) is None

    def test_引用序列为空返回None(self):
        assert extract_study_uid_from_stow_response({"00081199": {"Value": []}}) is None

    def test_缺RetrieveURL返回None(self):
        # 引用项存在但没有 00081190（RetrieveURL）字段
        resp = {"00081199": {"Value": [{"00080018": {"Value": ["1.2.3"]}}]}}
        assert extract_study_uid_from_stow_response(resp) is None

    def test_URL不含studies段返回None(self):
        assert extract_study_uid_from_stow_response(_stow_resp("http://x/y/z")) is None

    def test_URL含两个studies段视为畸形返回None(self):
        # split("/studies/") 得 3 段 → len != 2 → None
        url = "http://x/studies/1.2/studies/3.4"
        assert extract_study_uid_from_stow_response(_stow_resp(url)) is None


# ─── frame_cap_for：modality 自适应帧上限 ────────────────────────────────────

class TestFrameCapFor:
    def test_None与未知类型用默认上限(self):
        assert frame_cap_for(None) == AUTO_SAMPLE_COUNT
        assert frame_cap_for("ZZ") == AUTO_SAMPLE_COUNT

    def test_CT_MR切片多取18帧(self):
        assert frame_cap_for("CT") == 18
        assert frame_cap_for("MR") == 18
        assert frame_cap_for("MRI") == 18

    def test_X光与乳腺只取少量(self):
        assert frame_cap_for("DR") == 4
        assert frame_cap_for("DX") == 4
        assert frame_cap_for("CR") == 4
        assert frame_cap_for("MG") == 4

    def test_超声与血管造影中等(self):
        assert frame_cap_for("US") == 6
        assert frame_cap_for("XA") == 6

    def test_小写modality不区分大小写(self):
        assert frame_cap_for("ct") == 18
        assert frame_cap_for("us") == 6


# ─── read_preflight_study_uid：幂等预检读 StudyInstanceUID ──────────────────

class TestReadPreflightStudyUid:
    def test_合法DCM读出study_uid(self, tmp_path):
        p = _make_dcm(tmp_path / "a.dcm", study_uid="1.2.840.99999.777")
        assert read_preflight_study_uid(p) == "1.2.840.99999.777"

    def test_缺StudyInstanceUID返回None(self, tmp_path):
        p = _make_dcm(tmp_path / "b.dcm", include_study_uid=False)
        assert read_preflight_study_uid(p) is None

    def test_垃圾文件返回None不抛异常(self, tmp_path):
        p = tmp_path / "garbage.dcm"
        p.write_bytes(b"this is not a dicom file at all")
        assert read_preflight_study_uid(p) is None

    def test_文件不存在返回None不抛异常(self, tmp_path):
        assert read_preflight_study_uid(tmp_path / "missing.dcm") is None


# ─── parse_dicom_files：批量元数据解析 ───────────────────────────────────────

class TestParseDicomFiles:
    def test_多文件解析_按instance_number排序(self, tmp_path):
        # 故意乱序生成（instance_number 3 → 1 → 2）
        p1 = _make_dcm(tmp_path / "f1.dcm", sop_uid="1.1.3", instance_number=3)
        p2 = _make_dcm(tmp_path / "f2.dcm", sop_uid="1.1.1", instance_number=1)
        p3 = _make_dcm(tmp_path / "f3.dcm", sop_uid="1.1.2", instance_number=2)
        bytes_list, uids, frames_meta = parse_dicom_files([p1, p2, p3])
        # bytes 与 uids 按读取顺序一一对应
        assert len(bytes_list) == 3
        assert uids == ["1.1.3", "1.1.1", "1.1.2"]
        # frames_meta 按 instance_number 升序（DICOM 切片顺序）
        assert [m["instance_number"] for m in frames_meta] == [1, 2, 3]
        assert [m["instance_uid"] for m in frames_meta] == ["1.1.1", "1.1.2", "1.1.3"]

    def test_frames_meta含series_uid(self, tmp_path):
        p = _make_dcm(tmp_path / "f.dcm", series_uid="2.2.2.2")
        _, _, frames_meta = parse_dicom_files([p])
        assert frames_meta[0]["series_uid"] == "2.2.2.2"

    def test_坏文件跳过_好文件保留(self, tmp_path):
        good = _make_dcm(tmp_path / "good.dcm", sop_uid="3.3.3")
        bad = tmp_path / "bad.dcm"
        bad.write_bytes(b"\x00\x01 not dicom")
        bytes_list, uids, frames_meta = parse_dicom_files([bad, good])
        assert uids == ["3.3.3"]
        assert len(bytes_list) == 1
        assert len(frames_meta) == 1

    def test_全部是坏文件返回三个空列表(self, tmp_path):
        bad = tmp_path / "bad.dcm"
        bad.write_bytes(b"junk")
        assert parse_dicom_files([bad]) == ([], [], [])


# ─── extract_and_scan_dcm：解压 + 扫描 .dcm 路径（Round 6 新增）─────────────

def _make_zip_bytes(entries: dict[str, bytes]) -> bytes:
    """构造内存 ZIP：entries = {zip 内路径: 文件内容}。"""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestExtractAndScanDcm:
    def test_zip解压只返回dcm路径(self, tmp_path):
        archive = _make_zip_bytes({
            "series1/a.dcm": b"fake-a",
            "series1/b.DCM": b"fake-b",      # 大写后缀也要识别
            "readme.txt": b"not dicom",
            "DICOMDIR": b"index",
        })
        paths = extract_and_scan_dcm(archive, tmp_path, "zip")
        names = sorted(p.name.lower() for p in paths)
        assert names == ["a.dcm", "b.dcm"]
        # 解压产物落在 work_dir/extracted 下
        assert all("extracted" in str(p) for p in paths)

    def test_zip无dcm返回空列表(self, tmp_path):
        archive = _make_zip_bytes({"only.txt": b"hello"})
        assert extract_and_scan_dcm(archive, tmp_path, "zip") == []
