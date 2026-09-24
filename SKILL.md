---
name: zotero-entry
description: 把标准/规程/报告/投稿/校准证书**条目化**（用户也说"**Zotero 化**""导入 Zotero""建条目""来活儿了"）时使用：PDF 类型判定 → 双层化（Umi-OCR）→ 加书签 → 抽元数据 → 生成 RDF → **导入 Zotero（本地 API 直写，条目+附件）**；也用于查询本机 Zotero 库（检索条目、列分类与标签、取条目详情与 PDF 全文、看最近入库）。查询与写库走 Zotero 本地 API http://127.0.0.1:23119/api/，用 curl.exe 调用，Zotero 需正在运行且已勾选「允许其他应用程序与 Zotero 通讯」。
---

# Zotero 条目化与本地库查询

## 概述

两条线：**查询**本机 Zotero 库（核对库里有哪些标准、规程、文献，只读）；**条目化**——把工作区里的标准/规程/报告/投稿变成 Zotero 条目并挂上可标注的 PDF，见下文「条目化流水线」。
Zotero 官方并未提供 MCP，本技能走其官方 **Local API**（Zotero 7+，实测 10.0.3 可用）。

## 工具目录

本技能自带脚本，在**本技能目录下的 `tools/`**（`SKILL.md` 同一层）。下文命令里的 `tools\xxx.py` 都指这里，可用 `$SKILL/tools/xxx.py` 或绝对路径替换。

依赖：Python 3.10+、`pip install pymupdf requests`；**Umi-OCR 是独立软件、不在本仓库里**（便携版约 200MB），只有扫描件/绕码件才需要它：

- 官方仓库 <https://github.com/hiroi-sora/Umi-OCR>，下载页 <https://github.com/hiroi-sora/Umi-OCR/releases>
- 先检查、需要时自动下便携版：

```
py tools/umi_setup.py --check                 # 看服务与程序在不在，缺了会打印官方下载地址
py tools/umi_setup.py --download --start      # 从官方 Releases 下到 tools/_umi/ 并启动
```

- 下载体积大，**属于第三方软件，先跟用户说一声再下**；下完提醒开启「HTTP 服务」（默认 `127.0.0.1:1224`）。
- 装了别处的 Umi-OCR 也行：`--umi-exe <路径>` 或环境变量 `UMI_OCR_EXE`；端口改过用 `UMI_OCR_API`。

## 前提

1. Zotero 桌面端**必须正在运行**（进程名 `zotero`）。
2. 设置 → 高级 → 勾选「允许此计算机上的其他应用程序与 Zotero 通讯」；未勾选会返回 403。
3. 基址：`http://127.0.0.1:23119/api/users/0`（`0` 代表当前登录用户）。
4. 写库需本地 API key：复制 `tools/zotero_local_key.example.json` 为 `tools/zotero_local_key.json`，填入自己的 `serverId` 与 `apiKey`（获取方式见文末「写入」）。**该文件不要提交、不要外发。**

## 两条铁律

1. **必须用 `curl.exe`**。Zotero 本地 API 返回 **HTTP/1.0**，PowerShell 的 `Invoke-RestMethod` / `Invoke-WebRequest` 会报「基础连接已经关闭：连接被意外关闭」。
2. **中文关键词必须 URL 编码**，否则返回空或报错；中文输出在控制台易乱码，**存文件再读**或用 Python 解析。

编码与读取的标准写法：

```
$q = [uri]::EscapeDataString('流量')
$env:PYTHONIOENCODING='utf-8'
curl.exe -s "http://127.0.0.1:23119/api/users/0/items?q=$q&limit=20" |
  py -c "import sys,json;d=json.load(sys.stdin);[print(x['key'],'|',x['data'].get('itemType'),'|',x['data'].get('title')) for x in d]"
```

## 常用查询

按关键词检索条目：

```
curl.exe -s "http://127.0.0.1:23119/api/users/0/items?q=<编码后关键词>&limit=20"
```

列全部分类：

```
curl.exe -s "http://127.0.0.1:23119/api/users/0/collections?limit=100"
```

某分类下的条目（collectionKey 取自上一步）：

```
curl.exe -s "http://127.0.0.1:23119/api/users/0/collections/<collectionKey>/items?limit=50"
```

条目详情（含 creators、DOI、date、extra）：

```
curl.exe -s "http://127.0.0.1:23119/api/users/0/items/<itemKey>"
```

PDF 全文（附件条目才有）：

```
curl.exe -s "http://127.0.0.1:23119/api/users/0/items/<itemKey>/fulltext"
```

全部标签：

```
curl.exe -s "http://127.0.0.1:23119/api/users/0/tags?limit=100"
```

