# zotero-entry —— 把 PDF 变成 Zotero 条目（含书签与可标注附件）

一个给 AI Agent（DeepSeek Harness / Claude 等支持 SKILL.md 的环境）用的技能包：把标准、规程、报告、投稿、校准证书这类 PDF，**整备成可检索可标注的版本，建成 Zotero 条目并挂上附件**，全程走本机 Zotero 的官方 Local API。

## 它解决什么

- **扫描件不能标注**：整页位图的 PDF 用 Umi-OCR 转成双层可搜索 PDF（保留原图 + 叠加文字层），Zotero 里能选中、能高亮。
- **"有文字层但复制是乱码"**：字体被自定义子集重排的 PDF（中国标准出版社、部分电子书常见），文字层看着有、复制出来是 `犐犆犛２７．１２０．２０`。技能用三条判据把它识别出来，同样走 OCR。
- **长文档翻不动**：Umi-OCR 只给 `Page 1 / Page 2 …` 占位书签；技能直接读 OCR 文字层的坐标，**在正文里"认"出条款号标题**，生成章/节/条三级书签树，并写入与原文档一致的页码标签。
- **标准/规程在 Zotero 里类型总被判错**：走 RDF 而不是 RIS，用 `<rdf:Description>` + `<z:itemType>` 强制锁定 `standard` / `report` / `document`，GB/T 7714 引用能出 `[S]`。
- **手工建条目太慢**：一条命令建成条目 + 上传 PDF 附件，落在指定分类，带标签。

## 环境要求

- Windows（脚本用 PowerShell + Python；核心逻辑跨平台，路径写法按需调整）
- Python 3.10 以上，`pip install pymupdf requests`
- [Zotero](https://www.zotero.org/) 7+（实测 10.0.3）：运行中，且「设置 → 高级」勾选**允许其他应用程序与 Zotero 通讯**
- [Umi-OCR](https://github.com/hiroi-sora/Umi-OCR) v2（Paddle 版）：**只有扫描件/绕码件才用它**。这是独立软件、不在本仓库里（便携版约 200MB），先检查再决定装不装：

```powershell
py tools/umi_setup.py --check                # 看服务和程序在不在
py tools/umi_setup.py --download --start     # 从官方 Releases 下便携版并启动
```

下载来源是官方仓库 <https://github.com/hiroi-sora/Umi-OCR>（Releases 页 <https://github.com/hiroi-sora/Umi-OCR/releases>），解压到 `tools/_umi/`，不写系统目录、随时可删。启动后**要在 Umi-OCR 里开启「HTTP 服务」**（默认 `127.0.0.1:1224`）。

## 安装

**方式 A：手动放**

把本仓库的 `SKILL.md` 与 `tools/` 一起放到技能目录，两者必须同级：

```
<技能目录>/zotero-entry/SKILL.md
<技能目录>/zotero-entry/tools/*.py
```

常见技能目录：DeepSeek Harness 为 `~/.agents/skills/`，Claude Code 为 `~/.claude/skills/`。

**方式 B：SkillHub 商城**

在 DSH Web UI 侧边栏底部的「Skills 商城」面板搜索 `zotero-entry` 安装（可选项目级或用户级）。

## 配置写入权限

查询是免鉴权的；**写库**（建条目、挂附件）需要本机 API key：

1. 取 Server-ID：任意 GET 的响应头 `Zotero-Server-ID`。
2. 取 key：`POST http://127.0.0.1:23119/api/local/authorize`（头带 `Zotero-Server-ID`）→ Zotero 弹授权窗 → 点 Always Allow → 返回 `{"key": "..."}`。
3. 复制 `tools/zotero_local_key.example.json` 为 `tools/zotero_local_key.json`，填入 `serverId` 与 `apiKey`。

该文件是凭据，已在 `.gitignore` 中排除，**不要提交、不要外发**。

## 怎么用

### 作为技能调用（推荐）

装了技能之后直接说人话就行：

- 「条目化」／「Zotero 化」／「来活儿了」→ 跑整条流水线
- 「这份 PDF 加个书签」→ 只跑加书签那步
- 「库里有没有 XX 标准」→ 只查库

### 手工跑脚本

```powershell
# 0. Umi-OCR：先看有没有，没有就下（只有扫描件/绕码件才需要）
py tools/umi_setup.py --check
py tools/umi_setup.py --download --start

# 1. 判类型：干净文本层 / 图片扫描版 / 字体绕码版
py tools/pdf_probe.py "某标准.pdf"

# 2. 需要时双层化（Umi-OCR 转可搜索 PDF）
py tools/umi_layered.py "某标准.pdf" "输出目录"

# 3. 加书签 + 页码标签（结构表优先从文档自带目次推导）
py tools/pdf_bookmarks.py "某标准.pdf" --only-check        # 先预演
py tools/pdf_bookmarks.py "某标准.pdf" --out "带书签.pdf"   # 写出
py tools/pdf_bookmarks.py "带书签.pdf" --self-test          # 复核

# 4. 抽元数据候选（前 4 页 + 后 2 页）
py tools/pdf_metadata.py "某标准.pdf" --head 4 --tail 2

# 5. 建条目并挂附件（写库）
py tools/zotero_api_import.py --item-json item.json --pdf "带书签.pdf" --collection <分类key>
```

批量双层化：`py tools/umi_layered_batch.py <源目录> <文件清单> <输出目录>`。

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `umi_setup.py` | Umi-OCR 检查 / **从官方 Releases 自动下载便携版** / 启动 |
| `pdf_probe.py` | PDF 类型判定：图片扫描版 / 字体绕码文本层 / 干净文本层 |
| `umi_layered.py` | 单份 PDF 转双层可搜索 PDF（Umi-OCR 文档 API） |
| `umi_layered_batch.py` | 批量双层化 |
| `pdf_bookmarks.py` | 生成书签树 + 页码标签；`--only-check` 预演、`--sections` 指定结构表、`--self-test` 复核 |
| `pdf_metadata.py` | 渲染首尾页 → OCR → 抽取标准号/名称/日期/起草单位等候选字段 |
| `zotero_api_import.py` | 建条目 + 上传 PDF 附件（本机 Local API，自动复用 key） |

详细流程与坑位见 [`SKILL.md`](SKILL.md)。

## 几个实测出来的坑（都已写进 SKILL.md）

1. **PDF 不是两类而是三类**——"有文字层"不代表能标注，判据是文本能不能读。
2. **本地 API 的 `q` 参数查中文经常返回 0 条**（4083 条的库里查"校准证书"为空），要可靠结论就分页拉全量本地过滤。
3. **附件名不要含空格**——表单上传会把空格变成 `+` 落到磁盘，得改名后 PATCH 修正。
4. **别用 `Invoke-RestMethod` 调 Zotero 本地 API**——它返回 HTTP/1.0，会报"基础连接已经关闭"，用 `curl.exe`。
5. **加书签时目录页会冒充正文标题**，附录对照表里的纯号码格子也会，两个都得挡。

## 许可

MIT
