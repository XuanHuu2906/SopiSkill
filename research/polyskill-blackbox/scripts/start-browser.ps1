# Starts an ISOLATED Chrome profile for the PolySkill black-box session.
# Run this yourself, in PowerShell, from the repo root:
#     powershell -ExecutionPolicy Bypass -File research/polyskill-blackbox/scripts/start-browser.ps1
#
# What it does:
#   - uses a separate user-data-dir (required: Chrome 136+ ignores the debug port on the default profile)
#   - binds the DevTools port to loopback only
#   - opens https://web.polyskill.app
#
# It does NOT log you in, does NOT type anything, and does NOT touch PolySkill data.
# You log in manually; credentials must never be pasted into an agent session.

$ErrorActionPreference = 'Stop'

$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path $chrome)) {
    $chrome = 'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
}
if (-not (Test-Path $chrome)) {
    throw 'Chrome not found. Set $chrome to the correct chrome.exe path before running.'
}

$profile = Join-Path $env:LOCALAPPDATA 'REA-PolySkill-Profile'
Write-Host "chrome : $chrome"
Write-Host "profile: $profile"
Write-Host "cdp    : http://127.0.0.1:9222 (loopback only)"
Write-Host ''
Write-Host 'After the window opens: log in manually, open the course you want to test,'
Write-Host 'then tell the agent that the session is ready.'
Write-Host ''

Start-Process -FilePath $chrome -ArgumentList @(
    '--remote-debugging-port=9222',
    '--remote-debugging-address=127.0.0.1',
    ('--user-data-dir="' + $profile + '"'),
    '--no-first-run',
    '--no-default-browser-check',
    'https://web.polyskill.app'
)

Start-Sleep -Seconds 3
try {
    $v = Invoke-RestMethod 'http://127.0.0.1:9222/json/version' -TimeoutSec 5
    Write-Host "CDP OK. Browser: $($v.Browser)"
} catch {
    Write-Host 'CDP not reachable yet. Wait a moment and check:'
    Write-Host '  Invoke-RestMethod http://127.0.0.1:9222/json/version | Select-Object Browser'
}
