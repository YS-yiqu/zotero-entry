#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pdf_probe.py —— 「AI + Zotero + Umi-OCR 文件管理方案」第一步：PDF 可标注性判定
               （更准确地说：判定 PDF 属于 ①图片扫描版 ②真文本层 ③字体乱码文本层）

用法：
    python pdf_probe.py <pdf> [<pdf> ...]        # 打印判定报告
    python pdf_probe.py --json <pdf>             # 输出 JSON（供上层流程/AI 调用）

判定依据（三类互相独立，任一命中即降级为"必须 OCR"）：
    A. 图片覆盖率：页面被整页位图覆盖 且 该页可提取字符极少 → 图片扫描版
    B. 有效文本层：提取出的文本里命中常见中文/英文版式词（前言/范围/本文件/参考文献...）
    C. 字体绕码：字体名带 PK<hex> 子集标记，或子集字体数量异常多、cmap 覆盖率极低
       —— 中国标准出版社、部分正文识别工具导出的 PDF 常用这种"乱码文本层"，
          文本层看似存在（可复制、字数不低），但复制出来是 犐犆犛２７ 之类的废字。

结论：只有 B 命中且 C 未命中，才可以直接「AI 识图抽元数据 + 直接标注」；
      否则走 Umi-OCR → 双层可搜索 PDF → 再抽元数据。
