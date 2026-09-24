# -*- coding: utf-8 -*-
"""
zotero_api_import.py —— 通过 Zotero 本地 API 自动建条目并上传 PDF 附件

用途：把「文件 → Zotero 条目」这一步做成全自动（对应分类「000 自动导入测试」的验证场景）。

前置：
  1. Zotero 桌面端运行中，设置 → 高级 → 勾选「允许此计算机上的其他应用程序与 Zotero 通讯」。
  2. Zotero 10+ 写入需授权：POST /api/local/authorize（body {"appName":"..."}，头 Zotero-Server-ID），
     Zotero 会弹「本地 API 授权」窗，点「Always Allow」后返回 {"key":"...","remember":true}，key 可复用。
     Server-ID 可从任意 GET 响应头 Zotero-Server-ID 取。

用法：
  py tools\\zotero_api_import.py --key <API_KEY> --server-id <SID> --collection <COLLECTION_KEY> \\
      --item-json <条目JSON> --pdf <要挂的PDF> [--attach-title <附件标题>]

  条目 JSON 为数组（同 Zotero 写入 API 格式），其中 collections 由本脚本填入 --collection。
"""
import argparse, hashlib, json, os, sys
import requests

BASE = "http://127.0.0.1:23119/api/users/0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", help="本地 API 写入 key（缺省读 tools\\zotero_local_key.json）")
    ap.add_argument("--server-id", help="Zotero-Server-ID（缺省读 tools\\zotero_local_key.json）")
    ap.add_argument("--collection", help="目标分类 key")
    ap.add_argument("--item-json", required=True, help="条目 JSON 文件（数组）")
    ap.add_argument("--pdf", help="要作为附件上传的 PDF")
    ap.add_argument("--attach-title", default=None)
    args = ap.parse_args()

    # 复用已保存的本地写入 key，避免每次都调 /api/local/authorize（会弹窗抢焦点）
    if not args.key or not args.server_id:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zotero_local_key.json")
        if os.path.exists(cfg_path):
            cfg = json.load(open(cfg_path, encoding="utf-8"))
            args.key = args.key or cfg.get("apiKey")
            args.server_id = args.server_id or cfg.get("serverId")
    if not args.key or not args.server_id:
        print("缺少写入 key / Server-ID：先保存 tools\\zotero_local_key.json，或显式传 --key/--server-id")
        sys.exit(2)

    H = {"Zotero-API-Key": args.key, "Zotero-Server-ID": args.server_id}
    items = json.load(open(args.item_json, encoding="utf-8"))
    if args.collection:
        for it in items:
            it["collections"] = [args.collection]

    # 1) 建条目
    r = requests.post(BASE + "/items", headers={**H, "Content-Type": "application/json"},
                      json=items, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("failed"):
        print("建条目失败:", json.dumps(j["failed"], ensure_ascii=False)); sys.exit(1)
    pkey = j["success"]["0"]
    print("父条目 key =", pkey, "| 分类 =", args.collection)

    if not args.pdf:
        return
    # 2) 建子附件条目
    name = os.path.basename(args.pdf)
    size = os.path.getsize(args.pdf)
    md5 = hashlib.md5(open(args.pdf, "rb").read()).hexdigest()
    mtime = int(os.path.getmtime(args.pdf) * 1000)
    att = {
        "itemType": "attachment", "parentItem": pkey, "linkMode": "imported_file",
        "title": args.attach_title or name, "filename": name,
        "contentType": "application/pdf", "collections": [], "tags": [],
    }
    r = requests.post(BASE + "/items", headers={**H, "Content-Type": "application/json"},
                      json=[att], timeout=60)
    r.raise_for_status()
    akey = r.json()["success"]["0"]
    print("附件条目 key =", akey)

    # 3) 三阶段上传
    p1 = requests.post(f"{BASE}/items/{akey}/file",
                       headers={**H, "If-None-Match": "*",
                                "Content-Type": "application/x-www-form-urlencoded"},
                       data={"md5": md5, "filename": name, "filesize": size, "mtime": mtime},
                       timeout=60)
    p1.raise_for_status()
    info = p1.json()
    if info.get("exists"):
        print("服务器已有同 md5 文件，跳过上传"); return
    with open(args.pdf, "rb") as f:
        p2 = requests.post(info["url"], headers={"Content-Type": "application/octet-stream"},
                           data=f, timeout=600)
    p2.raise_for_status()
    p3 = requests.post(f"{BASE}/items/{akey}/file",
                       headers={**H, "If-None-Match": "*",
                                "Content-Type": "application/x-www-form-urlencoded"},
                       data={"upload": info["uploadKey"]}, timeout=300)
    p3.raise_for_status()
    print("附件上传完成，version =", p3.headers.get("Last-Modified-Version"))
    print("提醒：表单上传时文件名里的空格会变成 '+' 并落盘，需要时改名后 PATCH filename 修正。")


if __name__ == "__main__":
    main()
