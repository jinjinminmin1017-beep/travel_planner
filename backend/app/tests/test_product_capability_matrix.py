from pathlib import Path

from app.data_sources.config_loader import PROJECT_ROOT, load_data_source_configs


DOC_PATH = Path(PROJECT_ROOT) / "docs" / "old" / "PRODUCT_CAPABILITY_MATRIX.md"


def _doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_product_capability_matrix_has_required_statuses_and_sections():
    content = _doc()

    for status in ["待实现", "进行中", "阻塞于授权", "验收通过"]:
        assert status in content

    for section in ["产品能力矩阵", "Provider 能力矩阵", "自动化 Fixture 边界", "Planner 路线覆盖与边界", "更新规则"]:
        assert section in content


def test_product_capability_matrix_covers_registered_data_sources():
    content = _doc()
    missing = sorted({config.source_id for config in load_data_source_configs("DEV")} - set(_extract_backtick_tokens(content)))

    assert missing == []


def test_product_capability_matrix_documents_fixture_and_route_boundaries():
    content = _doc()

    for required_text in [
        "backend/app/tests/conftest.py",
        "backend/app/tests/test_no_simulated_fallback.py",
        "backend/app/data_sources/data_sources.test.json",
        "不得作为运行时 fallback",
        "上海嘉定南翔格林公馆",
        "青岛金水假日酒店",
        "北京国贸",
        "广州天河体育中心",
        "不登录",
        "不抢票",
        "不下单",
        "不支付",
    ]:
        assert required_text in content


def _extract_backtick_tokens(content: str) -> list[str]:
    tokens: list[str] = []
    parts = content.split("`")
    for index in range(1, len(parts), 2):
        tokens.append(parts[index])
    return tokens
