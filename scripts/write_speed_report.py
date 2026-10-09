"""Generate tables strictly from recorded, completed measurement files."""
import json
from pathlib import Path
root=Path('artifacts')
before=json.loads((root/'speed-before-summary.json').read_text(encoding='utf-8'))
after=json.loads((root/'speed-final-summary.json').read_text(encoding='utf-8'))
assert after['released'] and not after['errors'] and after['reviews'].get('guarded') and after['reviews'].get('bounded_prefix'), 'Final guarded run must finish successfully before publication'
def pct(s):return '—' if s['median'] is None else f"{s['median']*100:.1f}%"
def timing(s):return '—' if s['median'] is None else f"{s['median']/1000:.3f} / {s['p95']/1000:.3f}"
lines=['# 倍速字幕修复实测（2026-09-23～24）','',
'## 结论与实现','',
'默认无需知道播放器倍速。保留 Paraformer 原生流式快稿，新增本地 SenseVoice INT8 声学复核；中途最多两次、结束最多一次，复核音频约 12 秒上限，一个执行中/一个待处理。没有文本润色模型，没有上传音频，没有改采样率，也没有按慢速墙钟喂入音频。性能/准确率并非所有档位都改善，下面保留退步和高错误率结果。','',
'原实现并非捕获采样率错误：同一输出端点实际播放并捕获的波形相关系数约 0.99。保音高加速后错误增加，说明主要瓶颈包含模型的快速语音能力。Whisper base/small 的 beam 1/3 和时间拉伸消融均已实跑；更大模型/更大 beam 未普遍改善中文，所以没有直接换掉原生流式器。','',
'流式识别保持跨块状态，未改成独立短音频片。超过 12 秒后优先在至少 120 ms 的低能量边界确认；无可靠停顿最多 45 秒限制上下文并警告，替代此前无条件 30 秒硬切。极端连续讲话的边界仍可能不准确。增强只修改当前语句仍匹配的前缀；不同会话/暂停代次/语句、已改写前缀、英文未完成词的边界不拼接。更改倍速提示不能突破每句两次中途复核上限。历史保存不重复，迟到旧句不覆盖当前字幕。','',
'先做的一轮610秒盲目采用复核稿的实验，在中文2.5×出现退步：最终CER中位数15.3%，当轮原生稿8.3%。原始记录保留为 speed-after-ungated.json。之后加入保守中文一致性检查，再完整重跑610秒；下表采用重跑结果。规范化文字差异最多约10%（短句2字），否则保留原生稿/此前小范围修正。它不是正确性或置信度估计，可能拒绝正确结果；显式术语路径不套用这个自动门限。','',
'另外复现了跨模型覆盖范围差异：“温差除以热”被复核成“温差除以热阻”后直接接上后续原生“阻”，会产生重复。最终版中途修正要求中文字符/英文词单元数一致，并拦截未完成英文词边界；没有可靠词级时间戳时拒绝不确定拼接，而非按重复文本删除。结束复核拥有固定的完整音频区间，可以恢复漏词/真实重复。这个保护可能降低中途修正频率。','',
'手动倍速是可选的连续数值提示（0=未知，界面可填到4），只调整复核时机；不是播放器接口，也不是语速推断。课程术语最多200字符，仅传给本次 Whisper small 声学解码，仅复制声学结果中实际出现术语的等长局部修正，保留其他文字，不插入/删除词语，不保存全局词表。中文展示仍统一 OpenCC t2s，当前块最多两行。','',
'## 测试条件与口径','',
'Windows 11、Ryzen 7 7800X3D、32 GB RAM、RTX 4070 存在但未使用。Paraformer 和 SenseVoice 各用 CPU 两线程 INT8；可选术语 Whisper small 用 CPU 四线程、beam 3。版本沿用 requirements-lock.txt。','',
'测试素材：中文专业课程为 Microsoft Huihui SAPI 合成语音，原稿72字；普通英文为 Microsoft Zira SAPI 合成语音，原稿23词。真人英文为 LibriSpeech 1272-128104-0000，参考稿17词，来自公开标注/示例。没有获得用户原课程的人声和人工核对稿，也没有进行本轮人工逐字复听，**不能称为完整的真人课程、自然对话连读/弱读验收**。真人朗读只是一个很短的补充样本。','',
'使用 PyAV/FFmpeg atempo 生成保音高的1、1.25、1.5、2、2.5、3倍变体；大于2的变换串联较小因子。采样率仍是16000 Hz。切速样本在同一原音四个连续部分依次施加1→2→1.25→2.5；没有读取或操纵浏览器倍速接口，属于音频内切速回环测试，分段变换边界也可能有处理伪影。','',
'真实路径：测试语音 → 非默认 High Definition Audio Device 扬声器 → 同端点 WASAPI回环（48kHz双声道Float32）→ 有状态16kHz重采样 → 实际识别/复核 → Qt控件。没有注入预设字幕。校准用波形互相关；未把用户系统音频保存成文件。旧版410秒两轮，新版610秒三轮，均未给倍速提示、未填术语。','',
'准确率按完整参考稿计算：中文CER、英文WER；去标点、统一简体/英文小写，不把英文字符错误率当WER。raw是原生模型最后的未复核稿；末次临时稿是界面在确认前实际收到的完整临时文本（不拼接分页），可能含早期复核，也可能仍缺尾词；因此其全稿错误率包含尚未出现的尾部，不能解释成每个时间点的已听前缀错误率。最终稿另列，绝不冒充临时稿质量。','',
'首批可读按参考语言判断：中文至少两个汉字，英文至少一个三字母以上词；这个显示门限不代表识别正确，须同时看错误率。最终延迟从最后有声帧算到最终Qt控件更新，不包含讲话时长。时间为控件更新而非物理屏幕光子时间；Windows/Python单调时钟约15.6ms粒度，统计为0的短耗时只表示低于粒度。N较小，P95是描述性插值，不是泛化保证。没有做语义等价归一化，例如 mr/mister 也可能计为词差异。','',
'## 准确率对照（各轮中位数）','',
'| 素材@倍速 | N旧/新 | 旧稿 | 新原生未复核 | 新末次临时稿 | 新最终稿 |',
'|---|---:|---:|---:|---:|---:|']
for key,b in before['groups'].items():
    a=after['groups'][key]
    lines.append(f"| {key} | {b['n']}/{a['n']} | {pct(b['final_error'])} | {pct(a['raw_error'])} | {pct(a['last_provisional_error'])} | {pct(a['final_error'])} |")