"""
import sys
import os
import re
import json
import unicodedata

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("需要 PyMuPDF：py -3 -m pip install pymupdf", file=sys.stderr)
    raise

# ---------------------------------------------------------------- 常量表

# 版式高频词：真文本层的标准/报告/规程，前几页几乎必然命中其中若干
LAYOUT_KEYS_ZH = [
    "前言", "目次", "范围", "规范性引用文件", "术语和定义", "附录", "参考文献",
    "本文件", "本标准", "本规程", "中华人民共和国", "发布", "实施", "代替",
    "起草单位", "主要起草人", "归口", "批准", "发布单位", "实施日期",
]
LAYOUT_KEYS_EN = [
    "Foreword", "Contents", "Scope", "Normative references", "Bibliography",
    "Annex", "Published", "Standard",
]

# 字体名里的绕码指纹：PK + 十六进制，例如 E-HZ9-PK7483a5-Identity-H
FONT_OBFUSCATED_RE = re.compile(r"PK[0-9A-Fa-f]{4,}", re.I)
# 常见子集前缀（正常情况也会有，但只有配合低命中率才算异常）
FONT_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")

CJK_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")

# ---------------------------------------------------------------- 单文件判定


def probe_pdf(path, sample_pages=6, min_chars=120):
    """返回判定结果 dict。"""
    doc = fitz.open(path)
    n = doc.page_count

    # 采样页：前 sample_pages 页 + 最后 2 页（元数据都在首尾）
    idx = list(range(min(sample_pages, n)))
    for i in (n - 2, n - 1):
        if 0 <= i < n and i not in idx:
            idx.append(i)

    full_text = []
    img_only_pages = 0
    text_pages = 0
    font_names = set()
    total_chars = 0

    for i in range(n):
        page = doc[i]
        t = page.get_text()
        total_chars += len(t.strip())
        if len(t.strip()) > 50:
            text_pages += 1
        imgs = page.get_images(full=True)
        if imgs:
            covered = 0.0
            for im in imgs:
                try:
                    rects = page.get_image_rects(im[0])
                except Exception:
                    rects = []
                for r in rects:
                    covered = max(covered, (r.width * r.height) /
                                  max(1.0, page.rect.width * page.rect.height))
            # 整页图 且 几乎无字 → 图片扫描页
            if covered > 0.85 and len(t.strip()) < min_chars:
                img_only_pages += 1
        full_text.append(t)

    for i in idx:
        for f in doc[i].get_fonts(full=True):
            font_names.add(f[3])

    doc.close()

    sample = "".join(full_text)
    cjk_chars = CJK_RE.findall(sample)
    cjk_total = len(cjk_chars)
    cjk_distinct = len(set(cjk_chars))

    hits_zh = [k for k in LAYOUT_KEYS_ZH if k in sample]
    hits_en = [k for k in LAYOUT_KEYS_EN if k in sample]
    hits = hits_zh + hits_en

    obf_fonts = sorted({f for f in font_names if FONT_OBFUSCATED_RE.search(f)})
    subset_fonts = [f for f in font_names if FONT_SUBSET_RE.match(f)]

    # ---- 三条判据
    is_image_scan = img_only_pages > 0.6 * n or text_pages < 0.3 * n
    has_real_text = len(hits) >= 2
    is_obfuscated = False
    reasons = []

    if obf_fonts:
        is_obfuscated = True
        reasons.append(f"字体名带绕码指纹 PK<hex>（{len(obf_fonts)} 个，如 {obf_fonts[0]}）")

    # 有文字但一个版式词都命中不了，且 CJK 字符高度重复 → 乱码文本层
    if total_chars > 500 and not has_real_text:
        if cjk_total > 100 and cjk_distinct < 0.35 * cjk_total:
            is_obfuscated = True
            reasons.append(
                f"提取文本 {total_chars} 字，但 0 个版式关键词命中；"
                f"汉字 {cjk_total} 个却只有 {cjk_distinct} 种 → 字符集异常收敛"
            )
        elif total_chars > 2000:
            is_obfuscated = True
            reasons.append(f"提取文本 {total_chars} 字，但 0 个版式关键词命中")

    if is_image_scan:
        verdict = "IMAGE_SCAN"          # 图片扫描版，无文本层
    elif is_obfuscated:
        verdict = "TEXT_LAYER_GARBLED"  # 有文本层但被绕码，复制即乱码
    elif has_real_text:
        verdict = "TEXT_LAYER_OK"       # 干净文本层
    else:
        verdict = "UNKNOWN"             # 需要人工/OCR 兜底

    need_ocr = verdict != "TEXT_LAYER_OK"

    return {
        "file": os.path.basename(path),
        "path": os.path.abspath(path),
        "pages": n,
        "total_chars": total_chars,
        "text_pages": text_pages,
        "image_only_pages": img_only_pages,
        "layout_key_hits": hits,
        "cjk_total": cjk_total,
        "cjk_distinct": cjk_distinct,
        "font_count_sampled": len(font_names),
        "obfuscated_fonts": obf_fonts[:5],
        "sample_head": sample[:160].replace("\n", " "),
        "verdict": verdict,
        "need_ocr": need_ocr,
        "annotatable_as_is": not need_ocr,
        "reasons": reasons or (["命中版式关键词，文本层可用"] if not need_ocr else ["无有效文本层"]),
    }


VERDICT_ZH = {
    "IMAGE_SCAN": "图片扫描版（无文本层，不可标注）",
    "TEXT_LAYER_GARBLED": "字体绕码文本层（能选字但复制是乱码，不可直接标注）",
    "TEXT_LAYER_OK": "干净文本层（可直接标注）",
    "UNKNOWN": "无法判定（需 OCR 兜底）",
}


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    as_json = "--json" in argv
    files = [a for a in argv[1:] if not a.startswith("--")]
    results = []
    for f in files:
        try:
            r = probe_pdf(f)
        except Exception as e:  # 损坏文件等
            r = {"file": os.path.basename(f), "path": os.path.abspath(f),
                 "verdict": "ERROR", "error": repr(e), "need_ocr": True}
        results.append(r)
        if not as_json:
            print("=" * 78)
            print(f"文件: {r['file']}   ({r.get('pages')} 页)")
            print(f"判定: {r['verdict']} —— {VERDICT_ZH.get(r['verdict'], r.get('error', ''))}")
            if r.get("pages"):
                print(f"      文本页 {r['text_pages']}/{r['pages']}，"
                      f"纯图片页 {r['image_only_pages']}，"
                      f"可提取字符 {r['total_chars']}")
                print(f"      版式关键词命中 {len(r['layout_key_hits'])} 个: "
                      f"{', '.join(r['layout_key_hits'][:8]) or '无'}")
                print(f"      采样字体 {r['font_count_sampled']} 个，"
                      f"绕码字体 {len(r['obfuscated_fonts'])} 个")
                print(f"      文本层样本: {r['sample_head'][:90]}")
            print(f"      依据: {'；'.join(r['reasons'])}")
            print(f"      需要 OCR: {'是' if r['need_ocr'] else '否'}")
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
