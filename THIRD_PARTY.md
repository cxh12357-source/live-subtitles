# 第三方组件与模型

项目自身源码使用 MIT 许可；下列依赖与模型保留各自许可。打包目录 `third-party-licenses/` 收集了安装发行包中的 LICENSE/COPYING/NOTICE 文件，不能用项目自身许可替代它们。

- Qt/PySide6/Shiboken：[Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html)，开源发行采用 LGPL/GPL 及相关第三方许可。本程序动态加载 Qt DLL，没有修改 Qt 源码。
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：MIT。
- [Whisper](https://github.com/openai/whisper)：MIT；采用 Systran 转换为 CTranslate2 格式的 tiny/base/small 权重。
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)：MIT。
- [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)：MIT，包含 PortAudio 等组件，详见发行包。
- [Silero VAD](https://github.com/snakers4/silero-vad)：MIT，faster-whisper 附带的 ONNX 语音活动检测模型。
- [ONNX Runtime](https://github.com/microsoft/onnxruntime)：MIT。
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)：Apache 2.0，使用本地 CPU 流式接口。
- [SenseVoice 模型](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17)：模型卡标明 Apache 2.0，采用 INT8 声学复核模型，不修改权重。
- 倍速英文真人测试使用 LibriSpeech 的 `1272-128104-0000`，CC BY 4.0；署名 Vassil Panayotov, Guoguo Chen, Daniel Povey, Sanjeev Khudanpur, “LibriSpeech: An ASR corpus based on public domain audio books”, ICASSP 2015。样本副本取自 QwenLM/Qwen-Audio 的 `assets/audio/1272-128104-0000.flac`，参考稿来自 LibriSpeech 同名条目。测试变体仅用 FFmpeg atempo 改变速度，原样本不改内容。这是测试素材，不随 EXE 内嵌，不代表对白/弱读的全面覆盖。
- [中英流式 Paraformer 模型](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en/blob/main/README.md)：模型卡标明 Apache 2.0，由 ModelScope/Alibaba 的在线 Paraformer 转换；使用 INT8 编码器/解码器，不修改模型权重。
- [python-soxr](https://github.com/dofuuz/python-soxr)：采用 libsoxr 的有状态重采样，随包保留 LGPL 等对应发行声明。
- [SentencePiece](https://github.com/google/sentencepiece)：Apache 2.0。
- [Argos Translate](https://github.com/argosopentech/argos-translate)：用于语言包索引/格式；模型许可与软件许可独立。
- 已下载的 **English → Chinese 1.9** 语言包来自 OPUS-MT，包内 README 标明原模型使用 **CC BY 4.0**。署名：Jörg Tiedemann and Santhosh Thottingal, *OPUS-MT — Building open translation services for the World*, EAMT 2020, Lisbon, Portugal。模型 README 保存在 `%LOCALAPPDATA%/LocalCaptions/translation/en_zh/README.md`。程序对输出做简体转换和分词标记清理，不表示原作者认可本程序。
- NumPy、SciPy、PyAV/FFmpeg、OpenCC、Requests、Hugging Face Hub、Tokenizers、PyInstaller 及其传递依赖：见随包许可文件与对应项目，重新分发时保留声明。

模型不嵌入 EXE。新增语言包下载时应保留它的 README/许可证；不同语言包许可可能不同。