最近入库：

```
curl.exe -s "http://127.0.0.1:23119/api/users/0/items?sort=dateAdded&direction=desc&limit=20"
```

## 数据结构

每条记录为 `{ key, version, library, data }`：

- `key`：8 位条目号，后续查询要用；
- `data.itemType`：`standard`（标准/计量规程）、`report`、`document`、`journalArticle`、`book` 等；
- `data.title`、`data.creators`、`data.DOI`、`data.date`、`data.extra`（CSL 类型名常写在这里）。

分页用 `limit` 与 `start`；总条数在响应头 `Total-Results` 中，完整响应用的 `curl.exe -s -i` 才能看到头。

## 中文乱码处理

控制台直接打印中文会乱码，二选一：

- 用 Python 解析（见上，先设 `$env:PYTHONIOENCODING='utf-8'`）；
- 或落盘后读：

```
curl.exe -s "URL" -o "$env:TEMP\zotero.json"
```

再用 read 工具读该文件。

## 写入（本地 API）

- **一切 Zotero 操作必须静默，不得弹窗 / 抢焦点**：
  1. **不要主动启动 Zotero**（会带出主窗口、抢焦点）——未运行时先请用户自己开，不要代他启动。
  2. **不要调 `POST /api/local/authorize`**（授权窗）。
  3. **一轮把写操作集中做完**（建条目 + 挂附件一次批量完成），不要边查边写、反复刷 UI。
  4. 只做完成任务必需的 API 调用；收尾把临时文件清掉。
- 读请求免鉴权；写请求需 Zotero 10+ 的本地 API key，脚本 `tools/zotero_api_import.py` 自动读 `tools/zotero_local_key.json`（`--key/--server-id` 可显式覆盖）。
- 用户未明确要求时**不要写库**；用户可在 Zotero 设置里点「清除写入授权」撤销全部授权。

### 首次配置写入 key

1. 取 Server-ID：任意 GET 的响应头 `Zotero-Server-ID`（`curl.exe -s -i ...` 才看得到）。
2. 取 key：`POST /api/local/authorize`，头带 `Zotero-Server-ID`，body 用文件传（`--data-binary "@_auth.json"`，内联 JSON 会被 PowerShell 吃掉引号报 `Invalid JSON provided`）→ Zotero 弹授权窗 → 点 Always Allow → 返回 `{"key": "...", "remember": true}`。
3. 把 `serverId` 与 `apiKey` 写进 `tools/zotero_local_key.json`（照 `tools/zotero_local_key.example.json` 的格式），之后所有脚本复用，**不再重复授权**。
4. 仅当写请求返回 401/403（key 失效、换机、用户清过授权）才重新走一次第 2 步，且要**先告知用户会弹窗**。

## 常见故障

- `Invoke-RestMethod` 报连接被关闭 → 改用 `curl.exe`。
- 返回 403 → 设置里没勾选「允许其他应用程序与 Zotero 通讯」。
- 连接被拒 → Zotero 没运行。
- 中文查询无结果 → 关键词没 URL 编码。
- 只能读当前登录用户的库；群组库仅返回元数据，且为只读。

## 条目化流水线（用户口语：「Zotero 化」「条目化」「来活儿了」）

