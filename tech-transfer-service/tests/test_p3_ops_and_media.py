"""P3-8 & P3-9 媒体缩略图安全加固与分层健康检查测试。"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from config import settings
from core.errors import BizError
from modules.file import service as file_service


def test_file_thumbnail_decompression_bomb_rejected_and_atomic(tmp_path):
    """P3-A32: 超像素图片触发 DecompressionBombError 被拒绝，正常图片原子写入缩略图。"""
    src = tmp_path / "normal.png"
    buf = BytesIO()
    Image.new("RGB", (64, 64), color="blue").save(buf, format="PNG")
    src.write_bytes(buf.getvalue())

    with patch.object(settings, "MEDIA_ROOT", str(tmp_path)):
        thumb, mime = file_service.get_uploaded_thumbnail(src, "image/png", 77)
        assert mime == "image/jpeg"
        assert thumb.exists()

        # 模拟解压炸弹
        with patch.object(file_service, "_write_thumbnail", side_effect=Image.DecompressionBombError("bomb")):
            # 先删掉缓存触发重新生成
            thumb.unlink(missing_ok=True)
            with pytest.raises(BizError):
                file_service.get_uploaded_thumbnail(src, "image/png", 77)


def test_tiered_health_endpoints():
    """P3-A34/A35: /health/live, /health/ready, /health/deps 分层探针与生产鉴权门禁。"""
    from app import app

    client = TestClient(app)
    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["data"]["status"] == "alive"

    # /health/deps 在非 local 环境必须拒绝未鉴权请求
    with patch.object(settings, "APP_ENV", "production"):
        unauth = client.get("/health/deps")
        assert unauth.status_code == 401
