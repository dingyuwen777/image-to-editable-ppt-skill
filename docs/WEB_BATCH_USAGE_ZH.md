# 低 API 成本图片转可编辑 PPT：安装与使用

本文档说明如何使用：

```text
本地 editppt Runtime
→ GPT 网页端批量重建
→ 本地构建、渲染、校验和输出 PPTX
```

正常情况下，一套 PPT 只进行两次文件交接：

1. 本地生成 `handoff.zip`，上传到 GPT 网页端；
2. 从 GPT 网页端下载 `reconstruction.zip`，交给本地 Runtime。

只有本地验证失败的页面才需要进入后续修订轮次。

---

## 1. 能力边界

该模式能够保留原 Skill 的主要质量契约：

- OCR 和源像素文字框提示；
- 可编辑文本框；
- 可编辑简单形状和连接线；
- 独立复杂图片资产；
- Manifest 驱动的确定性 PPTX 构建；
- 页面和整套 PPTX 结构校验；
- 多轮“重建—渲染—对比—修正”；
- 禁止整页截图叠加隐藏文字的伪可编辑实现。

该模式不承诺任何输入均能达到 100% 像素级一致。复杂照片、插画、纹理和人物通常作为独立图片资产保留，资产内部不一定可编辑。

---

## 2. 环境要求

### 必需

- Windows 10/11、macOS 或 Linux；
- Python 3.10—3.12；
- Git；
- PowerPoint、WPS 或 LibreOffice，用于人工打开最终文件。

### 推荐

- 百度 AI Studio PaddleOCR-VL Token，用于更准确的文字内容、位置和字号提示；
- ImageMagick，用于 SVG 资产的跨平台预览；
- LibreOffice，用于旧 `.ppt` 输入转换。

Web Batch 模式本地端默认不需要：

- `OPENAI_API_KEY`；
- Codex OAuth；
- 本地文本大模型；
- 本地图像生成模型。

图像理解、背景修复和前景资产分离由 GPT 网页端完成。

---

## 3. 下载代码

```bash
git clone https://github.com/dingyuwen777/image-to-editable-ppt-skill.git
cd image-to-editable-ppt-skill
git switch feature/web-batch-reconstruction
```

在功能合并到 `main` 后，可省略最后一行。

---

