# 听见 · LocalCaptions

Windows 10/11 本地实时字幕个人项目：捕获电脑正在播放的声音，识别语音，在置顶悬浮窗显示当前字幕。以实际视频学习需求发起，采用 Codex AI 辅助开发；项目作者负责需求、使用反馈与迭代目标，代码和测试由 AI 协作完成。它不是自研语音模型。

## 已实现

- WASAPI 系统输出音频回环与设备选择，不默认使用麦克风。
- 中英 Paraformer 原生流式识别；可选 SenseVoice INT8 声学复核；faster-whisper 多语言兼容模式。
- 本地翻译，原文/译文/双语模式；中文统一 OpenCC 简体转换。
- 一个当前字幕块、最多两行，临时结果原位更新，长句分页；置顶、拖动、宽度/字号/颜色/透明度、锁定与鼠标穿透。
- 开始/暂停/停止、托盘与快捷键、TXT/SRT 导出；有界任务队列与过期结果防护。
- 日常运行不上传音频、不保存原始录音；模型首次下载需要联网。

## 环境与启动

Windows 10/11 x64，原生 Python 3.12，建议4核CPU、8 GB内存及2 GB以上可用磁盘。默认CPU INT8，不要求CUDA。

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\.venv\Scripts\python.exe -m captioner.download --model streaming-zh-en
.\.venv\Scripts\python.exe -m captioner.download --model sensevoice
.\start.cmd
```

选择实际播放音频的输出设备，再点击开始。仅原文字幕可离线使用已下载模型；跨语言翻译需要通过界面下载相应语言包。`Ctrl+Shift+S` 开始/暂停/恢复；`Ctrl+Shift+L` 解除穿透与锁定。控制台关闭后隐藏到托盘，从托盘退出。

流式中英模型约237 MB，增强复核约240 MB；Whisper small约486 MB。模型保存在 `%LOCALAPPDATA%\LocalCaptions`，仓库不包含模型、个人字幕、录音或可执行文件。

## 测试与打包

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

`requirements-lock.txt` 记录开发机依赖快照。PyInstaller采用onedir，必须分发整个输出文件夹并保留第三方许可证，模型仍单独下载。`scripts/make_fixtures.ps1` 可生成合成语音测试素材；真实系统回环测试需在本机有声输出下执行。测试素材与历史运行产物不随源码发布。`record-sample.cmd` 只有手动运行时才保存诊断录音，会记录选定输出设备的所有声音。

历史验证：45项单元/Qt组件测试通过；冻结版本610秒真实WASAPI回环无音频丢弃和错误事件；最终EXE真实回环、双语与两行显示验证通过。测试条件与完整边界见 [SPEED_RESULTS.md](SPEED_RESULTS.md)、[LATENCY_RESULTS.md](LATENCY_RESULTS.md)、[TEST_RESULTS.md](TEST_RESULTS.md)。公开仓库不附历史录音与原始字幕日志；结果为开发机记录，需要自行复测。

## 已知限制

- 同一设备上的多个应用声音会混合；不能读取播放器倍速，不绕过受保护内容。独占全屏可能遮挡普通置顶窗。
- 默认流式路径支持中英；Whisper兼容模型支持更多语言，但延迟和质量不同，详见 [LANGUAGES.md](LANGUAGES.md)。
- 快速讲话、背景音乐、专业同音词仍可能识错。3×测试不可靠，中文2×并未普遍改善；不保证所有视频低于1秒或所有语言准确。
- 准确率素材主要为合成课程与一个短真人英文样本，不能外推到完整真人课程；组件测试不等于音频准确率验收。
- 长句后半段、数小时持续运行、跨显示器DPI、CUDA及独占全屏未全面验证。
- SRT时间相对当前捕获会话，不跟踪视频跳转后的播放器时间。

## 许可

项目自身代码采用 [MIT](LICENSE)。依赖与模型保留各自许可，参见 [THIRD_PARTY.md](THIRD_PARTY.md)。使用第三方模型进行推理，不声明拥有模型权重或训练成果。
