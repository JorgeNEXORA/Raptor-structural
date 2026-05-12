# Script PowerShell — corre no teu PC Windows
# Faz upload do projeto para o servidor Hetzner e instala tudo
#
# USO:
#   .\deploy\upload_and_deploy.ps1 -ServerIP "1.2.3.4" -SSHKey "C:\Users\Utilizador\.ssh\id_rsa"

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP,

    [Parameter(Mandatory=$false)]
    [string]$SSHKey = "$env:USERPROFILE\.ssh\id_rsa"
)

$PROJECT_DIR = Split-Path -Parent $PSScriptRoot
$REMOTE_TMP  = "/tmp/structural_ai_upload"

Write-Host "=== [1/3] Upload do projeto ===" -ForegroundColor Cyan
# Exclui __pycache__, outputs gerados e .git
& scp -i $SSHKey -r `
    -o StrictHostKeyChecking=no `
    "$PROJECT_DIR" `
    "root@${ServerIP}:${REMOTE_TMP}"

Write-Host "=== [2/3] Copiar para /opt e correr setup ===" -ForegroundColor Cyan
& ssh -i $SSHKey -o StrictHostKeyChecking=no "root@$ServerIP" @"
cp -r $REMOTE_TMP /opt/structural_ai
cd /opt/structural_ai
bash deploy/setup_server.sh
"@

Write-Host ""
Write-Host "=== [3/3] Concluído ===" -ForegroundColor Green
Write-Host "Acede em: http://$ServerIP" -ForegroundColor Yellow
