"""lint・整形・型・テストをまとめて実行する（CLAUDE.md 1.2 の「チェックを通す」）。

使い方：uv run python scripts/check.py
1つでも失敗したら、最後に失敗したものを表示して終了コード 1 で終わる。
"""

import subprocess
import sys

CHECKS: list[tuple[str, list[str]]] = [
    ("lint（Ruff）", ["ruff", "check", "."]),
    ("整形（Ruff）", ["ruff", "format", "--check", "."]),
    ("型（mypy）", ["mypy", "."]),
    ("テスト（pytest）", ["pytest"]),
]


def main() -> int:
    failed: list[str] = []
    for name, command in CHECKS:
        print(f"\n=== {name}: {' '.join(command)}", flush=True)
        # 1つ失敗しても残りを続け、まとめて結果を見られるようにする
        if subprocess.run(command, check=False).returncode != 0:  # noqa: S603
            failed.append(name)

    if failed:
        print(f"\n失敗：{'、'.join(failed)}")
        return 1
    print("\nすべて通りました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
