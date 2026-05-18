# Local autonomous refresh (fallback to the GitHub Actions cron).
# Run by Windows Task Scheduler if you'd rather not use GitHub Actions.
# Scrape -> validate -> rebuild -> commit & push (host auto-deploys on push).
# Validation failure aborts WITHOUT publishing, so bad data never goes live.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "[refresh] scraping public OZEV data..."
python pipeline/extract.py
if ($LASTEXITCODE -ne 0) { Write-Host "[refresh] extract failed"; exit 1 }

Write-Host "[refresh] validating..."
python pipeline/validate.py
if ($LASTEXITCODE -ne 0) { Write-Host "[refresh] validation FAILED - not publishing"; exit 1 }

Write-Host "[refresh] rebuilding site..."
python site/generate.py
if ($LASTEXITCODE -ne 0) { Write-Host "[refresh] generate failed"; exit 1 }

Write-Host "[refresh] committing..."
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "Auto-refresh: $(Get-Date -Format yyyy-MM-dd)"
    git push
    Write-Host "[refresh] pushed - host will auto-deploy"
} else {
    Write-Host "[refresh] no changes this run"
}
