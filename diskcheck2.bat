@echo off
setlocal
set OUT=C:\Dev\pca-multiexercicio-backend\diskcheck_result.txt
echo Aguarde... analisando C:\ > "%OUT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$out='%OUT%'; ^
   $drive = Get-PSDrive C; ^
   $linha = 'C: Livre: ' + [math]::Round($drive.Free/1GB,1) + ' GB   Usado: ' + [math]::Round($drive.Used/1GB,1) + ' GB'; ^
   $linha | Out-File $out -Encoding UTF8; ^
   '' | Add-Content $out; ^
   'TOP PASTAS EM C:\:' | Add-Content $out; ^
   Get-ChildItem C:\ -Directory -ErrorAction SilentlyContinue | ForEach-Object { ^
     $name = $_.Name; ^
     $bytes = 0; ^
     try { ^
       $bytes = ([System.IO.DirectoryInfo]$_.FullName).EnumerateFiles('*',[System.IO.SearchOption]::AllDirectories) | ^
                Measure-Object -Property Length -Sum | Select-Object -ExpandProperty Sum; ^
       if (-not $bytes) { $bytes = 0 } ^
     } catch {}; ^
     $gb = [math]::Round($bytes/1GB,2); ^
     ($gb.ToString('F2') + ' GB   ' + $name) | Add-Content $out ^
   }; ^
   '' | Add-Content $out; ^
   'Concluido.' | Add-Content $out"
echo Resultado salvo em %OUT%
