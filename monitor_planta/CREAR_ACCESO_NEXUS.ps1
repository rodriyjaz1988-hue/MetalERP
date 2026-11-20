# Crea el acceso directo "Nexus" en el escritorio con el icono nexus.ico
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$esc  = [Environment]::GetFolderPath('Desktop')
$ws   = New-Object -ComObject WScript.Shell
$viejo = Join-Path $esc 'Monitor de planta.lnk'
$nuevo = Join-Path $esc 'Nexus.lnk'
$python = 'C:\Python314\pythonw.exe'
if (Test-Path $viejo) {
    $t = $ws.CreateShortcut($viejo).TargetPath
    if ($t) { $python = $t }
}
$s = $ws.CreateShortcut($nuevo)
$s.TargetPath = $python
$s.Arguments = '"' + (Join-Path $aqui 'monitor_ventana.py') + '"'
$s.WorkingDirectory = $aqui
$s.IconLocation = (Join-Path $aqui 'nexus.ico') + ',0'
$s.Description = 'Nexus - MetalERP'
$s.Save()
if (Test-Path $nuevo) {
    if (Test-Path $viejo) { Remove-Item $viejo -ErrorAction SilentlyContinue }
    Write-Host 'Listo: acceso directo "Nexus" creado en el escritorio.'
} else {
    Write-Host 'No se pudo crear el acceso directo.'
}
