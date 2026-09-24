# -*- coding: utf-8 -*-
"""_conv.py <srcdir> <listfile> <outdir> —— 批量把 PDF 转双层可搜索 PDF(pdfLayered)"""
import sys, os, json, time
import requests

API = "http://127.0.0.1:1224"
srcdir, listfile, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(outdir, exist_ok=True)
names = [l.strip() for l in open(listfile, encoding="utf-8-sig") if l.strip()]

for n in names:
    src = os.path.join(srcdir, n)
    if not os.path.exists(src):
        print("MISSING", n, flush=True); continue
    try:
        with open(src, "rb") as f:
            r = requests.post(API + "/api/doc/upload",
                              files={"file": (n, f, "application/pdf")},
                              data={"json": json.dumps({"doc.extractionMode": "fullPage"})},
                              timeout=300)
        j = r.json()
        if j.get("code") != 100:
            print("UPLOAD FAIL", n, j, flush=True); continue
        mid = j["data"]
        rr = {}
        while True:
            time.sleep(2)
            rr = requests.post(API + "/api/doc/result", json={"id": mid}, timeout=120).json()
            if rr.get("is_done"):
                break
            if rr.get("state") == "failure":
                print("OCR FAIL", n, rr.get("message"), flush=True); break
        if not rr.get("is_done") or rr.get("state") != "success":
            continue
        dd = requests.post(API + "/api/doc/download",
                           json={"id": mid, "file_types": ["pdfLayered"]}, timeout=120).json()
        if dd.get("code") != 100:
            print("DL FAIL", n, dd, flush=True); continue
        data = requests.get(dd["data"], timeout=900).content
        open(os.path.join(outdir, dd["name"]), "wb").write(data)
        print("OK", n, "->", dd["name"], len(data), flush=True)
        requests.get(API + "/api/doc/clear/" + mid, timeout=60)
    except Exception as e:
        print("ERR", n, repr(e)[:150], flush=True)
print("ALL DONE", flush=True)
