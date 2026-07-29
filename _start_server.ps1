$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'C:\Dev\pca-multiexercicio-backend'
.venv\Scripts\python.exe manage.py runserver 2>&1
