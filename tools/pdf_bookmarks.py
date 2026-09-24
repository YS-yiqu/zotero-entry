#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pdf_bookmarks.py —— 给（扫描 + OCR 后的）标准/规程类 PDF 加书签 + 页码标签

核心思路：**不去猜页码，而是在正文里"认出"标题**。
Umi-OCR 生成的双层 PDF 里，每个字都带字号/坐标，而标准的标题有稳定的排版特征：
    标题行字号明显大于正文，且"条款号 + 标题"通常在同一行（如 "7.2 能力"）
因此可以逐页扫描、按特征识别标题，得到的页码天生精确，不依赖目次页那几个 OCR 得
时好时坏的页码数字。

三层校验：
  1) 结构表（条款号 + 标题）—— 标题以目次页原文为准，OCR 错字按标准正文校正
  2) 排版识别 —— 字号 / 行形态 / 条款号正则，在正文页里定位真实物理页
  3) 页码标签 —— 由页脚数字自动推断"打印页码 ↔ 物理页"偏移，写进 PDF page labels

用法：
    python pdf_bookmarks.py <pdf> --out <输出.pdf>            # 生成带书签的 PDF
    python pdf_bookmarks.py <pdf> --only-check                # 只打印识别结果
    python pdf_bookmarks.py <pdf> --dump-headings             # 看正文里认出了哪些标题
    python pdf_bookmarks.py <pdf> --sections toc.json --out <输出.pdf>   # 用外部结构表
    python pdf_bookmarks.py <pdf> --self-test                 # 校验已有书签是否有错位

章节结构（条款号 + 标题）的来源，按优先级：
    1) --sections 指定的 JSON
    2) 文档自带目录页推出的结构（auto_toc）
    3) 内置示例表（GB/T 19001-2016，仅在推不出结构时兜底）
