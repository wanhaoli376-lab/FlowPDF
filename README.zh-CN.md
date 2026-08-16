# FlowPDF

FlowPDF 是一款面向 Windows 10/11 的本地 PDF 查看与编辑软件。界面默认使用简体中文，
文档只在本机处理：不上传、不登录、不含遥测和广告。

## 当前状态

本仓库目前处于 `0.1.0a1` 开发阶段。项目会优先完成可靠查看、后台渲染、内存受限缓存、
安全保存，再逐步补齐页面管理、文字、图片和批注编辑。功能状态以本节和 CHANGELOG 为准，
尚未完成的能力不会写成“完整支持”。

## 启动

开发与正式构建基线使用 Python 3.14，项目声明兼容 Python 3.12–3.14。

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
python -m flowpdf
```

开发环境也可以运行 `scripts\run_dev.ps1`。测试和检查分别使用：

```powershell
scripts\test.ps1
scripts\lint.ps1
```

## 重要限制

- PDF 不是 Word 文档；复杂 PDF 中已有文字不一定能完全保留原版式。
- 原字体缺失时会替换字体，替换结果可能与原版式不同。
- 新文字明显长于原文字时，可能需要缩小字号或手动调整区域。
- 扫描型 PDF 需要可选 OCR；OCR 不是首版硬依赖。
- 首版不支持完整段落自动重排。
- 首版签名只表示视觉签名，不是具有证书认证能力的数字签名。
- 某些受权限限制、加密异常、资源异常或损坏的 PDF 可能无法编辑。

## 隐私与安全

FlowPDF 不执行 PDF 内嵌 JavaScript，不自动打开外部链接或附件。密码只应保留在内存中，
日志不记录密码和文档正文。编辑默认写入副本，不覆盖源文件。

## 许可证

项目自身尚未授予开源许可证。第三方依赖的初步核查见
[`LICENSES/THIRD_PARTY.md`](LICENSES/THIRD_PARTY.md)。发布或分发前必须再次核对实际锁定版本的
许可证文本，尤其是 PyMuPDF 的 AGPL/商业双重许可要求。
