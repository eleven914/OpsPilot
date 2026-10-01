$ErrorActionPreference = "Stop"

$dockerAppData = "E:\DockerData\appdata"
$dockerLocalAppData = "E:\DockerData\localappdata"
$dockerExecutable = "E:\Apps\Docker\Docker Desktop.exe"

New-Item -ItemType Directory -Force -Path $dockerAppData, $dockerLocalAppData | Out-Null
$env:APPDATA = $dockerAppData
$env:LOCALAPPDATA = $dockerLocalAppData
Start-Process -FilePath $dockerExecutable -WindowStyle Hidden
