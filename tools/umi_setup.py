#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
umi_setup.py —— Umi-OCR 检查 / 下载 / 启动助手

Umi-OCR 是独立软件，不在本仓库里（便携版约 200MB，不适合塞进 Git）。
本脚本负责三件事：

  1) 检查：Umi-OCR 的 HTTP 服务（默认 127.0.0.1:1224）是否可用、exe 在哪
  2) 下载：从官方 GitHub Releases 取 Windows 便携版，解压到 tools/_umi/
  3) 启动：把找到的 Umi-OCR.exe 拉起来（供其它脚本随后调用 HTTP API）

官方地址
    仓库：https://github.com/hiroi-sora/Umi-OCR
    下载：https://github.com/hiroi-sora/Umi-OCR/releases

用法：
    py tools/umi_setup.py --check               # 只看状态，不动任何东西
    py tools/umi_setup.py --download            # 检查不到就下载便携版
    py tools/umi_setup.py --download --start    # 下载完顺便启动
    py tools/umi_setup.py --start               # 只启动已找到的 exe

注意：下载的是第三方开源软件，体积较大（约 200MB），请确认网络与磁盘空间。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "_umi")          # 便携版解压到这里（已在 .gitignore 中）
UMI_BASE = os.environ.get("UMI_OCR_API", "http://127.0.0.1:1224")

OFFICIAL_REPO = "https://github.com/hiroi-sora/Umi-OCR"
OFFICIAL_RELEASES = "https://github.com/hiroi-sora/Umi-OCR/releases"
API_LATEST = "https://api.github.com/repos/hiroi-sora/Umi-OCR/releases/latest"


def log(msg):
    print(msg, file=sys.stderr)


# ------------------------------------------------------------------ 查找 / 检查

def service_ready(timeout=3):
    """Umi-OCR 的 HTTP 服务是否在监听（这是所有脚本真正依赖的东西）。"""
    try:
        urllib.request.urlopen(UMI_BASE + "/api/ocr/get_options", timeout=timeout).read()
        return True
    except Exception:
        return False


def find_exe():
    """按优先级找 Umi-OCR.exe：缓存目录 → 环境变量 → 常见安装位置。找不到返回 None。"""
    cands = []
    if os.path.isdir(CACHE_DIR):
        for root, _dirs, files in os.walk(CACHE_DIR):
            for f in files:
                if f.lower() == "umi-ocr.exe":
                    cands.append(os.path.join(root, f))
    env_exe = os.environ.get("UMI_OCR_EXE")
    if env_exe:
        cands.append(env_exe)
    for root in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"),
                 os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("SystemDrive", "C:") + "\\"):
        if not root:
            continue
        cands += [os.path.join(root, "Umi-OCR", "Umi-OCR.exe"),
                  os.path.join(root, "Umi-OCR_Paddle", "Umi-OCR.exe")]
    cands += [os.path.join(HERE, "Umi-OCR", "Umi-OCR.exe"),
              # 本机开发时工作区里的便携版（Zotero 工作区/Umi-OCR_Paddle_v2.1.5）
              os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                           "Umi-OCR_Paddle_v2.1.5", "Umi-OCR.exe")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def status():
    ok_srv, exe = service_ready(), find_exe()
    log("Umi-OCR 状态")
    log(f"  HTTP 服务（{UMI_BASE}）：{'可用 ✅' if ok_srv else '不可用 ❌'}")
    log(f"  可执行文件：{exe or '未找到'}")
    if not ok_srv and not exe:
        log("")
        log("  需要装一个 Umi-OCR（开源、免费）：")
        log(f"    官方仓库：{OFFICIAL_REPO}")
        log(f"    下载页面：{OFFICIAL_RELEASES}")
        log("    或直接让我下：py tools/umi_setup.py --download")
        log("    装完记得在 Umi-OCR 里开启「HTTP 服务」（默认端口 1224）。")
    elif not ok_srv and exe:
        log("")
        log(f"  已找到程序但服务没开，先启动它：py tools/umi_setup.py --start")
    return ok_srv, exe


# ------------------------------------------------------------------ 下载

def _pick_asset(assets):
    """从 Release 资产里挑 Windows 便携版 zip：优先名字带 Paddle 且带 win 的。"""
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    def score(a):
        n = a["name"].lower()
        s = 0
        s += 3 if "win" in n else 0
        s += 2 if "paddle" in n else 0
        s -= 2 if ("rapid" in n or "src" in n or "runtime" in n) else 0
        return (-s, -a.get("size", 0))
    zips.sort(key=score)
    return zips[0] if zips else None


