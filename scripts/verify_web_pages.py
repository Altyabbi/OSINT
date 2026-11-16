"""用 Streamlit AppTest 框架无头逐页执行 app.py，确认每个页面渲染无异常。

用法：conda run -n nli python scripts/verify_web_pages.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(ROOT / "dashboard" / "app.py")
PAGES = ["概览 Dashboard", "数据查询", "数据采集", "日报中心", "智能问答", "系统信息"]


def main() -> None:
    failures = 0
    for page in PAGES:
        at = AppTest.from_file(APP, default_timeout=120)
        at.run()
        if not at.exception:
            at.sidebar.radio[0].set_value(page)
            at.run()
        if at.exception:
            failures += 1
            print(f"[FAIL] {page}: {at.exception[0].value!r}"[:500])
        else:
            print(f"[OK]   {page}（渲染 {len(at.markdown)} 个 markdown 块，无异常）")
    if failures:
        sys.exit(1)
    print("ALL PAGES OK")


if __name__ == "__main__":
    main()