用户把标准/规程/报告/投稿放进工作区 `归档\` 并说一句"来活儿了"，就是跑这条流水线。**用 RDF，不用 RIS**。

### 第 1 步：判定 PDF 类型（三类，不是两类）

```
py tools/pdf_probe.py <pdf>          # 加 --json 便于程序读
```

**自测**：拿任意一份真实 PDF 跑一遍即可——先 `pdf_probe.py` 判类型，需求 OCR 时先 `umi_setup.py --check` 确认 Umi-OCR 在不在，再按下面的步骤走。想快速验证书签与抽取逻辑，用一份有「目次页」的标准/规程（自带目录效果最好）。

- `TEXT_LAYER_OK`（干净文本层）→ 直接可入库，跳过双层化
- `IMAGE_SCAN`（图片扫描版）→ 走第 2 步
- `TEXT_LAYER_GARBLED`（**字体绕码文本层**）→ 也走第 2 步

第三类最坑：能选中、能复制，但复制出来是 `犐犆犛２７．１２０．２０` 这种乱码（字体被自定义子集重排）。
**判据是"文本是不是人话"，不是"有没有文本层"**——绕码件有 3 万字文本层，却一个版式关键词都命中不了。

### 第 2 步：双层化（图片扫描版 / 绕码版必做）

Zotero 里要的是**可选中、可标注**的 PDF，不是纯图片扫描件。

- **先确认 Umi-OCR 在不在**：`py tools/umi_setup.py --check`。缺了就提示用户，并给出官方下载页 <https://github.com/hiroi-sora/Umi-OCR/releases>；用户同意后再 `py tools/umi_setup.py --download --start`（下到 `tools/_umi/`，约 200MB）。
- `py tools/umi_layered.py <源pdf> <输出目录>`（Umi-OCR 文档 API：`POST /api/doc/upload` → 轮询 `POST /api/doc/result` → 取 `pdfLayered` → 下载；产物 `[OCR]_<原名>.layered.pdf`）。前提：Umi-OCR 服务在跑（HTTP 1224，**勿代用户启动**；装了没开就 `umi_setup.py --start`）。
- 批量：`py tools/umi_layered_batch.py <srcdir> <listfile> <outdir>`。

### 第 3 步：加书签 + 页码标签（快速定位）

**Umi-OCR 生成的双层 PDF 只带 `Page 1 / Page 2 …` 占位书签，等于没有目录，必须重做。**

```
py tools/pdf_bookmarks.py <pdf> --only-check     # 先预演，看定位结果
py tools/pdf_bookmarks.py <pdf> --dump-headings  # 看正文里认出了哪些标题
py tools/pdf_bookmarks.py <pdf> --out <输出.pdf>  # 写出书签树 + 页码标签
py tools/pdf_bookmarks.py <pdf> --sections toc.json --out <输出.pdf>   # 手动给结构表
py tools/pdf_bookmarks.py <已加书签.pdf> --self-test   # 复核有没有错位
```

**章节结构（条款号 + 标题）不用手写**，优先级是：`--sections` 指定的 JSON → **文档自带目次页自动推导**（取目次左列的条款号与标题，右侧页码列按坐标排除）→ 内置示例表（GB/T 19001-2016，**只在推不出结构时兜底，且会打警告**）。
看到 "⚠ 没能从文档里推出章节结构" 就必须改用 `--sections`：拿 `--dump-headings` 的输出整理成 `[["1","范围"],["1.1","…"]]` 存成 JSON 传进去。

做法是**不猜页码、在正文里"认"标题**：双层 PDF 的字带坐标，标题行特征稳定——行首是条款号（1~5 段数字，如 `4.3`、`7.5.3`、`0.3.2`）且带短标题、行长明显小于正文宽度；`前言/引言/参考文献/附录X` 单独成段且**水平居中**。

三个必避的坑：

1. **目录页冒充标题**——先识别"目次 + 点线 + 短行密集"的页并整页排除，否则书签全指到目次页；
2. **标题里带顿号**（如 `5.3 组织的岗位、职责和权限`）——不能一见标点就否掉，只否"号码,号码"式表格行；
3. **附录对照表的纯号码格子**（`6.1`、`9.1` 单独一行）会冒充标题——只作最后兜底，且优先用"该号码的下级标题"（`6.1` 缺标题 → 落在 `6.1.2` 那一页）。

书签与元数据抽取**共用同一套标题识别结果**，所以这一步排在 OCR 之后、抽元数据之前。

### 第 4 步：抽元数据

```
py tools/pdf_metadata.py <pdf> --head 4 --tail 2
```

范围是**前 4 页 + 后 2 页**：起草单位与主要起草人常在**前言第 Ⅲ 页**，只读前两页会漏掉；起草单位还会跨行折断，必须先拼行再切分。
拿出候选后**由 AI 结合正文与页面图定稿**——OCR 必有错字（"厂"→"广"、"翾"→"點"、`900`→`9oo`），标准号与发布/实施日期再到 openstd.samr.gov.cn 核对。

### 第 5 步：生成 RDF 条目文件

1. **清空 RDF 文件夹——只删 `.zotero.rdf`，别的文件一个都别动**：
   - `RDF\` 里可能混着源 PDF、双层 PDF、甚至同名子目录，**只按 `*.zotero.rdf` 过滤**；
   - 删之前先看一眼被删的文件**是不是本轮刚生成的**。若里面躺着一份**没入库**的旧 RDF（如"标准批量导入-17条"），**不要删，移到 `RDF\未入库备份\`** 并在回复里告知用户。
2. 再读 `归档\`，只处理**本轮新出现**的文件——做一件即结束，不迁移、不重构、不追溯历史 RDF。
3. 本轮新条目**合并进一个 RDF 文件**放回 `RDF\`；命名沿用既有约定。
4. 生成规则：顶层必须 `<rdf:Description>` + `z:itemType` 定类型；作者**只能**写 `bib:authors` + `<rdf:li>` 纯文本（写 `foaf:Organization` 会丢作者），且**不要再写 `dc:creator`**；`Extra` 里写 CSL 类型名。
5. 类型判定：标准 / 计量规程 → `standard`；技术报告 → `report`；企业制度与设备手册 / **校准证书** → `document`；设计投稿 → `artwork`（CSL 用 `graphic`）。
6. `Language` 决定显示「等」还是 et al.：`zh-CN`/`zh-TW` → 「等」；`en` 或留空 → et al.；**中文文献必须填 `zh-CN`**。

### 第 6 步：导入 Zotero（写库，本流水线的终点）

**前置检查（顺序照做，缺一项就停）：**

1. **Zotero 必须在运行**。先 `Get-Process zotero` 探一下：
   - **没运行 → 请用户自己打开 `C:\Program Files\Zotero\zotero.exe`，不要代他启动**。代启动会把主窗口拉出来抢焦点，用户明确提过这个 Bug（曾因此被追责一次）。
   - 已运行 → 继续。
2. **查询式去重（必做，用 `curl.exe`，不能用 `Invoke-RestMethod`）**：
   - 按**编号**与**名称关键词**各查一次，例如 `q=<标准号或证书编号>`、`q=<器具名称>`；
   - 中文必须 `[uri]::EscapeDataString()` 编码；
   - **注意坑**：本地 API 的 `q` 对中文关键词**经常返回 0 条**（实测 4000 多条库里查"校准证书"这类词全为空）。想要可靠结论就**拉全量本地过滤**：`?limit=100&start=0,100,…` 分页取回后按 `title/extra/date` 子串匹配，比 `q` 准得多。
   - 查到相同条目 → **不导入，只提示用户「库中已存在」**；查不到才继续。
3. **确认授权可用**：key 已存 `tools\zotero_local_key.json`（`serverId` + `apiKey`），脚本自动复用。**不要调 `POST /api/local/authorize`**——它会弹授权窗抢焦点。仅当写请求返回 401/403 时，先告知用户会弹窗、让他准备点 Always Allow，再重新授权并把新 key 写回该文件。

**写入（两种方式，选一种，不要混着做）：**

- **手工 RDF 导入**（用户自己在 Zotero 里「文件 → 导入」那个 `.zotero.rdf`）：到第 5 步就结束，不写库。
- **本地 API 直写**（推荐，一步到位，条目 + 附件一次做完）：
  - 一条命令：`py tools/zotero_api_import.py --item-json <条目.json> --pdf <PDF> [--collection WEBG3IMH]`；批量用 `py tools/zotero_batch_import.py --json <items.json>`（每项含 `_pdf` 与 `_name`）。
  - 手工调用的四段式（脚本内部就是这么做的）：
    1. `POST /api/users/0/items`（头 `Zotero-API-Key`、`Zotero-Server-ID`，body 为数组）→ 条目 key 在 `success["0"]`；机构作者用 `{"creatorType":"author","name":"..."}`，标准号写 `number`，归入分类写 `"collections":["WEBG3IMH"]`；
    2. 建子附件条目 `{"itemType":"attachment","parentItem":"<父key>","linkMode":"imported_file","filename":"...","contentType":"application/pdf"}`；
    3. `POST /items/<附件key>/file`（头 `If-None-Match: *`，表单 `md5/filename/filesize/mtime`）取 `url` + `uploadKey` → `POST <url>` 传字节（期望 201）→ 再 `POST /items/<附件key>/file`（表单 `upload=<uploadKey>`）得 204；
    4. **附件名不要含空格**：表单里的空格会被编码成 `+` 并落到磁盘；需重命名磁盘文件 + `PATCH /items/<key>` 改 `filename`，且 PATCH 必须带**当前**的 `If-Unmodified-Since-Version`（版本过期会静默不生效）。
  - **静默纪律**：一轮把「建条目 + 挂附件」集中做完，不要边查边写反复刷 UI；只做必需的 API 调用；收尾清掉临时 JSON。
  - **写 pdf 用哪个版本**：图片扫描版 / 字体绕码版必须挂**双层可搜索 PDF**（第 2 步的产物）；干净文本层直接挂原 PDF。

### 第 7 步：登记

- 每新增一条条目，同步更新工作区 `MEMORY.md` 的「文献对象 N」编号与产出文件清单（含证书编号/标准号、来源文件名、查库去重结论）。
- 回复里写清**最终落在哪里**：条目 key、附件 key、分类，以及用了哪种导入方式（RDF 手工导 / API 直写）。

**发表规范小注**：ICMJE 规定先后发表属二次发表，须双方编辑同意并声明引用前作；预印本不算 prior publication，但须告知期刊。

