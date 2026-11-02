# Crée sur le bureau le raccourci qui démarre le service moteur et l'overlay (spec 00 §3.1).
# Utilise le dossier Bureau réel de Windows (qui peut être redirigé vers OneDrive).

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'

if (-not (Test-Path $pythonw)) {
    Write-Error "Environnement virtuel introuvable : $pythonw"
    exit 1
}

$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Civ VI Smart Overlay.lnk'
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + (Join-Path $root 'src\launcher.py') + '"'
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = Join-Path $root 'src\ui\styles\overlay.ico'
$shortcut.Description = 'Civ VI Smart Overlay'
$shortcut.Save()
Write-Output "Raccourci : $path"
