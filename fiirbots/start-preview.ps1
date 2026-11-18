$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:FIIRBOTS_GPIO_ENABLED = '0'
$env:FIIRBOTS_REBOOT_ENABLED = '0'
# Empty process values are removed by older PowerShell versions. Set them in Python.
$env:FIIRBOTS_DB = 'data/dashboard-preview.db'
python -c "import os; os.environ['FIIRBOTS_SERIAL_PORT']=''; os.environ['FIIRBOTS_SCAN_NETWORK']=''; import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, access_log=False)"
