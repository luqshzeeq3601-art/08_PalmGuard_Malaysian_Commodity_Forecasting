# scripts/deploy_cloud_run.ps1
# Optional deployment script for Google Cloud Run (Portfolio Checklist)
# Marked UNVERIFIED: Requires GCP account and active billing project.

param (
    [string]$ProjectId = "palmguard-project",
    [string]$Region = "asia-southeast1",
    [string]$ServiceName = "palmguard-api"
)

Write-Host "=== PalmGuard Cloud Run Deployment (UNVERIFIED) ==="
Write-Host "[*] Project: $ProjectId"
Write-Host "[*] Region: $Region"
Write-Host "[*] Service: $ServiceName"

Write-Host "[*] Building container image via Google Cloud Build..."
# gcloud builds submit --tag gcr.io/$ProjectId/$ServiceName:latest .

Write-Host "[*] Deploying image to Cloud Run..."
# gcloud run deploy $ServiceName `
#     --image gcr.io/$ProjectId/$ServiceName:latest `
#     --platform managed `
#     --region $Region `
#     --allow-unauthenticated `
#     --memory 1Gi `
#     --cpu 1 `
#     --port 8000

Write-Host "[!] Note: Script is unverified until a billing-enabled GCP project is connected."
