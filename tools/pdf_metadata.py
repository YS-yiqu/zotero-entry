#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pdf_metadata.py —— 「AI + Zotero + Umi-OCR」第二步：OCR 首尾页 + 抽取元数据候选

分工：本脚本只做"确定性"的部分，把"需要判断"的部分留给 AI/人。
      1) 渲染首页 N 页 + 末页 M 页（300dpi）
      2) 调 Umi-OCR HTTP API（默认 127.0.0.1:1224）逐页 OCR
      3) 抽取候选字段：标准号 / 中英文名称 / 发布实施日期 / 代替标准 /
         起草单位 / 主要起草人 / 归口单位 / ICS / CCS / 发布单位 / 参考文献
      4) 落盘 JSON（含逐页 OCR 全文，供 AI 复核定稿）

前置：Umi-OCR 已启动（.settings: server.enable=true, port=1224）。
      加 --autostart 时，脚本会在服务不可用时自己拉起 Umi-OCR
      （exe 位置取 --umi-exe，或环境变量 UMI_OCR_EXE，或常见安装路径）。

用法：
    python pdf_metadata.py <pdf> [--head 4] [--tail 2] [--dpi 300] [--out out.json]
    python pdf_metadata.py <pdf> --autostart --umi-exe "<Umi-OCR 安装目录>/Umi-OCR.exe"
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

try:
    import fitz
except ImportError:
    print("需要 PyMuPDF：py -3 -m pip install pymupdf", file=sys.stderr)
    raise

# 复用同目录的 umi_setup.py（检查/下载/启动 Umi-OCR 都归它管）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import umi_setup
except Exception:                                    # 单文件拷贝使用时的兜底
    umi_setup = None


def find_umi_exe():
    """找 Umi-OCR.exe：优先问 umi_setup（缓存目录/环境变量/常见位置）。"""
    if umi_setup is not None:
        exe = umi_setup.find_exe()
        if exe:
            return exe
    return os.environ.get("UMI_OCR_EXE")


UMI_BASE = (umi_setup.UMI_BASE if umi_setup is not None
            else os.environ.get("UMI_OCR_API", "http://127.0.0.1:1224"))
UMI_API = UMI_BASE + "/api/ocr"

# ---------------------------------------------------------------- OCR

def ocr_ready(timeout=3):
    if umi_setup is not None:
        return umi_setup.service_ready(timeout=timeout)
    try:
        urllib.request.urlopen(UMI_BASE + "/api/ocr/get_options", timeout=timeout).read()
        return True
    except Exception:
        return False


def ensure_umi(exe=None, wait_s=60, autostart=True):
    """确认 Umi-OCR HTTP 服务可用；autostart 为真且找到 exe 时尝试拉起。"""
    if ocr_ready():
        return True
    if autostart:
        if umi_setup is not None:
            return umi_setup.start(exe=exe, wait_s=wait_s)
        exe = exe or find_umi_exe()
        if exe and os.path.exists(exe):
            print(f"[i] 启动 Umi-OCR：{exe}", file=sys.stderr)
            subprocess.Popen([exe])
            t0 = time.time()
            while time.time() - t0 < wait_s:
                time.sleep(2)
                if ocr_ready():
                    return True
    print("[!] Umi-OCR 服务不可用（默认端口 1224）。", file=sys.stderr)
    print("    先检查/安装：py tools/umi_setup.py --check", file=sys.stderr)
    print("    自动下载并启动：py tools/umi_setup.py --download --start", file=sys.stderr)
    return False


