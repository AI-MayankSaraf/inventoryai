# Starts a local S3 stand-in (moto) on port 5555 and creates the bucket.
# Run from the backend folder:  .\start-storage.ps1
# Leave this window open while the API is running. Data is in memory only.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe -m pip install -q "moto[server]"

$listening = Get-NetTCPConnection -LocalPort 5555 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Start-Process -WindowStyle Minimized -FilePath ".\.venv\Scripts\moto_server.exe" -ArgumentList "-H","127.0.0.1","-p","5555"
    Start-Sleep -Seconds 4
}

@'
import boto3
s = boto3.client("s3", endpoint_url="http://127.0.0.1:5555", aws_access_key_id="test",
                 aws_secret_access_key="test", region_name="us-east-1")
b = "inventoryai-documents"
try:
    s.head_bucket(Bucket=b)
except Exception:
    s.create_bucket(Bucket=b)
s.put_public_access_block(Bucket=b, PublicAccessBlockConfiguration=dict(
    BlockPublicAcls=True, IgnorePublicAcls=True, BlockPublicPolicy=True, RestrictPublicBuckets=True))
print("S3 stand-in ready: bucket", b)
'@ | & .\.venv\Scripts\python.exe -

& .\.venv\Scripts\python.exe -m scripts.verify_s3 2>&1 | Select-Object -Last 4
Write-Host "`nNow start the API:  uvicorn app.main:app --reload"