def download(force=False):
    if os.path.isdir(CACHE_DIR) and not force:
        exe = find_exe()
        if exe and exe.startswith(CACHE_DIR):
            log(f"缓存中已有 Umi-OCR：{exe}（要重新下载加 --force）")
            return exe
    log("查询官方最新版本 ...")
    req = urllib.request.Request(API_LATEST, headers={"User-Agent": "zotero-entry/umi-setup"})
    try:
        rel = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    except Exception as e:
        log(f"[!] 取版本信息失败：{e}")
        log(f"    请手动下载：{OFFICIAL_RELEASES}")
        return None
    tag = rel.get("tag_name", "?")
    asset = _pick_asset(rel.get("assets", []))
    if not asset:
        log(f"[!] 该版本没有 Windows zip 资产，请手动下载：{OFFICIAL_RELEASES}")
        return None
    size_mb = round(asset.get("size", 0) / 1024 / 1024, 1)
    log(f"找到 {tag} → {asset['name']}（{size_mb} MB）")
    log("开始下载（来源：GitHub Releases，开源软件，可随时删除 tools/_umi/）...")
    os.makedirs(CACHE_DIR, exist_ok=True)
    zpath = os.path.join(CACHE_DIR, asset["name"])
    try:
        with urllib.request.urlopen(asset["browser_download_url"], timeout=60) as r, \
                open(zpath, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\r  下载中 {pct}%  ({done // 1048576}/{total // 1048576} MB)",
                          end="", file=sys.stderr)
        print("", file=sys.stderr)
    except Exception as e:
        log(f"[!] 下载失败：{e}")
        log(f"    请手动下载：{OFFICIAL_RELEASES}")
        return None
    log("解压中 ...")
    try:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(CACHE_DIR)
    except Exception as e:
        log(f"[!] 解压失败：{e}")
        return None
    exe = find_exe()
    if exe:
        log(f"✅ 已就绪：{exe}")
        log("   提醒：首次运行请在 Umi-OCR 里开启「HTTP 服务」（默认 127.0.0.1:1224）。")
    else:
        log("[!] 解压完没找到 Umi-OCR.exe，请手动检查 tools/_umi/ 目录。")
    return exe


# ------------------------------------------------------------------ 启动

def start(exe=None, wait_s=60):
    if service_ready():
        log(f"Umi-OCR 服务已在运行（{UMI_BASE}）")
        return True
    exe = exe or find_exe()
    if not exe:
        log("[!] 没找到 Umi-OCR.exe。先跑：py tools/umi_setup.py --download")
        return False
    log(f"启动 Umi-OCR：{exe}")
    # 路径可能含中文，按 UTF-8 解出字符串再交给系统
    target = os.fsdecode(exe) if isinstance(exe, bytes) else exe
    try:
        subprocess.Popen([target])
    except Exception as e:
        log(f"[!] 启动失败：{e}")
        log(f"    可手动双击运行：{target}")
        return False
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(2)
        if service_ready():
            log(f"✅ 服务已就绪（{UMI_BASE}）")
            return True
    log("[!] 等不到服务。请在 Umi-OCR 界面里开启「HTTP 服务」，")
    log(f"    端口若改过，用环境变量告诉脚本：set UMI_OCR_API=http://127.0.0.1:<端口>")
    return False


def main():
    ap = argparse.ArgumentParser(description="Umi-OCR 检查 / 下载 / 启动")
    ap.add_argument("--check", action="store_true", help="只检查状态（默认行为）")
    ap.add_argument("--download", action="store_true", help="下载官方 Windows 便携版到 tools/_umi/")
    ap.add_argument("--force", action="store_true", help="重新下载（覆盖缓存）")
    ap.add_argument("--start", action="store_true", help="启动已找到的 Umi-OCR")
    ap.add_argument("--umi-exe", default=None, help="指定 Umi-OCR.exe 路径")
    args = ap.parse_args()

    if args.download:
        exe = download(force=args.force)
        if exe and args.start:
            start(exe)
        return 0
    if args.start:
        return 0 if start(args.umi_exe) else 1
    ok, _exe = status()
    if not ok:
        log("")
        log("  下一步：py tools/umi_setup.py --download --start")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
