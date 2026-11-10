# Diagnostico de la conexion PC -> torno Fanuc. Solo mira, no cambia nada.
$TORNO = '192.168.10.200'; $PC = '192.168.10.5'; $PUERTO = 8193; $ADAPTADOR = 'Ethernet'
$salida = New-Object System.Collections.Generic.List[string]
function Linea($t, $color = 'Gray') { Write-Host $t -ForegroundColor $color; $salida.Add($t) }
function Caso($letra, $titulo, $pasos) {
  Linea ''; Linea "==> CASO $letra - $titulo" 'Yellow'
  foreach ($p in $pasos) { Linea "    $p" 'White' }
}
Linea "Diagnostico torno $TORNO  ($(Get-Date -Format 'dd/MM/yyyy HH:mm'))" 'Cyan'
Linea ''
$ad = Get-NetAdapter -Name $ADAPTADOR -ErrorAction SilentlyContinue
if (-not $ad) {
  Linea "No encuentro el adaptador de red '$ADAPTADOR'. Adaptadores de esta PC:" 'Red'
  Get-NetAdapter | ForEach-Object { Linea ("   " + $_.Name + "  (" + $_.Status + ")") }
} elseif ($ad.Status -ne 'Up') {
  Linea "1) Cable: NO detectado ($($ad.Status))" 'Red'
  Caso 'A' 'La PC no ve el cable' @(
    'Con el torno PRENDIDO DEL TODO, cable en el conector de red de ATRAS de la pantalla (CD38A).',
    'Mirar que se prenda la luz del conector. Probar otro cable.',
    'Reiniciar el puerto (cmd como administrador):',
    '  netsh interface set interface name="Ethernet" admin=disabled',
    '  netsh interface set interface name="Ethernet" admin=enabled',
    'Si sigue igual: poner un switch en el medio (PC -> switch -> torno).')
} else {
  Linea "1) Cable: detectado ($($ad.LinkSpeed))" 'Green'
  $ips = @(Get-NetIPAddress -InterfaceAlias $ADAPTADOR -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { $_.IPAddress })
  if ($ips -notcontains $PC) {
    Linea "2) IP de la PC: $($ips -join ', ')  (tiene que ser $PC)" 'Red'
    Caso 'B' 'La PC no tiene la IP fija' @(
      'En cmd como administrador:',
      '  netsh interface ipv4 set address name="Ethernet" static 192.168.10.5 255.255.255.0',
      'Despues volver a correr este diagnostico.')
  } else {
    Linea "2) IP de la PC: $PC" 'Green'
    $ping = Test-Connection -ComputerName $TORNO -Count 2 -Quiet -ErrorAction SilentlyContinue
    $vecino = Get-NetNeighbor -IPAddress $TORNO -ErrorAction SilentlyContinue | Where-Object { $_.State -notin 'Unreachable', 'Incomplete' }
    if ($ping) { Linea "3) Ping al torno: responde" 'Green' } else { Linea "3) Ping al torno: NO responde" 'Red' }
    if ($vecino) { Linea "   El torno aparece en la red (MAC $($vecino.LinkLayerAddress))" 'Green' } else { Linea "   El torno NO aparece en la red" 'Red' }
    $tcp = Test-NetConnection -ComputerName $TORNO -Port $PUERTO -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) {
      Linea "4) Puerto FOCAS ${PUERTO}: abierto" 'Green'
      Caso 'F' 'La red esta bien' @(
        'En el Monitor -> Lectores: IP 192.168.10.200, puerto 8193, Fanuc (FOCAS) -> Probar.',
        'Si da error, mandar a Claude el mensaje EXACTO.')
    } elseif ($ping -or $vecino) {
      Linea "4) Puerto FOCAS ${PUERTO}: cerrado" 'Red'
      Caso 'E' 'El torno esta en la red pero FOCAS no responde' @(
        'En el torno: SYSTEM -> [EMBED PORT] (EMBEDDED) -> [FOCAS2]:',
        '  TCP PORT NUMBER 8193 / UDP PORT NUMBER 0 / TIME INTERVAL 0',
        'Apagar y prender el torno. Volver a correr este diagnostico.')
    } else {
      Caso 'C' 'El torno no tiene IP en el puerto de red de atras' @(
        'En el torno (MDI): SYSTEM -> [EMBED PORT] -> [COMMON].',
        'Arriba TIENE que decir COMMON:SETTING [EMBEDDED] (si dice [PCMCIA]: tecla [EMBED] o [CHG DEV]).',
        'IP ADDRESS 192.168.10.200 / SUBNET MASK 255.255.255.0 / ROUTER IP ADDRESS 0.0.0.0',
        'Apagar con el interruptor general, esperar 10 s, prender.',
        'Si ya estaba asi: revisar conector (el de atras) o poner un switch en el medio.')
    }
  }
}
$archivo = Join-Path $PSScriptRoot 'diagnostico_torno.txt'
$salida | Set-Content -Path $archivo -Encoding UTF8
Linea ''; Linea "Resultado guardado en $archivo (podes mandarselo a Claude)." 'Cyan'
