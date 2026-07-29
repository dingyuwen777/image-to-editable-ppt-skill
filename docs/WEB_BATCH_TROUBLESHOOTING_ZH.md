# Web Batch 故障排查

## 1. `editppt` 命令不存在

重新激活虚拟环境并安装：

```bash
python -m pip install -e ./skills/image-to-editable-ppt/cli
editppt --help
```

Windows：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux：

```bash
source .venv/bin/activate
```

## 2. `editppt doctor` 显示 API backend missing

Web Batch 模式不依赖图片 API fallback。普通：

```bash
editppt doctor
```

只要 Python 依赖正常即可。不要使用要求模型凭据的：

```bash
editppt doctor --check-api
```

导入网页结果后，任务应显示 `web-artifact` backend。

## 3. OCR 只有位置，没有文字内容

说明当前使用 `builtin-ink`。配置 PaddleOCR Token：

```bash
editppt config --paddle-ocr-token "你的Token"
editppt run hints "<RUN>"
```

重新导出 Handoff：

```bash
editppt web export "<RUN>" --out handoff-with-ocr.zip
```

## 4. `.pptx` 报“不支持复杂 PPTX”

当前轻量路径只支持每页一张铺满页面图片的 PPTX。将原生/混合型 PPTX 导出为 PDF 或页面 PNG 后重新执行：

```bash
editppt prepare exported.pdf
```

## 5. `.ppt` 报找不到 Office converter

安装 LibreOffice，并确认：

```bash
soffice --version
```

或先手工将 `.ppt` 转换为 `.pptx`/PDF。

## 6. `web export` 报缺少 instruction 文件

确认当前代码分支包含：

```text
skills/image-to-editable-ppt/prompts/web-batch-worker.md
skills/image-to-editable-ppt/references/page-decision-tree.md
skills/image-to-editable-ppt/references/manifest-schema.md
skills/image-to-editable-ppt/references/web-bundle-protocol.md
```

重新安装 editable CLI 后再执行。

## 7. GPT 网页端没有输出 ZIP

明确要求：

```text
严格按照包内 web-bundle-protocol 输出 reconstruction 或 revision-result ZIP。
不要直接生成 PPTX，不要只返回 JSON 文本或页面说明。
```

确保开启文件处理/代码执行能力。输出必须包含 `bundle.json` 和每页完整 `manifest.json`。

## 8. `web inspect` 报路径、符号链接或 ZIP 限制错误

返回包违反安全协议。不要手工绕过校验。让网页端重新打包，确保：

- POSIX 相对路径；
- 无 `..`、绝对路径、盘符或反斜杠；
- 无符号链接；
- 无重复成员；
- 不包含超大无关文件。

## 9. `web import` 报 Job ID 不匹配

该 Reconstruction Bundle 不是由当前 `RUN` 的 Handoff 生成。使用对应任务目录，或重新从当前 RUN 导出 Handoff。

不要手工修改 `job_id`，因为页面原图哈希仍会不一致。

## 10. `web import` 报 source hash mismatch

常见原因：

- `source.png` 被修改；
- 使用了另一个任务的结果包；
- prepare 后重新生成了页面；
- 网页端错误改写了 `source_sha256`。

从当前 RUN 重新导出 Handoff，并让网页端原样复制每页 SHA-256。

## 11. `web import` 报 missing asset

Manifest 引用了不存在的文件。网页端结果包中必须存在：

```text
pages/page_NNN/assets/<对应文件>
```

同时应有合法 `asset_provenance`。让 GPT 网页端重新打包，不要在本地创建空文件绕过校验。

## 12. `web build` 页面构建失败

查看：

```text
<RUN>/pages/page_NNN/validation.json
<RUN>/pages/page_NNN/page_result.json
<RUN>/failed_pages.json
```

然后导出失败页：

```bash
editppt revision export "<RUN>" --out revision.zip
```

不要直接修改 `page_jobs.json`。

## 13. 页面预览报缺少 ImageMagick

页面 Manifest 使用 SVG 图片。安装 ImageMagick，使以下任一命令可用：

```bash
magick -version
convert -version
```

Web 模式不会静默忽略无法预览的 SVG，因为那会导致错误的视觉验收。

## 14. 中文预览字体异常

Runtime 会依次查找：

- Windows：微软雅黑、黑体、等线；
- Linux：Noto Sans CJK、思源黑体、文泉驿；
- macOS：苹方、华文黑体、Arial Unicode。

Linux 建议安装：

```bash
sudo apt-get install fonts-noto-cjk
```

实际 PowerPoint 显示还取决于 Manifest 中指定字体以及打开文件电脑的字体安装情况。

## 15. 页面验证通过但视觉仍有明显差异

结构校验不是视觉语义判断。执行 Revision 轮次，让 GPT 查看：

- `source.png`；
- `preview.png`；
- `split_assets_contact.png`；
- `validation.json`；
- 当前 Manifest。

在 `correction-request.json` 中补充人工观察也可以，但不要降低 Manifest/资产来源门禁。

## 16. Revision Apply 后页面仍显示旧结果

确认已经再次运行：

```bash
editppt web build "<RUN>"
```

Revision Apply 只替换 Manifest/资产并把变更页面重置为 `pending`；重新构建后才产生新的页面 PPTX 和预览。

## 17. Revision round 已存在

每轮编号只能应用一次。检查：

```text
<RUN>/revisions/round-XX/
```

从新的失败状态导出下一轮，不要覆盖已有历史。

## 18. 最终 PPTX 没有生成

只有全部页面被记录且通过验证时才 Finalize。检查：

```bash
editppt run status "<RUN>"
cat "<RUN>/failed_pages.json"
```

修正失败页后重新运行 `editppt web build`。

## 19. 文件含保密信息

Handoff 包包含页面原图，上传 GPT 网页端属于外部处理。组织不允许外传时，不应使用 Web Batch 模式；使用本地/Codex 原 Skill 或企业批准的私有模型环境。

Runtime 的 ZIP 安全校验只能防止恶意结果包，不能替代数据合规审批。
