"""稀疏克隆 Live2D 模型到 data/live2d/<模型名>/。

比逐文件下载快得多：一次 partial clone（只取 tree）+ sparse-checkout 目标目录。

用法：
    python scripts/fetch_live2d.py --name qiye_10
    python scripts/fetch_live2d.py --name xuefeng_3 --dest D:\somewhere
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://github.com/Eikanya/Live2d-model.git"
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="模型目录名（如 qiye_10）")
    parser.add_argument("--dest", default="", help="目标目录，默认 data/live2d/<name>")
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args()

    dest = Path(args.dest) if args.dest else DEFAULT_LIVE2D_DIR / args.name
    workdir = Path(tempfile.mkdtemp(prefix="live2d-"))
    repo_dir = workdir / "repo"
    try:
        clone_args = [
            "git", "clone", "--depth", "1", "--filter=blob:none",
            "--no-checkout", args.repo, str(repo_dir),
        ]
        _run(clone_args, cwd=workdir)
        listing = _run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=repo_dir, capture=True
        ).stdout or ""
        lines = listing.splitlines()
        model3 = f"{args.name}.model3.json"
        model2 = f"{args.name}.model.json"
        matches = [line for line in lines if line.endswith(model3)]
        if not matches:
            matches = [line for line in lines if line.endswith(model2)]
        if not matches:
            print(f"仓库中未找到 {args.name}.model3.json")
            return 1
        model_file = matches[0]
        model_dir = model_file.rsplit("/", 1)[0]
        print(f"# 模型目录: {model_dir}")

        _run(["git", "sparse-checkout", "init", "--no-cone"], cwd=repo_dir)
        sparse_file = repo_dir / ".git" / "info" / "sparse-checkout"
        sparse_file.write_text(f"/{model_dir}/\n", encoding="utf-8")
        _run(["git", "sparse-checkout", "reapply"], cwd=repo_dir)

        src = repo_dir / model_dir
        if not src.exists():
            print(f"稀疏检出失败: {src}")
            return 1
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, dirs_exist_ok=True)

        files = [p for p in dest.rglob("*") if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        print(f"# copied {len(files)} files ({total / 1024 / 1024:.1f} MB) -> {dest}")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