lines+=['','## 延迟对照（中位数 / P95，秒）','',
'| 素材@倍速 | 旧首批可读 | 新首批可读 | 旧最终确认 | 新最终确认 |','|---|---:|---:|---:|---:|']
for key,b in before['groups'].items():
    a=after['groups'][key]
    lines.append(f"| {key} | {timing(b['first_readable_ms'])} | {timing(a['first_readable_ms'])} | {timing(b['final_ms'])} | {timing(a['final_ms'])} |")
lines+=['','## 漏词、重复和术语','',
'逐段参考稿、原生稿、末次临时稿、最终稿，以及删除/插入/替换次数均在 speed-before-summary.json 和 speed-final-summary.json 的 clips 中。最终稿采用实际进入Qt控件的确认文本；若已切新句而未显示，不把后台结果当成已显示字幕。后台生成稿另存 generated_final。插入不等同于重复；excess_adjacent_repeats 只标记相对参考稿多出的相邻1～3单元重复候选，不替代人工核对。实现没有按文本重复删除词语；回归测试明确保留 “we we”。','',
'| 素材 | 删除单位：旧/新 | 插入单位：旧/新 | 重复候选：旧/新 |','|---|---:|---:|---:|']
for fixture in ('course','english','human-english'):
    br=[r for r in before['clips'] if r['fixture']==fixture];ar=[r for r in after['clips'] if r['fixture']==fixture]
    # Per-clip means, because old and new repetition counts differ.
    avg=lambda rs,key:sum(r['final_error'][key] for r in rs)/len(rs)
    rep=lambda rs:sum(r['excess_adjacent_repeats']['final'] for r in rs)/len(rs)
    lines.append(f"| {fixture}（每段均值） | {avg(br,'deletions'):.2f} / {avg(ar,'deletions'):.2f} | {avg(br,'insertions'):.2f} / {avg(ar,'insertions'):.2f} | {rep(br):.2f} / {rep(ar):.2f} |")
