$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
New-Item -ItemType Directory -Force artifacts | Out-Null
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice('Microsoft Zira Desktop')
    $synth.SetOutputToWaveFile((Join-Path $PWD 'artifacts/english.wav'))
    $synth.Speak('Hello everyone. This is a test of real time captions. The weather is beautiful today. We are listening to audio from the computer.')
    $synth.SetOutputToNull()
    $synth.SelectVoice('Microsoft Huihui Desktop')
    $synth.SetOutputToWaveFile((Join-Path $PWD 'artifacts/chinese.wav'))
    $synth.Speak('大家好，这是电脑实时字幕的测试。今天的天气非常好。我们正在验证系统声音捕获和中文语音识别。')
    $synth.SetOutputToNull()
    $synth.SetOutputToWaveFile((Join-Path $PWD 'artifacts/course.wav'))
    $synth.Speak('今天讨论多层平壁的稳态导热。首先确定两侧的边界条件，再计算每一层材料的热阻。总热阻等于各层热阻与两侧对流热阻之和。温度差除以总热阻，就得到通过平壁的热流量。')
} finally { $synth.Dispose() }