## 4. 安装 Runtime

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .\skills\image-to-editable-ppt\cli
editppt --help
editppt setup
editppt doctor
```

以后使用前：

```powershell
cd <仓库目录>
.\.venv\Scripts\Activate.ps1
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./skills/image-to-editable-ppt/cli
editppt --help
editppt setup
editppt doctor
```

也可以使用：

```bash
pipx install --force --editable ./skills/image-to-editable-ppt/cli
```

---

## 5. 可选配置

### PaddleOCR Token

```bash
editppt config --paddle-ocr-token "你的Token"
editppt doctor
```

没有 Token 时仍能运行，但退化为离线文字墨迹测量，文字内容和分块质量可能降低。

### ImageMagick

确认以下命令之一可用：

```bash
magick -version
convert -version
```

仅当页面使用 SVG 图片资产时，预览阶段必须使用 ImageMagick。没有 SVG 时不是必需项。

### LibreOffice

旧 `.ppt` 文件需要：

```bash
soffice --version
```

图片、PDF 和图片型 `.pptx` 不依赖 LibreOffice。

---

## 6. 安装 GPT 网页端 Skill

需要安装的 Skill 目录：

```text
skills/image-to-editable-ppt-web/
└── SKILL.md
```

在支持个人/工作区 Skill 的 GPT 网页端，将该目录打包为 ZIP 后安装。Skill 名称为：

```text
image-to-editable-ppt-web
```

网页端 Skill 仅负责读取 Handoff、分析页面、调用网页端图片工具并输出 Reconstruction/Revision Bundle。它不会在网页端直接生成最终 PPTX。

若当前 GPT 账号不能安装个人 Skill，可以创建仅自己可见的 Custom GPT，把 `SKILL.md` 内容作为 Instructions，并开启：

- 文件上传；
- 数据分析/代码执行；
- 图像生成与编辑。

---

## 7. 第一次转换

以下示例输入为：

```text
D:\PPT\input\deck.pdf
```

### 7.1 本地预处理

Windows：

```powershell
editppt prepare "D:\PPT\input\deck.pdf" --out-root "D:\PPT\runtime-data"
```

macOS/Linux：

```bash
editppt prepare ~/PPT/input/deck.pdf --out-root ~/PPT/runtime-data
```

命令会输出类似：

```text
D:\PPT\runtime-data\20260730-010101-deck\deck_manifest.json
run_id=20260730-010101-deck
pages=10
```

任务目录记为：

```text
RUN=D:\PPT\runtime-data\20260730-010101-deck
```

输入支持：

```bash
editppt prepare page.png
editppt prepare page-01.png page-02.png page-03.png
editppt prepare deck.pdf
editppt prepare image-based.pptx
editppt prepare legacy.ppt
```

`.pptx` 当前应为“每页一张铺满页面的图片型 PPTX”。原生或混合型 PPTX 请先导出为 PDF 或页面图片。

### 7.2 检查文字提示

每页目录应包含：

```text
pages/page_001/source.png
pages/page_001/text_hints.json
pages/page_001/text_hints.png
```

配置 OCR Token 后需要重新生成提示时：

```bash
editppt run hints "<RUN>"
```

### 7.3 导出 Handoff

```bash
editppt web export "<RUN>" --out "handoff.zip"
```

检查包：

```bash
editppt web inspect "handoff.zip"
```

Handoff 不包含 API Key、Codex OAuth、输入原文件、绝对本地路径或无关任务文件。

### 7.4 上传 GPT 网页端

上传 `handoff.zip`，发送：

```text
使用 image-to-editable-ppt-web Skill 处理这个 handoff。
严格遵循包内 page-decision-tree、manifest-schema 和 web-bundle-protocol。
完成所有页面后输出 reconstruction.zip，不要直接生成最终 PPTX。
```

GPT 网页端会：

1. 解包并验证协议；
2. 逐页查看原图和 OCR hints；
3. 判断背景、前景资产、文本和原生形状；
4. 必要时调用网页端图像生成/编辑；
5. 写入完整 `manifest.json`、资产和来源记录；
6. 输出 `reconstruction.zip`。

网页端返回文件后下载到本地。

### 7.5 本地检查并导入结果包

```bash
editppt web inspect "reconstruction.zip"
editppt web import "<RUN>" "reconstruction.zip"
```

导入会拒绝：

- Job ID 不一致；
- 页面原图哈希不一致；
- ZIP 路径穿越；
- 符号链接；
- 重复成员；
- 缺失 Manifest；
- Manifest 引用缺失资产；
- 资产路径逃逸到页面目录外。

导入成功后，任务的图片后端会切换为：

```text
web-artifact
```

此后本地不调用图片模型 API。

### 7.6 本地统一构建

```bash
editppt web build "<RUN>"
```

该命令自动执行：

```text
逐页构建 page.pptx
→ 跨平台渲染 preview.png
→ 生成原图/预览对比图
→ 页面结构校验
→ 记录通过页面
→ 全部通过后构建最终 PPTX
→ 整套 PPTX 校验
```

成功输出：

```text
<RUN>/final/deck_edited.pptx
<RUN>/final/validation.json
<RUN>/final/run_summary.json
<RUN>/web_build_summary.json
```

---

## 8. 多轮“重建—渲染—对比—修正”

若 `editppt web build` 返回失败页面，不需要重新处理整个 Deck。

### 8.1 导出失败页

```bash
editppt revision export "<RUN>" --out "revision-round-01.zip"
```

包中仅包含失败或未记录页面，包括：

- 原图；
- 当前 Manifest；
- 当前预览；
- 原图/预览对比图；
- 验证报告；
- OCR hints；
- 当前资产；
- 结构化修正要求。

### 8.2 上传 GPT 网页端修正

上传 `revision-round-01.zip`，发送：

```text
使用 image-to-editable-ppt-web Skill 修正这个 revision-request。
根据 source、preview、contact sheet、validation 和 correction-request 修复根因。
输出 revision-result ZIP，只处理包中列出的页面。
```

下载网页端输出，例如：

```text
revision-result-round-01.zip
```

### 8.3 应用修订并重新构建

```bash
editppt revision apply "<RUN>" "revision-result-round-01.zip"
editppt web build "<RUN>"
```

旧版本页面会归档在：

```text
<RUN>/revisions/round-01/before/page_001/
```

已通过页面不会被重置或重建。

仍有失败页时重复：

```text
revision export
→ GPT 网页端修正
→ revision apply
→ web build
```

通常建议网页语义修订不超过 2—3 轮。持续失败页面应人工审查，避免无限循环。

---

## 9. 断点续跑

所有状态保存在 `RUN` 中，不依赖聊天记忆。

常用检查：

```bash
editppt run status "<RUN>"
cat "<RUN>/web_build_summary.json"
cat "<RUN>/failed_pages.json"
```

聊天中断后，只需重新上传当前 Handoff 或 Revision Bundle；本地任务无需重新 prepare。

---

## 10. 数据安全

- Handoff 会将页面原图和 OCR hints上传到 GPT 网页端；保密资料需符合组织的数据策略。
- Bundle 不包含本地 API Key、OAuth 文件和无关文件。
- Runtime 将所有网页返回 ZIP 视为不可信输入并执行安全校验。
- 不要手工解压后覆盖任务目录；始终使用 `editppt web import` 或 `editppt revision apply`。
- 不要修改 `source.png`，其 SHA-256 是网页结果与本地任务绑定的完整性依据。

---

## 11. 更新代码

```bash
git fetch origin
git switch feature/web-batch-reconstruction
git pull --ff-only
python -m pip install -e ./skills/image-to-editable-ppt/cli
editppt doctor
```

更新不会主动修改已有的任务目录。重要任务应保留完整 `RUN` 目录备份。

---

## 12. 最短命令清单

```bash
# 1. 本地预处理
editppt prepare input.pdf --out-root runtime-data

# 2. 导出并上传 GPT 网页端
editppt web export <RUN> --out handoff.zip

# 3. 下载网页结果并导入
editppt web inspect reconstruction.zip
editppt web import <RUN> reconstruction.zip

# 4. 本地统一构建
editppt web build <RUN>

# 5. 失败页修订
editppt revision export <RUN> --out revision-round-01.zip
editppt revision apply <RUN> revision-result-round-01.zip
editppt web build <RUN>
```