lines+=['','默认未给术语提示；“平壁”等同音词仍会识错，简体转换不会修复声学错误。各术语原稿/未复核稿/最终稿出现次数在 clips[].terms。可选术语实验单列于下方，不混入默认结果。','',
'## 持续运行与负载','',
f"新版连续 {after['seconds']} 秒：音频丢弃 {after['dropped']}，退出后设备/线程释放 {after['released']}；错误事件 {len(after['errors'])}。",
f"首批可读显示缺失 {after['missing_displays']['first']} 段，最终确认显示缺失 {after['missing_displays']['final']} 段；缺失项不计入延迟分位数，不以0秒代替。准确率仍保留对应的遗漏。",
f"复核 {after['reviews']['count']} 次，前缀仍匹配而被接受 {after['reviews']['accepted']} 次；计算中位数/P95 {timing(after['reviews']['inference_ms'])} 秒，排队 {timing(after['reviews']['queue_ms'])} 秒。未接受不意味着主音频被丢弃。",
f"RSS峰值 {after['memory']['peak_mib']:.1f} MiB，结束前 {after['memory']['last_mib']:.1f} MiB；每2秒抽样的主音频/ASR队列峰值 {after['memory']['max_raw']}/{after['memory']['max_asr']}。",
f"第一/最后三分之一ASR排队中位数/P95：{timing(after['asr_queue_first'])} / {timing(after['asr_queue_last'])} 秒。测试进程保存诊断事件，因此少量内存增加不能直接归因于生产识别器；生产默认无诊断日志，历史也有上限。十分钟不能证明全天不泄漏。",'',
'## 复现与限制','',
'```powershell',
'.venv\\Scripts\\python.exe -m scripts.make_speed_corpus',
'.venv\\Scripts\\python.exe -m scripts.latency_benchmark --variant speed-baseline --transport loopback --isolated-device --seconds 410 --mode original --corpus artifacts/speed/manifest.json --output artifacts/speed-before.json',
'.venv\\Scripts\\python.exe -m scripts.latency_benchmark --variant reviewed --transport loopback --isolated-device --seconds 610 --mode original --corpus artifacts/speed/manifest.json --output artifacts/speed-final.json',
'.venv\\Scripts\\python.exe -m scripts.analyze_speed artifacts/speed-before.json artifacts/speed-final.json',
'```','',
'仅一个输出设备时去掉 --isolated-device 并关闭其他音源。使用 --transport replay 是真实WAV按时钟送入的组件测试，不是真实系统回环。--speed-hint 可测试手动提示，--hotwords 可测试用户提供的术语。所有默认矩阵均为提示0/术语空白。','',
'真实原课程、自然对话中系统性的弱读/连读、强背景音乐、第三语言、其他播放器的具体变速算法和更慢CPU仍未验证。高倍速明显存在可用边界，不能因最终稿改善而宣称临时字幕同样准确。模型预训练数据可能包含公开演示样本，本组小样本不是独立泛化测试集。','',
'参考：[LibriSpeech 数据集与许可](https://www.openslr.org/12/)、[真人英文样本来源](https://github.com/QwenLM/Qwen-Audio/blob/main/assets/audio/1272-128104-0000.flac)、[SenseVoice官方接口](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)、[FFmpeg atempo](https://ffmpeg.org/ffmpeg-filters.html#atempo)。','']
from scripts.analyze_latency import stats
events=json.loads((root/'speed-final.json').read_text(encoding='utf-8'))['events']
lines+=['## 分阶段耗时（默认610秒，毫秒，中位数 / P95）','','| 阶段 | 中位数 / P95 |','|---|---:|']
for label,stage,key in [('采集块','capture','block_ms'),('驱动缓冲年龄','capture','portaudio_age_ms'),('预处理排队','audio','queue_ms'),('重采样处理','audio','preprocess_ms'),('重采样延迟','audio','resampler_delay_ms'),('识别排队','asr','queue_ms'),('流式推理','asr','inference_ms'),('语句结束等待','asr','endpoint_wait_ms'),('复核推理','review','inference_ms'),('结果到Qt控件','display','ui_ms')]:
    v=stats(e[key] for e in events if e['stage']==stage and key in e and (key!='endpoint_wait_ms' or e.get('final')))
    lines.append(f"| {label} | {v['median']} / {v['p95']} |")
