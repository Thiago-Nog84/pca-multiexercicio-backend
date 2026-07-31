# =====================================================================
# Sincronização automática PCA MPPI — SIAFE (empenho/liquidação/pagamento)
# + PNCP (instrumentos e aditivos). Idempotente; seguro para rodar diário.
# Registrado no Agendador de Tarefas do Windows (ver README abaixo).
# =====================================================================
$ErrorActionPreference = 'Continue'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$repo = 'C:\Dev\pca-multiexercicio-backend'
Set-Location $repo
$ano = (Get-Date).Year

$logDir = Join-Path $repo 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("sync_" + (Get-Date -Format 'yyyy-MM-dd') + ".log")

function Etapa($desc, $cmdArgs) {
    ("`n---- {0}  ({1}) ----" -f $desc, (Get-Date -Format 'HH:mm:ss')) | Out-File -Append -Encoding utf8 $log
    & python manage.py @cmdArgs *>> $log
}

("==================================================") | Out-File -Append -Encoding utf8 $log
("Sincronização iniciada em {0}" -f (Get-Date)) | Out-File -Append -Encoding utf8 $log

Etapa "Empenhos SIAFE ($ano)"          @('importar_empenhos_siafe', '--exercicio', "$ano")
Etapa "Liquidações SIAFE"              @('importar_liquidacoes_siafe')
Etapa "Pagamentos SIAFE (OB)"          @('importar_pagamentos_siafe')
Etapa "Instrumentos e aditivos (PNCP)" @('sincronizar_instrumentos_pncp')

("`nSincronização concluída em {0}" -f (Get-Date)) | Out-File -Append -Encoding utf8 $log