def ocr_image(png_path, language="models/config_chinese.txt",
              parser="single_para", timeout=300):
    """返回 (文本, 耗时秒)。parser: single_para 单栏按自然段 / multi_para 多栏。"""
    b64 = base64.b64encode(open(png_path, "rb").read()).decode()
    body = json.dumps({
        "base64": b64,
        "options": {"data.format": "text", "ocr.language": language,
                    "tbpu.parser": parser},
    }).encode()
    req = urllib.request.Request(UMI_API, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
    return (r.get("data") or ""), time.time() - t0


# ---------------------------------------------------------------- 渲染

def render_pages(pdf, pages, outdir, dpi=300, tag="meta"):
    os.makedirs(outdir, exist_ok=True)
    doc = fitz.open(pdf)
    out = []
    for p in pages:
        if 0 <= p < doc.page_count:
            png = os.path.join(outdir, f"{tag}_p{p + 1:03d}.png")
            doc[p].get_pixmap(dpi=dpi).save(png)
            out.append((p, png))
    doc.close()
    return out


# ---------------------------------------------------------------- 抽取

BOILER = ["中华人民共和国国家标准", "中华人民共和国国家军用标准", "国家计量检定规程",
          "中华人民共和国国家计量检定规程", "中华人民共和国能源行业标准",
          "中华人民共和国机械行业标准", "国家标准", "国家军用标准", "团体标准"]

# 封面上的"单位"黑名单：这些是发布机构，不是起草单位
PUBLISHER_WORDS = ["国家市场监督管理总局", "国家标准化管理委员会", "国家质量监督检验检疫总局",
                   "国家技术监督局", "国家能源局", "中央军委装备发展部", "生态环境部",
                   "中华人民共和国", "发布", "实施"]

# 版式里会混进"起草单位：…"行尾的噪声词
TAIL_NOISE = re.compile(r"(并?归口|提出|发布|实施|请注意|本文件|本标准|本规程).*$")


def tight(text):
    """压掉换行/空白，方便跨行取字段。"""
    return re.sub(r"[ \t\u3000]+", " ", text)


# OCR 常把数字/连字符识别成全角或异体（"2０99-０１-0０１发布"），
# 抽取前统一成 ASCII，否则日期一类字段整条抽不出来。
_FULLWIDTH = "０１２３４５６７８９"
_DIGITS = {ord(c): str(i) for i, c in enumerate(_FULLWIDTH)}
# 注意：不动"—"（一字线是标准号的正确写法，见标准书写规范）
_PUNCT = {ord("－"): "-", ord("–"): "-", ord("〜"): "～",
          ord("（"): "(", ord("）"): ")", ord("："): ":", ord("，"): ",",
          ord("．"): ".", ord("／"): "/"}


def normalize(text):
    return text.translate(_DIGITS).translate(_PUNCT)


def _date_before_label(text, label):
    """在"发布/实施"这类标签前面找最近的日期，容忍 OCR 噪声。

    OCR 会把封面的日期认成 "2０99-０１-0０１发布"（全角混排）或 "20999-06-01实施"
    （年份被多认一位）。所以这里从标签往前找最近的一段数字，把**最后一组**当
    年月日处理，返回归一化后的 YYYY-MM-DD；实在取不到就返回 None。
    """
    for m in re.finditer(label, text):
        seg = text[max(0, m.start() - 28):m.start()]
        groups = re.findall(r"\d+", seg)
        if len(groups) < 3:
            continue
        nums = groups[-3:]
        year = nums[0]
        if len(year) < 4:
            continue
        year = year[:4]                       # "20999" → "2099"
        mon, day = nums[1].zfill(2)[:2], nums[2].zfill(2)[:2]
        return f"{year}-{mon}-{day}"
    return None


def extract_fields(pages_text, tail_from=None):
    """pages_text: [(page_index, text)]；tail_from: 后 N 页起始索引（用于限定参考文献页）。"""
    ordered = sorted(pages_text)
    # 先规范化（全角数字/标点 → ASCII），再做任何正则匹配
    flat = normalize(tight("\n".join(t for _, t in ordered)))
    oneline = re.sub(r"\n", "", flat)
    compact = re.sub(r"\s+", "", flat)

    f = {}

    # --- 标准号：取"本文件的号"，不是它代替的那个号
    # （OCR 常把封面 "JJG 1033—2007" 与 "代替 JJG 198-1994" 混在一起，先扣掉被代替号）
    std_pat = (r"((?:GB|GJB|GB/Z|NB|JJG|JJF|HB|QJ|DL|SY|SH|HG|TB|YD|T/[A-Z]{2,6})"
               r"\s*/?\s*[A-Z]{0,3}\s*\d+(?:\.\d+)*\s*[—\-–－]\s*\d{4})")
    replaced = re.search(r"代替\s*" + std_pat, flat)
    replaced_no = re.sub(r"\s+", "", replaced.group(1)) if replaced else None
    pool = [m for m in re.finditer(std_pat, oneline)]
    if replaced_no:
        pool = [m for m in pool if re.sub(r"\s+", "", m.group(1)) != replaced_no] or pool
    if pool:
        m = pool[0]
        f["standard_number_raw"] = m.group(1).strip()
        f["standard_number"] = re.sub(r"\s+", "", m.group(1)).replace("—", "-") \
            .replace("–", "-").replace("－", "-")
    if replaced_no:
        f["replaces"] = replaced_no

    # --- 中文名称候选（封面最长中文行，排除套话/目录行）
    cand = []
    for line in flat.split("\n"):
        s = line.strip()
        if not (4 <= len(s) <= 30) or not re.search(r"[\u4e00-\u9fff]", s):
            continue
        if any(b in s for b in BOILER) or re.search(r"\d{3,}", s):
            continue
        if any(k in s for k in ["发布", "实施", "代替", "ICS", "CCS", "分类号", "目次",
                                "前言", "范围", "参考文献", "·", "…"]):
            continue
        if s.count(" ") > 1 or re.search(r"\.{3,}", s):
            continue
        cand.append(s)
    if cand:
        f["title_candidates"] = cand[:6]

    # --- 英文名称
    en = re.findall(r"[A-Za-z][A-Za-z0-9 ,\-\(\)/]{25,140}", flat)
    en = [e.strip() for e in en
          if len(e.split()) >= 5 and not re.search(r"GB|NB|IAEA|IEEE|ANSI", e)]
    if en:
        f["title_en_candidates"] = en[:3]

    # --- 发布 / 实施日期（先用严格正则，OCR 噪声大时退回"标签前找日期"）
    f["date_issued"] = _date_before_label(flat, r"发布")
    f["date_implemented"] = _date_before_label(flat, r"实施")
    if not f["date_issued"]:
        f.pop("date_issued", None)
    if not f["date_implemented"]:
        f.pop("date_implemented", None)

    # --- 代替 / 历次版本
    m = re.search(r"代替\s*([A-Z][A-Za-z/]*\s*\d+(?:\.\d+)*\s*[—\-–]\s*\d{4})", flat)
    if m:
        f["replaces"] = re.sub(r"\s+", "", m.group(1))
    m = re.search(r"(\d{4})\s*年首次发布为\s*([A-Z][A-Za-z/]*\s*\d+(?:\.\d+)*\s*[—\-–]\s*\d{4})",
                  flat)
    if m:
        f["first_published"] = m.group(1)
    m = re.search(r"本次为第([一二三四五六七八九十]+)次修订", flat)
    if m:
        f["edition"] = "第%s次修订" % m.group(1)

    # --- 起草单位：OCR 常把换行吃掉、把多家单位连成一串，
    #     所以先按顿号/逗号切，再看有没有"XX公司XX院"这种粘在一起的，按常见后缀补切
    m = re.search(r"起草单位\s*[:：]\s*(.{4,500}?)(?:。|主要起草人|起草人|$)", oneline)
    if m:
        seg = TAIL_NOISE.sub("", m.group(1))
        seg = re.sub(r"(本文件|本标准|本规程)", "", seg)
        orgs = [s.strip() for s in re.split(r"[、,，;；]", seg) if len(s.strip()) >= 4]
        split_orgs = []
        for o in orgs:
            # OCR 把换行吃掉后，多家单位会粘成一串；按常见机构后缀切开。
            # 注意：Python 的 re 不支持变长 lookbehind，这里用捕获组换行再切。
            marked = re.sub(r"(公司|研究院|研究所|大学|中心|集团|监督局|协会)([\u4e00-\u9fff])",
                            r"\1\n\2", o)
            split_orgs += [p.strip() for p in marked.split("\n") if p.strip()]
        if split_orgs:
            f["drafting_orgs"] = split_orgs

    # --- 主要起草人
    m = re.search(r"主要起草人\s*[:：]\s*(.{10,700}?)(?:。|起草单位|$)", oneline)
    if m:
        f["drafters"] = [s.strip() for s in re.split(r"[、,，;；]", m.group(1))
                         if 2 <= len(s.strip()) <= 5]

    # --- 提出 / 归口单位
    m = re.search(r"由(.{2,60}?)(?:提出|提出并)?(?:并)?归口", oneline)
    if m:
        f["administered_by"] = m.group(1).strip("，,。 ")
        f["proposed_by"] = f["administered_by"]
    m = re.search(r"归口单位\s*[:：]\s*([^。\n]{2,80})", flat)
    if m:
        f["administered_by"] = m.group(1).strip()
    m = re.search(r"主管(?:部门|单位)\s*[:：]\s*([^\n]{2,60})", flat)
    if m:
        f["competent_authority"] = m.group(1).strip()

    # --- ICS / CCS
    m = re.search(r"ICS\s*([0-9]{2}(?:\.[0-9]{2,3}){1,2})", flat)
    if m:
        f["ics"] = m.group(1)
    m = re.search(r"CCS\s*([A-Z]\s?\d{1,3})", flat)
    if m:
        f["ccs"] = re.sub(r"\s+", " ", m.group(1))

    # --- 发布单位（封面底部署名）
    pub = []
    for org in ["国家市场监督管理总局", "国家标准化管理委员会", "国家质量监督检验检疫总局",
                "国家技术监督局", "国家能源局", "中央军委装备发展部"]:
        if org in compact:
            pub.append(org)
    if pub:
        f["publishers"] = pub

    # --- 参考文献（只取末页，按 [n] 起头）
    tail_pages = [t for p, t in ordered if tail_from is None or p >= tail_from]
    refs = []
    for t in tail_pages:
        if "参考文献" not in t and not re.search(r"^\s*\[?1\]?\s*[A-Z]", t, re.M):
            continue
        for line in re.split(r"(?=\[\s*\d{1,2}\s*\])", t):
            line = line.strip()
            if re.match(r"^\[\s*\d{1,2}\s*\]", line) and len(line) > 6:
                refs.append(re.sub(r"\s+", " ", line))
    if refs:
        f["references"] = refs[:60]

    # --- 需要人工/AI 复核的提示
    warn = []
    if f.get("title_candidates"):
        warn.append("中文名称候选需 AI 结合封面图定稿（OCR 易把'厂/广'、'—/一'弄错）")
    if f.get("drafting_orgs"):
        warn.append("起草单位/起草人来自 OCR，需与全国标准信息公共服务平台核对")
    f["_review_notes"] = warn
    return f


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--head", type=int, default=4)
    ap.add_argument("--tail", type=int, default=2)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--out", default=None)
    ap.add_argument("--imgdir", default=None)
    ap.add_argument("--parser", default="single_para")
    ap.add_argument("--umi-exe", default=None,
                    help="Umi-OCR.exe 路径（缺省读环境变量 UMI_OCR_EXE，再试常见安装位置）")
    ap.add_argument("--autostart", action="store_true",
                    help="服务不可用时自动拉起 Umi-OCR（默认不拉，只提示）")
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    n = doc.page_count
    doc.close()

    idx = sorted(set(list(range(min(args.head, n)))
                     + list(range(max(0, n - args.tail), n))))
    base = os.path.splitext(os.path.abspath(args.pdf))[0]
    imgdir = args.imgdir or (base + "_pages")
    pages = render_pages(args.pdf, idx, imgdir, dpi=args.dpi)
    print(f"[i] 渲染 {len(pages)} 页 → {imgdir}", file=sys.stderr)

    if not ensure_umi(exe=args.umi_exe, autostart=args.autostart):
        print("[!] Umi-OCR 未就绪：请先启动 Umi-OCR（HTTP 端口 1224）", file=sys.stderr)
        return 3

    pages_text, t_all = [], 0.0
    for p, png in pages:
        try:
            txt, dt = ocr_image(png, parser=args.parser)
            t_all += dt
            print(f"[i] OCR 第 {p + 1} 页 {dt:.2f}s，{len(txt)} 字", file=sys.stderr)
        except Exception as e:
            txt = ""
            print(f"[!] OCR 第 {p + 1} 页失败: {e!r}", file=sys.stderr)
        pages_text.append((p, txt))

    tail_from = max(0, n - args.tail)
    fields = extract_fields(pages_text, tail_from=tail_from)
    result = {
        "file": os.path.basename(args.pdf),
        "pages": n,
        "ocr_pages": [p + 1 for p, _ in pages_text],
        "ocr_seconds_total": round(t_all, 2),
        "fields": fields,
        "ocr_text": {f"p{p + 1}": t for p, t in pages_text},
    }
    out = args.out or (base + ".meta.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print(json.dumps(fields, ensure_ascii=False, indent=2))
    print(f"\n[i] 共耗时 {t_all:.1f}s，已写出 {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
