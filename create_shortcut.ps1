$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path

$BuiltExePath = "$ProjectPath\dist\1SalemBOT\1SalemBOT.exe"
$PythonPath = "$ProjectPath\.venv\Scripts\pythonw.exe"
$MainPath = "$ProjectPath\main.py"
$IconPath = "$ProjectPath\assets\bot_icon.ico"

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = "$Desktop\1SalemBOT.lnk"

$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)

$TargetPath = $PythonPath
$Arguments = "`"$MainPath`""

if (Test-Path $BuiltExePath) {
    $TargetPath = $BuiltExePath
    $Arguments = ""
}

$Shortcut.TargetPath = $TargetPath
$Shortcut.Arguments = $Arguments
$Shortcut.WorkingDirectory = $ProjectPath

if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}

$Shortcut.Save()

if (Test-Path $BuiltExePath) {
    Write-Host "Shortcut created successfully. It points to the packaged desktop app."
} else {
    Write-Host "Shortcut created successfully. Run build_windows_app.ps1 to generate a pinnable desktop exe."
}