"""
import argparse
import json
import re
import sys

try:
    import fitz
except ImportError:
    print("需要 PyMuPDF", file=sys.stderr)
    raise

# ------------------------------------------------------------------ 结构表
# 下面这份是**示例表**（GB/T 19001-2016 的目次），只在脚本推不出结构时兜底。
# 正常情况不用管它：脚本会先从文档自带的目录页推出结构（见 auto_toc），
# 想精确控制就用 --toc 传一份 JSON：{"sections": [["1","范围"], ["1.1","…"], ...]}
SECTIONS = [
    ("前言", "前言"),
    ("引言", "引言"),
    ("0.1", "总则"),
    ("0.2", "质量管理原则"),
    ("0.3", "过程方法"),
    ("0.3.1", "总则"),
    ("0.3.2", "PDCA循环"),
    ("0.3.3", "基于风险的思维"),
    ("1", "范围"),
    ("2", "规范性引用文件"),
    ("3", "术语和定义"),
    ("4", "组织环境"),
    ("4.1", "理解组织及其环境"),
    ("4.2", "理解相关方的需求和期望"),
    ("4.3", "确定质量管理体系的范围"),
    ("4.4", "质量管理体系及其过程"),
    ("5", "领导作用"),
    ("5.1", "领导作用和承诺"),
    ("5.1.1", "总则"),
    ("5.1.2", "以顾客为关注焦点"),
    ("5.2", "方针"),
    ("5.2.1", "制定质量方针"),
    ("5.2.2", "沟通质量方针"),
    ("5.3", "组织的岗位、职责和权限"),
    ("6", "策划"),
    ("6.1", "应对风险和机遇的措施"),
    ("6.2", "质量目标及其实现的策划"),
    ("6.3", "变更的策划"),
    ("7", "支持"),
    ("7.1", "资源"),
    ("7.1.1", "总则"),
    ("7.1.2", "人员"),
    ("7.1.3", "基础设施"),
    ("7.1.4", "过程运行环境"),
    ("7.1.5", "监视和测量资源"),
    ("7.1.6", "组织的知识"),
    ("7.2", "能力"),
    ("7.3", "意识"),
    ("7.4", "沟通"),
    ("7.5", "成文信息"),
    ("7.5.1", "总则"),
    ("7.5.2", "创建和更新"),
    ("7.5.3", "成文信息的控制"),
    ("8", "运行"),
    ("8.1", "运行的策划和控制"),
    ("8.2", "产品和服务的要求"),
    ("8.2.1", "顾客沟通"),
    ("8.2.2", "产品和服务要求的确定"),
    ("8.2.3", "产品和服务要求的评审"),
    ("8.2.4", "产品和服务要求的更改"),
    ("8.3", "产品和服务的设计和开发"),
    ("8.3.1", "总则"),
    ("8.3.2", "设计和开发策划"),
    ("8.3.3", "设计和开发输入"),
    ("8.3.4", "设计和开发控制"),
    ("8.3.5", "设计和开发输出"),
    ("8.3.6", "设计和开发更改"),
    ("8.4", "外部提供的过程、产品和服务的控制"),
    ("8.4.1", "总则"),
    ("8.4.2", "控制类型和程度"),
    ("8.4.3", "提供给外部供方的信息"),
    ("8.5", "生产和服务提供"),
    ("8.5.1", "生产和服务提供的控制"),
    ("8.5.2", "标识和可追溯性"),
    ("8.5.3", "顾客或外部供方的财产"),
    ("8.5.4", "防护"),
    ("8.5.5", "交付后活动"),
    ("8.5.6", "更改控制"),
    ("8.6", "产品和服务的放行"),
    ("8.7", "不合格输出的控制"),
    ("9", "绩效评价"),
    ("9.1", "监视、测量、分析和评价"),
    ("9.1.1", "总则"),
    ("9.1.2", "顾客满意"),
    ("9.1.3", "分析与评价"),
    ("9.2", "内部审核"),
    ("9.3", "管理评审"),
    ("9.3.1", "总则"),
    ("9.3.2", "管理评审输入"),
    ("9.3.3", "管理评审输出"),
    ("10", "改进"),
    ("10.1", "总则"),
    ("10.2", "不合格和纠正措施"),
    ("10.3", "持续改进"),
    ("附录A", "附录A（资料性附录）　新结构、术语和概念说明"),
    ("附录B", "附录B（资料性附录）　SAC/TC 151制定的其他质量管理和质量管理体系标准"),
    ("参考文献", "参考文献"),
]

EXACT = ("前言", "引言", "参考文献")     # 无条款号的独立标题
CLOSE = {"4", "5", "6", "7", "8", "9", "10", "1", "2", "3"}  # 一级章号：须行首独立出现


# ------------------------------------------------------------------ 参数估计

def body_font_size(doc, sample=12):
    """用页面上出现最多的字号近似"正文字号"。"""
    from collections import Counter
    c = Counter()
    for p in range(min(sample, doc.page_count)):
        for b in doc[p].get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["text"].strip():
                        c[round(s["size"], 1)] += len(s["text"])
    return c.most_common(1)[0][0] if c else 10.0


def infer_page_offset(doc, body_size):
    """由页脚数字推断：物理页 → 打印页码 的固定偏移。"""
    cands = []
    for p in range(doc.page_count):
        lines = []
        for b in doc[p].get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l["spans"]:
                    t = s["text"].strip()
                    if not t or l["bbox"][1] < doc[p].rect.height * 0.9:
                        continue
                    lines.append(t)
        # 底部只可能是页脚（数字或罗马数字）
        for t in lines:
            if re.fullmatch(r"\d{1,3}", t):
                cands.append((p + 1, int(t)))
    if not cands:
        return None
    # 取出现次数最多的 (物理页 - 打印页) 差值
    from collections import Counter
    diffs = Counter(phys - printed for phys, printed in cands)
    return diffs.most_common(1)[0][0]


# ------------------------------------------------------------------ 标题识别

def toc_pages(doc):
    """挑出目录页（物理页号集合，1-based）。

    判据（任一命中即算目录页）：
      a) 有"目 次 / 目次 / 目录 / CONTENTS"标题行（中间可能有全角空格）；
      b) 有点线引导行（…… 或 ...）且整页行短而密。
    目录页必须先排除，否则书签全会指向目录页——这是最容易踩的坑。
    """
    out = set()
    for p in range(min(16, doc.page_count)):
        text = doc[p].get_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if re.search(r"目[\s\u3000]*[次录]|CONTENTS", text, re.I):
            out.add(p + 1)
            continue
        dots = len(re.findall(r"\.{3,}|…", text))
        short = sum(1 for l in lines if len(l) <= 60)
        if lines and dots >= 1 and short / len(lines) > 0.8:
            out.add(p + 1)
    return out


NUM_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,4})(.*)$")
# 条款号后面不能紧跟这些字符（否则是"5kg""3.5mm""2/3"之类，不是标题）
# 注意：不能一律排除字母——像 "0.3.2PDCA循环" 是合法标题，因此只拦"ASCII 单词+数字"的组合
NOT_TITLE_AFTER = re.compile(r"^[A-Za-z]{1,4}\d|^[\d./%°℃]|^[A-Za-z]{1,4}$")
# 标题开头不可能是标点（OCR 噪声，如正文行 "6) 审核结果；" 被截成 "6" + ") 审核结果；"）
BAD_TITLE_START = re.compile(r"^[)\]】：:；;，,、。·\-—]")
# 标题里不该出现句读句尾（那是正文句子）
BAD_TITLE_BODY = re.compile(r"[。；;]$")


def page_headings(doc, pno, body_size):
    """识别该页的标题行。返回 (hits, cells)。

    hits：{条款号/名称: (y, 标题)}  —— 带标题的标题行，可信
    cells：{条款号: (y, "")}        —— 表格里"纯号码"的小格子（附录对照表），
                                      只在找不到带标题的标题行时用作兜底线索
    """
    page = doc[pno]
    W = page.rect.width
    found, cells = {}, {}
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for line in b.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue

            # ---- 居中独立标题：前言 / 引言 / 参考文献 / 附录X
            for s in spans:
                key = s["text"].strip().replace(" ", "")
                if key in ("前言", "引言", "参考文献") or re.match(r"^附录[A-Z]?$", key):
                    cx = (s["bbox"][0] + s["bbox"][2]) / 2
                    if abs(cx - W / 2) < W * 0.15:
                        found.setdefault(key, (s["bbox"][1], ""))

            # ---- 条款号标题
            text = "".join(s["text"] for s in spans).strip()
            if not text or len(text) > 26:
                continue
            x0, y0 = line["bbox"][0], line["bbox"][1]
            width = line["bbox"][2] - x0
            if width > W * 0.62:
                continue
            if re.search(r"\.{3,}|…", text):           # 目录点线
                continue
            if re.search(r"\d\s*[,，]\s*\d", text):    # 表格格子里并排的多个号码
                continue
            if text.endswith(("，", ",")):             # 正文句子被切断
                continue
            m = NUM_RE.match(text)
            if not m:
                continue
            num, title = m.group(1), m.group(2).strip()
            if not title:
                # 纯号码：可能是表格格子。单独一个一级章号（"7"）直接丢
                if "." in num:
                    cells.setdefault(num, (y0, ""))
                continue
            if NOT_TITLE_AFTER.match(title):
                continue
            if BAD_TITLE_START.match(title) or BAD_TITLE_BODY.search(title):
                continue
            centred = abs((line["bbox"][0] + line["bbox"][2]) / 2 - W / 2) < W * 0.15
            if x0 > W * 0.30 and not centred:
                continue
            found.setdefault(num, (y0, title))
    return found, cells


def scan_document(doc, body_size, skip=()):
    """全文档扫描 → (hits, cells)。

    hits：条款号 → 首次出现且"带标题"的 (物理页, y, 标题)
    cells：条款号 → 首次出现且"只有号码"的 (物理页, y, "")（表格兜底）
    """
    hits, cells = {}, {}
    for p in range(doc.page_count):
        if (p + 1) in skip:
            continue
        h, c = page_headings(doc, p, body_size)
        for key, (y, title) in h.items():
            prev = hits.get(key)
            if prev is None or (not prev[2] and title):
                hits[key] = (p + 1, y, title)
        for key, (y, _) in c.items():
            cells.setdefault(key, (p + 1, y, ""))
    return hits, cells


def candidate_keys(hits, cells, no):
    """结构表条目可能对应的扫描键，按可靠性排序：

    1) 完全同号（正文标题）
    2) 该号码的下级标题（如 6.1 缺标题，就落到 6.1.2）—— 页码必然正确
    3) 该号码的 OCR 粘连变体（如 7.1.3 → 7.1.33）
    4) 表格里的纯号码格子（附录对照表）—— 只作最后兜底，可能偏后
    """
    def score(k):
        if k == no:
            return (0, 0, 0)
        if k.startswith(no + "."):
            return (1, len(k) - len(no), 0)
        if re.fullmatch(re.escape(no) + r"\.?\d*", k):
            return (2, len(k) - len(no), 0)
        return (3, 0, 0)

    pool = {}
    for k, v in hits.items():
        pool[k] = (v, True)          # True = 带标题的正文标题行（可靠）
    for k, v in cells.items():
        pool.setdefault(k, (v, False))   # False = 表格纯号码格子（兜底）
    keys = [k for k in pool if k == no or k.startswith(no + ".")
            or re.fullmatch(re.escape(no) + r"\.?\d*", k)]
    if no in hits:                       # 有精确标题行 → 直接用它
        return [no] + [k for k in sorted(keys, key=lambda k: (score(k), pool[k][0][0]))
                       if k != no]
    # 没有精确标题行 → 优先"带标题的"候选，再考虑表格格子
    keys.sort(key=lambda k: (0 if pool[k][1] else 1, score(k), pool[k][0][0]))
    return keys


def clean_title(s):
    """清掉标题尾巴上的点线/省略号等 OCR 残留（"引用文献…．" → "引用文献"）。"""
    s = re.sub(r"[\s.·…．、,，;；:：]+$", "", s)
    s = re.sub(r"^[\s.·…．]+", "", s)
    return s


def auto_toc(doc, body_size, skip):
    """从文档自身推出章节结构表 [(条款号, 标题), ...]。

    目录页左侧那一列就是条款号 + 标题（行序即权威结构顺序），右侧页码列按坐标排除。
    两种排法都处理：
      · "N 标题" 同一行
      · 章号单独占一行，标题在下一行（OCR 常把 "1 范围" 拆成两行）
    """
    W = doc[0].rect.width if doc.page_count else 595.0
    out = []

    def add(no, title):
        title = clean_title(title)
        if title and no not in {x[0] for x in out}:
            out.append((no, title))

    for p in sorted(skip):
        page = doc[p - 1]
        texts, pending = [], None
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                x0 = line["bbox"][0]
                width = line["bbox"][2] - x0
                if x0 > W * 0.45 or width > W * 0.55:
                    continue
                texts.append("".join(s["text"] for s in spans).strip())
        for text in texts:
            if not text:
                continue
            m_only = re.fullmatch(r"(\d{1,2}(?:\.\d{1,2}){0,3})", text)
            if m_only:
                pending = m_only.group(1)      # 号码单独一行（"1"、"6.4"）
                continue
            m = re.match(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s*(.+?)\s*$", text)
            if m and clean_title(m.group(2)):
                add(m.group(1), m.group(2))
                pending = None
            elif pending:
                # 上一行留了个孤零零的号码，这一行没号码 → 判定为被拆开的"号码 + 标题"
                if len(text) <= 24 and text[-1:] not in "。；;：:":
                    add(pending, text)
                    pending = None
    if len(out) >= 2:
        return out

    # 收尾二：补回被 OCR 整条吃掉的一级章（如 "1 范围" 只剩一个孤零零的 "1"）。
    # 只在一级章范围内补，且只补"正文里认得出标题"的号——不把正文噪声收进结构表。
    if out:
        heads = {int(x[0].split(".")[0]) for x in out}
        lo, hi = min(heads), max(heads)
        gaps = [n for n in range(lo, hi + 1) if n not in heads]
        if gaps:
            hits, _cells = scan_document(doc, body_size, skip=skip)
            for n in gaps:
                cand = hits.get(str(n))
                if cand and cand[2]:
                    out.append((str(n), cand[2]))
            out.sort(key=lambda x: [int(t) for t in x[0].split(".")])
            left = [n for n in gaps if str(n) not in {x[0] for x in out}]
            if left:
                print(f"⚠ 目录里缺这几个一级章的标题：{left}——"
                      f"正文里也没认出对应标题，建议用 --sections 手工补结构表",
                      file=sys.stderr)
    if len(out) >= 2:
        return out

    # 兜底：没有可用目录页 → 按正文里的出现顺序收集
    hits, _cells = scan_document(doc, body_size, skip=skip)
    ordered = sorted(((v[0], v[1], k, v[2]) for k, v in hits.items()),
                     key=lambda t: (t[0], t[1]))
    return [(k, clean_title(title)) for _p, _y, k, title in ordered
            if re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,3}", k)]


def build(doc, sections=None, verbose=True):
    body_size = body_font_size(doc)
    skip = toc_pages(doc)
    if sections is None:
        auto = auto_toc(doc, body_size, skip)
        if len(auto) >= 2:
            sections = auto
            if verbose:
                print(f"章节结构来源：文档自带目录（{len(sections)} 条）")
        else:
            sections = SECTIONS
            print("⚠ 没能从文档里推出章节结构（没找到可用目录页），"
                  "落回内置示例表（GB/T 19001-2016）。\n"
                  "   这样生成的书签一定不对——请用 --sections <toc.json> 指定结构表，"
                  "或先 --dump-headings 看看正文标题能不能认出来。", file=sys.stderr)
    hits, cells = scan_document(doc, body_size, skip=skip)
    if verbose:
        print(f"目录页（已排除）: {sorted(skip) or '无'}；"
              f"正文中识别到 {len(hits)} 个标题行（另有 {len(cells)} 个表格号码作兜底）")
    toc, missing = [], []
    last_page = 0
    for no, title in sections:
        keys = candidate_keys(hits, cells, no)
        page, note = None, ""
        if keys:
            # 精确号码优先（页码可靠）；只有精确号码缺失时才用下级标题/变体/表格号码
            chosen = keys[0]
            pg, y, found_title = (hits.get(chosen) or cells[chosen])
            page = pg
            if chosen != no:
                kind = "下级标题" if chosen.startswith(no + ".") else "OCR 变体/表格号码"
                note = f"· 用{kind} {chosen}"
            if found_title and title:
                a, b = re.sub(r"\s", "", found_title), re.sub(r"\s", "", title)
                if b[:3] not in a and a[:3] not in b:
                    note += f"· 正文标题“{found_title}”"
        if page is None:
            # 兜底：指向其后最近的、识别到标题的那一页
            later = sorted(v[0] for v in hits.values() if v[0] > last_page)
            nxt = later[0] if later else (last_page or 1)
            note = f"⚠ 正文中未识别到标题行，指向其后最近的标题页（物理 {nxt}）"
            page = max(nxt, last_page or 1)
        last_page = max(last_page, page)
        if no in EXACT or no.startswith("附录"):
            lvl = 1
        else:
            lvl = no.count(".") + 1
        label = title if (no in EXACT or no.startswith("附录")) else f"{no} {title}"
        toc.append([lvl, label, page])
        if verbose:
            flag = "!!" if note.startswith("⚠") else "OK"
            print(f"  {flag} 物理{page:>3}  L{lvl}  {label}   {note}")
    return toc, missing, body_size


def apply_labels(doc, offset, body_size):
    """按页脚推断的偏移写 page labels：offset=物理页-打印页。"""
    specs = []
    for p in range(1, doc.page_count + 1):
        printed = p - offset
        if printed < 1:
            specs.append({"startpage": p - 1, "prefix": "封面" if p == 1 else "",
                          "style": "r" if p > 1 else "", "firstpagenum": max(1, p - 1)})
    if offset:
        specs.append({"startpage": offset, "prefix": "", "style": "D", "firstpagenum": 1})
    if specs:
        doc.set_page_labels(specs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out")
    ap.add_argument("--only-check", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--sections", help='外部条款表 JSON：[["1","总则"],["1.1","目的"],...]'
                                        '（默认先自动从目录页推，推不出再用内置示例表）')
    ap.add_argument("--dump-headings", action="store_true", help="打印正文中识别到的全部标题后退出")
    args = ap.parse_args()

    doc = fitz.open(args.pdf)

    sections = None                     # None = 自动推结构（auto_toc）
    if args.sections:
        with open(args.sections, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):       # 允许 {"sections": [...]} 包一层
            raw = raw.get("sections", [])
        sections = [tuple(x) for x in raw]
        print(f"已载入外部条款表 {len(sections)} 条：{args.sections}")

    if args.dump_headings:
        body_size = body_font_size(doc)
        skip = toc_pages(doc)
        hits, cells = scan_document(doc, body_size, skip=skip)
        print(f"目录页(已排除): {sorted(skip) or '无'}；识别到 {len(hits)} 个带标题行，{len(cells)} 个纯号码")
        for k in sorted(hits, key=lambda x: [int(t) if t.isdigit() else 0 for t in x.split(".")]):
            pg, y, t = hits[k]
            print(f"  {k:<12} 物理{pg:>3}  {t}")
        return 0

    if args.self_test:
        toc = doc.get_toc()
        body_size = body_font_size(doc)
        hits = scan_document(doc, body_size)
        bad = []
        for lvl, label, page in toc:
            key = re.sub(r"^(附录[A-Z]|[0-9.]+)\s*", "", label).strip()
            # 该页是否真的出现这个标题文本
            txt = re.sub(r"\s", "", doc[page - 1].get_text()) if 1 <= page <= doc.page_count else ""
            if key.replace("　", "")[:6] not in txt:
                bad.append((page, label))
        print(f"书签 {len(toc)} 条，校验不通过 {len(bad)} 条")
        for page, label in bad:
            print(f"  !! 物理{page}: {label}")
        return 0

    print(f"页数 {doc.page_count}，原有书签 {len(doc.get_toc())} 条"
          f"（{'占位 Page n，将被替换' if doc.get_toc() else '无'}）")
    toc, missing, body_size = build(doc, sections)
    print(f"\n共生成 {len(toc)} 条书签" + (f"，未定位 {len(missing)} 条：{missing}" if missing else "，全部定位成功"))

    if args.only_check:
        return 0
    if not args.out:
        print("未指定 --out", file=sys.stderr)
        return 2

    offset = infer_page_offset(doc, body_size) or 0
    print(f"页脚推断：物理页 = 打印页 + {offset}")
    if offset:
        apply_labels(doc, offset, body_size)
    doc.set_toc(toc)
    doc.save(args.out, garbage=3, deflate=True, clean=True)
    doc.close()
    print(f"已写出 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
