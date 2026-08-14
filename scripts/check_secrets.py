"""Fail CI when tracked files appear to contain real credentials."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"^\s*(LLM_API_KEY|EMBEDDING_API_KEY|IMAP_PASSWORD|SMTP_PASSWORD)\s*=\s*(?!your_|你的|example|placeholder|\s*$)[^\s#]{12,}"),
)


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    )
    return [ROOT / item.decode("utf-8") for item in output.split(b"\0") if item]


def main() -> None:
    findings: list[str] = []
    for path in tracked_files():
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ipynb"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "secret-scan: allow" in line:
                continue
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                findings.append(f"{path.relative_to(ROOT)}:{line_number}")
    if findings:
        raise SystemExit("疑似密钥出现在 Git 跟踪文件：\n" + "\n".join(findings))
    print("Secret scan passed")


if __name__ == "__main__":
    main()