lines+=['','本轮准确率矩阵关闭翻译，因此不能从这些数据推导翻译延迟。打包双语测试另验证翻译功能；此前独立翻译测量见 LATENCY_RESULTS.md。','',
        '## 长句与可选术语复测','']
for name in ('speed-long-before','speed-long','speed-terms'):
    p=root/(name+'-summary.json')
    if not p.exists():continue
    extra=json.loads(p.read_text(encoding='utf-8'))
    lines.append(f"{name}：{extra['seconds']}秒，音频丢弃{extra['dropped']}，错误{len(extra['errors'])}，释放{extra['released']}。未进入确认显示的语句块{extra['missing_displays'].get('unconfirmed_blocks','未统计')}个。")
    lines+=['','| 样本 | N | 原生错误率 | 末次临时 | 确认块错误率 | 最后实际显示错误率 | 首显秒中位/P95 | 确认秒中位/P95 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for key,g in extra['groups'].items():
        lines.append(f"| {key} | {g['n']} | {pct(g['raw_error'])} | {pct(g['last_provisional_error'])} | {pct(g['final_error'])} | {pct(g['last_shown_error'])} | {timing(g['first_readable_ms'])} | {timing(g['final_ms'])} |")
    lines.append('')
lines+=['长句是33.68秒合成课程串接并缩短停顿至120毫秒，单次测试不能估计稳定P95。术语实验手动指定中文，填写“多层平壁，平壁，稳态导热，边界条件，热阻”，因此不能当作只改变词表一个变量的因果实验。确认块错误率只拼接真正显示过的确认块；若修正迟到，临时稿已经显示却未确认，会被该口径计为缺失。最后实际显示错误率保留该临时稿，仍不采用后台未显示修正。两者分别报告。','',
        '术语初次整句替换曾把正确的“温度差”改成“温补差”；原始记录保留在 speed-terms-unrestricted.json。最终实现只接受声学模型确实识别出的术语等长局部修改，不能恢复术语漏字，也不能保证术语提示永不诱发错误。它不是凭词表自动替换所有同音词。','']
pack=root/'packaged-speed.json'
if pack.exists():
    p=json.loads(pack.read_text(encoding='utf-8'));es=p['events']
    counts={k:sum(e['kind']==k for e in es) for k in ('partial','final','translated','display')}
    lines+=['## 交付验证','',f'Windows EXE实际回环烟雾测试48秒：{counts}；设备线程释放{p["released"]}。脚本断言显示最多两行、统一简体、临时先于确认、历史每句唯一、无识别/翻译错误。45项单元/Qt组件测试通过；它们验证状态逻辑，不是音频准确率测试。','']
Path('SPEED_RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
