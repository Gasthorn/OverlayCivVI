# Copie src/mod/ dans le dossier Mods de Civ VI.
# Utilise le dossier Documents réel de Windows (qui peut être redirigé vers OneDrive).

$documents = [Environment]::GetFolderPath('MyDocuments')
$target = Join-Path $documents "My Games\Sid Meier's Civilization VI\Mods\CivVISmartOverlay"
$source = Join-Path $PSScriptRoot "..\src\mod"

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse -Force
Write-Output "Mod installé dans : $target"
