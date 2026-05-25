param(
    [Parameter(Mandatory = $true)]
    [string]$Message,

    [string]$Title,

    [string[]]$Paths
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $Title) {
    $Title = $Message
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TitleText,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "== $TitleText =="
    $global:LASTEXITCODE = 0
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$TitleText failed with exit code $LASTEXITCODE"
    }
}

function Get-PullRequestUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Branch,

        [Parameter(Mandatory = $true)]
        [string]$PrTitle
    )

    $remote = git remote get-url origin
    if ($LASTEXITCODE -ne 0 -or -not $remote) {
        return $null
    }

    $ownerRepo = $null
    if ($remote -match "github\.com[:/](?<repo>[^/]+/[^/.]+)(\.git)?$") {
        $ownerRepo = $Matches["repo"]
    }

    if (-not $ownerRepo) {
        return $null
    }

    $encodedBranch = [System.Uri]::EscapeDataString($Branch)
    $encodedTitle = [System.Uri]::EscapeDataString($PrTitle)
    return "https://github.com/$ownerRepo/compare/main...$encodedBranch" + "?expand=1&title=$encodedTitle"
}

function Get-ClipboardText {
    try {
        return Get-Clipboard -Raw
    }
    catch {
        return (Get-Clipboard | Out-String).TrimEnd()
    }
}

function Open-PrBody {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    try {
        Start-Process notepad.exe -ArgumentList $Path
    }
    catch {
        Write-Host "Could not open pr_body.md in notepad: $_" -ForegroundColor Yellow
    }
}

function Copy-PrBodyToClipboard {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $bodyText = Get-Content -LiteralPath $Path -Raw
    $verified = $false

    try {
        if ((Get-Command Set-Clipboard -ErrorAction SilentlyContinue) -and (Get-Command Get-Clipboard -ErrorAction SilentlyContinue)) {
            $bodyText | Set-Clipboard
            $clipboardText = Get-ClipboardText
            if ($clipboardText -eq $bodyText) {
                $verified = $true
                Write-Host "Clipboard verified."
            }
        }
    }
    catch {
        $verified = $false
    }

    if (-not $verified) {
        Write-Host "Clipboard copy could not be verified. Opening pr_body.md." -ForegroundColor Yellow
        Open-PrBody -Path $Path
    }
}

Push-Location $repoRoot
try {
    $branch = git branch --show-current
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        Write-Host "ERROR: Could not determine current branch." -ForegroundColor Red
        exit 1
    }

    if ($branch -eq "main") {
        Write-Host "ERROR: Refusing to commit directly on main." -ForegroundColor Red
        exit 1
    }

    $preflightScript = Join-Path $PSScriptRoot "git_preflight.ps1"
    Invoke-Step "git_preflight.ps1" {
        & $preflightScript
    }

    $status = git status --short
    Write-Host ""
    Write-Host "== Pending changes =="
    if ($status) {
        $status | ForEach-Object { Write-Host $_ }
    }
    else {
        Write-Host "No pending changes."
    }

    Write-Host ""
    Write-Host "== Publish summary =="
    Write-Host "Branch: $branch"
    Write-Host "Commit message: $Message"
    Write-Host "PR title: $Title"
    if ($Paths) {
        Write-Host "git add target: specified paths"
        $Paths | ForEach-Object { Write-Host "  $_" }
    }
    else {
        Write-Host "git add target: all changes (-A)"
    }

    Write-Host ""
    $answer = Read-Host "Type YES to run git add, git commit, and git push"
    if ($answer -ne "YES") {
        Write-Host "Canceled."
        exit 1
    }

    if ($Paths) {
        Invoke-Step "git add specified paths" {
            git add -- $Paths
        }
    }
    else {
        Invoke-Step "git add -A" {
            git add -A
        }
    }

    Invoke-Step "git commit" {
        git commit -m $Message
    }

    Invoke-Step "git push" {
        git push -u origin $branch
    }

    $bodyPath = Join-Path $repoRoot "pr_body.md"
    $prBodyScript = Join-Path $PSScriptRoot "pr_body.ps1"
    Invoke-Step "create pr_body.md" {
        & $prBodyScript -OutputPath $bodyPath
    }

    Copy-PrBodyToClipboard -Path $bodyPath

    $url = Get-PullRequestUrl -Branch $branch -PrTitle $Title
    Write-Host ""
    if ($url) {
        Write-Host "PR creation URL:"
        Write-Host $url
        try {
            Start-Process $url
        }
        catch {
            Write-Host "Could not open PR creation URL in browser: $_" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "PR URLを推定できませんでした。GitHub上で手動作成してください" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "PR creation and merge were not automated."
}
finally {
    Pop-Location
}
