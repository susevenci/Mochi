"""环境体检（T0-01）。

运行：``python scripts/doctor.py``
检测 Python / Node / pnpm / npm / cargo / WebView2；缺项给出可直接复制的安装命令。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def _first_line(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[0] if lines else ""


def _run(cmd: list[str]) -> tuple[bool, str]:
    exe = shutil.which(cmd[0])
    if exe is None:
        return False, "未安装或不在 PATH"
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=30, shell=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"执行失败: {exc}"
    if proc.returncode != 0:
        return False, _first_line(proc.stderr) or f"退出码 {proc.returncode}"
    return True, _first_line(proc.stdout)


def check_python() -> Check:
    version = platform.python_version()
    ok = sys.version_info >= (3, 11)
    return Check(
        "Python >= 3.11",
        ok,
        version,
        hint="https://www.python.org/downloads/",
    )


def check_node() -> Check:
    ok, detail = _run(["node", "--version"])
    if not ok:
        return Check("Node >= 20", False, detail, hint="https://nodejs.org/")
    try:
        major = int(detail.lstrip("v").split(".")[0])
    except ValueError:
        major = 0
    return Check("Node >= 20", major >= 20, detail, hint="https://nodejs.org/")


def check_pnpm() -> Check:
    ok, detail = _run(["pnpm", "--version"])
    if not ok:
        return Check("pnpm >= 9", False, detail, hint="npm.cmd i -g pnpm")
    try:
        major = int(detail.split(".")[0])
    except ValueError:
        major = 0
    return Check("pnpm >= 9", major >= 9, detail, hint="npm.cmd i -g pnpm")


def check_npm() -> Check:
    """pnpm 缺失时的降级通道（PowerShell 下需用 npm.cmd 绕过执行策略）。"""
    ok, detail = _run(["npm", "--version"])
    return Check("npm（降级通道）", ok, detail, hint="随 Node 安装；PowerShell 请用 npm.cmd")


def check_cargo() -> Check:
    ok, detail = _run(["cargo", "--version"])
    return Check("Rust / cargo", ok, detail, hint="https://rustup.rs/")


def check_webview2() -> Check:
    if platform.system() != "Windows":
        return Check("WebView2 Runtime", True, "非 Windows，跳过")
    import winreg

    guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    locations = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"),
    ]
    for root, path in locations:
        try:
            with winreg.OpenKey(root, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                return Check("WebView2 Runtime", True, str(version))
        except OSError:
            continue
    return Check(
        "WebView2 Runtime",
        False,
        "未检测到",
        hint="https://developer.microsoft.com/microsoft-edge/webview2/",
    )


def main() -> int:
    checks = [
        check_python(),
        check_node(),
        check_pnpm(),
        check_npm(),
        check_cargo(),
        check_webview2(),
    ]
    width = max(len(c.name) for c in checks)
    failures = 0
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"
        print(f"[{mark}] {check.name.ljust(width)}  {check.detail}")
        if not check.ok:
            failures += 1
            if check.hint:
                print(f"       -> {check.hint}")
    print()
    if failures:
        print(f"{failures} 项未通过 —— 修复后再进入 S0 后续任务。")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
