"""Tests for tenant-scoped demo hardening."""

from app.core.demo_protection import effective_demo_mode, effective_demo_read_only


def test_sam_carbons_exempt_from_demo_hardening(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_READ_ONLY", "true")
    from importlib import reload
    import app.core.config as config_mod

    reload(config_mod)

    assert effective_demo_mode("SAM_CARBONS_DEMO") is False
    assert effective_demo_read_only("SAM_CARBONS_DEMO") is False


def test_video_demo_tenant_inherits_demo_flags(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_READ_ONLY", "true")
    from importlib import reload
    import app.core.config as config_mod

    reload(config_mod)

    assert effective_demo_mode("NYRA_VIDEO_DEMO") is True
    assert effective_demo_read_only("NYRA_VIDEO_DEMO") is True


def test_auto_oem_not_hardened_by_default(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_READ_ONLY", "true")
    from importlib import reload
    import app.core.config as config_mod

    reload(config_mod)

    assert effective_demo_mode("AUTO_OEM_DEMO") is False
    assert effective_demo_read_only("AUTO_OEM_DEMO") is False
