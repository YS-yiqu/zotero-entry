# -*- coding: utf-8 -*-
"""_layered.py <pdf> <outdir>
调用 Umi-OCR 文档 API 把 PDF 转成双层可搜索 PDF(pdfLayered)，落盘到 outdir。"""
import sys, os, json, time
import requests

pdf, outdir = sys.argv[1], sys.argv[2]
API = "http://127.0.0.1:1224"
os.makedirs(outdir, exist_ok=True)

with open(pdf, "rb") as f:
    r = requests.post(
        API + "/api/doc/upload",
        files={"file": (os.path.basename(pdf), f, "application/pdf")},
        data={"json": json.dumps({"doc.extractionMode": "fullPage"})},
        timeout=300,
    )
j = r.json()
print("upload:", j.get("code"), j.get("data"))
if j.get("code") != 100:
    sys.exit(1)
mid = j["data"]

while True:
    time.sleep(2)
    rr = requests.post(API + "/api/doc/result", json={"id": mid}, timeout=120).json()
    print("  progress %s/%s state=%s" % (rr.get("processed_count"), rr.get("pages_count"), rr.get("state")))
    if rr.get("is_done"):
        break
    if rr.get("state") == "failure":
        print("FAIL:", rr.get("message")); sys.exit(2)

dd = requests.post(API + "/api/doc/download", json={"id": mid, "file_types": ["pdfLayered"]}, timeout=120).json()
print("download:", dd.get("code"), dd.get("name"))
if dd.get("code") != 100:
    sys.exit(3)
data = requests.get(dd["data"], timeout=600).content
outpath = os.path.join(outdir, dd["name"])
open(outpath, "wb").write(data)
print("saved:", outpath, len(data), "bytes")
requests.get(API + "/api/doc/clear/" + mid, timeout=60)
