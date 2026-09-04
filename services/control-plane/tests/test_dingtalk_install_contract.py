from pathlib import Path


def test_dingtalk_doctor_reports_b_drive_signature_version_and_process() -> None:
    root = Path(__file__).resolve().parents[3]
    script = (root / "scripts" / "doctor-dingtalk.ps1").read_text(encoding="utf-8")

    assert "B:\\DingDing" in script
    assert "B:\\Apps\\DingTalk" in script
    assert "Get-AuthenticodeSignature" in script
    assert "ProductVersion" in script
    assert "Get-Process" in script
    assert "AppData" in script
