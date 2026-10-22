r"""按模型名抓取 Live2D 模型到 data/live2d/<模型名>/。

做法分两步，避免 git 稀疏检出的逐 blob 拉取（GitHub 限速时极慢）：

1. **只克隆元数据**（``--filter=blob:none --no-checkout``），用 ``git ls-tree`` 找到
   模型目录与其中的文件清单；
2. **逐文件从 CDN 下载**（默认 jsDelivr，失败时回落到 raw.githubusercontent）。

用法：
    python scripts/fetch_live2d.py --name qiye_10
    python scripts/fetch_live2d.py --name qiye_10 --dest D:\somewhere
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "Eikanya/Live2d-model"
REPO_URL = f"https://github.com/{REPO}.git"
BRANCH = "master"
CDN_TEMPLATE = "https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}"
RAW_TEMPLATE = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"
UA = {"User-Agent": "mochi-live2d-fetcher"}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE2D_DIR = PROJECT_ROOT / "data" / "live2d"


def _run(cmd: list[str], cwd: Path, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print(">", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) if capture else subprocess.run(cmd, cwd=str(cwd), check=True, text=True)


def _download(url: str, timeout: float = 300.0) -> bytes:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _fetch_file(repo_path: str, retries: int = 3) -> bytes:
    quoted = urllib.parse.quote(repo_path)
    urls = [
        CDN_TEMPLATE.format(repo=REPO, branch=BRANCH, path=quoted),
        RAW_TEMPLATE.format(repo=REPO, branch=BRANCH, path=quoted),
    ]
    last: Exception | None = None
    for url in urls:
        for attempt in range(retries):
            try:
                return _download(url)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                print(f"  ! {url} 第 {attempt + 1} 次失败: {exc}")
    raise RuntimeError(f"下载失败: {repo_path}: {last}")


def _list_repo_files(repo_dir: Path) -> list[str]:
    listing = _run(
        ["git", "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=repo_dir,
        capture=True,
    ).stdout or ""
    return [line for line in listing.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="模型目录名（如 qiye_10）")
    parser.add_argument("--dest", default="", help="目标目录，默认 data/live2d/<name>")
    parser.add_argument("--repo-url", default=REPO_URL)
    args = parser.parse_args()

    dest = Path(args.dest) if args.dest else DEFAULT_LIVE2D_DIR / args.name
    workdir = Path(tempfile.mkdtemp(prefix="live2d-"))
    repo_dir = workdir / "repo"
    try:
        _run(
            [
                "git", "-c", "core.quotepath=false", "clone", "--depth", "1",
                "--filter=blob:none", "--no-checkout", args.repo_url, str(repo_dir),
            ],
            cwd=workdir,
        )
        files = _list_repo_files(repo_dir)
        model3 = f"{args.name}.model3.json"
        model2 = f"{args.name}.model.json"
        matches = [f for f in files if f.endswith(model3)]
        if not matches:
            matches = [f for f in files if f.endswith(model2)]
        if not matches:
            print(f"仓库中未找到 {model3}")
            return 1
        model_dir = matches[0].rsplit("/", 1)[0]
        print(f"# 模型目录: {model_dir}")

        wanted = [f for f in files if f.startswith(f"{model_dir}/")]
        dest.mkdir(parents=True, exist_ok=True)
        total = 0
        for index, repo_path in enumerate(wanted, start=1):
            relative = repo_path[len(model_dir) + 1 :]
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size > 0:
                print(f"[{index}/{len(wanted)}] 跳过（已存在）{relative}")
                continue
            data = _fetch_file(repo_path)
            target.write_bytes(data)
            total += len(data)
            print(f"[{index}/{len(wanted)}] {relative} ({len(data) / 1024:.0f} KB)")
        print(f"# 完成：{len(wanted)} 个文件，{total / 1024 / 1024:.1f} MB -> {dest}")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
