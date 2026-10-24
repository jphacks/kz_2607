param([string]$Text, [string]$Out)
# Windowsの日本語音声で、テスト用のWAV(16kHz・モノラル・16bit)を作る
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$ja = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq "ja-JP" } | Select-Object -First 1
if (-not $ja) { Write-Host "No Japanese voice is installed"; exit 1 }
$s.SelectVoice($ja.VoiceInfo.Name)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($Out, $fmt)
$s.Speak($Text)
$s.Dispose()
Write-Host "OK: $Out"
