# FlowPDF Windows 构建报告

## 固定构建基线

- 应用版本：`0.1.0a1`
- 操作系统：Windows 10/11 x64
- Python：CPython `3.14.5` x64
- PySide6：`6.11.1`
- PyMuPDF：`1.28.2`
- Pillow：`12.2.0`
- PyInstaller：`6.22.1`
- 完整直接及打包依赖：见 `requirements-build.txt`

正式构建脚本会拒绝其他 Python 补丁版本，避免发布包在不明确的解释器上生成。

## 构建命令

```powershell
scripts\build_windows.ps1
```

输出位置：`dist\FlowPDF\FlowPDF.exe`（便携目录版）。构建目录和输出目录不提交 Git。

## 验证状态

- 当前开发机 PyInstaller 构建：已完成。隔离 `.venv-build` 仅安装锁定依赖；产物 188 个文件，
  合计 162.27 MiB，主 EXE 约 4.61 MB。
- 打包程序启动烟雾测试：已通过，退出码 0；移除 `PYTHONPATH` 并把 `PATH` 缩减为 Windows
  系统目录后仍通过。
- 无 Python 开发环境的干净 Windows 10/11 电脑：尚未验证。
- 中文目录启动：当前开发机已通过，退出码 0。
- 打包态中文 PDF 打开与安全另存：已通过；输出重新打开后为 2 页且文字层可读取。
- 代码签名：未签名，Windows 可能显示“未知发布者”提示。

## 当前开发机性能基线

2026-08-16 在 Python 3.14.5、24 逻辑处理器的当前 Windows 开发机上运行
`scripts\benchmark.ps1`。测试对象是脚本生成的 300 页轻量 PDF（50,551 字节），因此只适合
检测代码回归，不代表真实大型文档：打开 0.0112 秒、第一页同步渲染 0.0033 秒、300 张低清
缩略图 0.0250 秒、全文字提取 0.0170 秒、保存 0.0056 秒；进程峰值工作集约 97.3 MB。
模拟快速跳页时，队列从 300 个请求降到 1 个有效请求；缩略图缓存使用 6.61 MB，配置上限
536.87 MB。原始 JSON 由脚本写到被 Git 忽略的 `output\benchmark.json`。

## 许可证

发布前必须依据 `LICENSES/THIRD_PARTY.md` 完成最终法律审核。特别注意 PyMuPDF 的
AGPL/商业双重许可，以及 PySide6/Qt 的 LGPLv3/GPLv3/商业许可条件。项目自身当前没有
许可证授权，不得把整个应用标注为 MIT。
