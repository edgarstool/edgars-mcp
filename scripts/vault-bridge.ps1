<#>
.SYNOPSIS
    WB-11 Vault A Windows Bridge — Canonical write path for Vault A mutations
    Applies mutation intents to canonical local Vault A before mirror/QMD sync.

.DESCRIPTION
    This is the ONLY canonical write path for Vault A. VPS mirror and QMD sync
    must pull from this canonical local Vault A — never write directly to mirrors.

    Features:
    - Reads intent files from .vault-intents/ directory
    - Validates expected_sha256 conflict semantics at apply time
    - Applies create/update intents atomically
    - Logs all operations to vault-bridge.log (JSONL)
    - Removes intent files on success
    - Dry-run mode for validation
    - Supports selective intent application

.PARAMETER VaultRoot
    Path to canonical Vault A root (default: G:\Obsidian\Edgar'sObsidianVault)

.PARAMETER DryRun
    Validate and preview without applying changes

.PARAMETER IntentIds
    Comma-separated list of specific intent IDs to apply (default: all pending)

.EXAMPLE
    # Apply all pending intents
    .\vault-bridge.ps1

.EXAMPLE
    # Dry run to preview
    .\vault-bridge.ps1 -DryRun

.EXAMPLE
    # Apply specific intents
    .\vault-bridge.ps1 -IntentIds "intent-a1b2c3d4,intent-e5f6g7h8"

.EXAMPLE
    # Verbose output (built-in -Verbose from CmdletBinding)
    .\vault-bridge.ps1 -Verbose

.NOTES
    Author: Edgar (WB-11 Vault A Full Cut)
    Version: 2.0.0-wb11
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$VaultRoot = "G:\Obsidian\Edgar'sObsidianVault",

    [Parameter(Mandatory=$false)]
    [switch]$DryRun,

    [Parameter(Mandatory=$false)]
    [string]$IntentIds = ""
)

# ── Strict mode ──────────────────────────────────────────────────────────────
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Constants ────────────────────────────────────────────────────────────────
$INTENTS_DIR_NAME = ".vault-intents"
$MANIFEST_ID_FILE = ".vault-manifest-id"
$BRIDGE_LOG_FILE = "vault-bridge.log"
$VALID_EXT = ".md"

$CONTROL_DIRS = @(
    ".obsidian", ".trash", ".git", ".vault-intents",
    ".vault-manifest-id", "node_modules", "__pycache__", ".venv"
)

$HIDDEN_PREFIX = "."

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"
    Write-Host $line
    # Also append to bridge log file
    $logEntry = @{
        timestamp = (Get-Date).ToString("o")
        level = $Level
        message = $Message
    } | ConvertTo-Json -Compress
    Add-Content -Path (Join-Path $script:VaultRoot $BRIDGE_LOG_FILE) -Value $logEntry -Encoding UTF8
}

function Write-VerboseLog {
    param([string]$Message)
    if ($PSBoundParameters.ContainsKey('Verbose') -or $VerbosePreference -ne 'SilentlyContinue') {
        Write-Log $Message "VERBOSE"
    }
}

function Test-IsControlOrHidden {
    param([string]$RelativePath)
    $parts = $RelativePath -split '[\\/]'
    foreach ($part in $parts) {
        if ($part.StartsWith($HIDDEN_PREFIX) -or $CONTROL_DIRS -contains $part) {
            return $true
        }
    }
    return $false
}

function Get-SHA256 {
    param([string]$FilePath)
    $hash = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($FilePath)
    $bytes = $hash.ComputeHash($stream)
    $stream.Close()
    ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Get-SHA256String {
    param([string]$Content)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Content)
    $hash = [System.Security.Cryptography.SHA256]::Create()
    $hashBytes = $hash.ComputeHash($bytes)
    ($hashBytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Resolve-VaultPath {
    param([string]$RelativePath, [string]$Action = "read")

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        throw "Path must be a non-empty string"
    }

    $rel = $RelativePath.TrimStart('/','\')
    if ([System.IO.Path]::IsPathRooted($rel)) {
        throw "Absolute paths not allowed: $rel"
    }
    if ($rel -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "Path traversal not allowed: $rel"
    }
    if (-not $rel.EndsWith($VALID_EXT, [StringComparison]::OrdinalIgnoreCase)) {
        $rel += $VALID_EXT
    }

    $vaultRoot = $script:VaultRoot
    $fullPath = Join-Path $vaultRoot $rel

    # For create: path doesn't exist yet, just validate it's within vault
    if ($Action -eq 'create') {
        $fullPathResolved = Resolve-Path $fullPath -ErrorAction SilentlyContinue
        if ($fullPathResolved) {
            if (-not $fullPathResolved.Path.StartsWith($vaultRoot)) {
                throw "Path outside vault: $rel"
            }
        } else {
            # Path doesn't exist, verify parent is within vault
            $parentDir = Split-Path $fullPath -Parent
            $parentResolved = Resolve-Path $parentDir -ErrorAction SilentlyContinue
            if ($parentResolved -and -not $parentResolved.Path.StartsWith($vaultRoot)) {
                throw "Path outside vault: $rel"
            }
        }
    } else {
        # For read/update: path must exist
        $resolved = Resolve-Path $fullPath -ErrorAction Stop
        if (-not $resolved.Path.StartsWith($vaultRoot)) {
            throw "Path outside vault: $rel"
        }
        $fullPath = $resolved.Path
    }

    $relPath = $fullPath.Substring($vaultRoot.Length + 1)
    if (Test-IsControlOrHidden $relPath) {
        throw "Access to control/hidden directory not allowed: $rel"
    }
    if (-not $fullPath.EndsWith($VALID_EXT, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Only .md files allowed: $rel"
    }

    return $fullPath
}

function Get-SafeRelPath {
    param([string]$FullPath)
    $vaultRoot = $script:VaultRoot
    $rel = $FullPath.Substring($vaultRoot.Length + 1)
    return [System.IO.Path]::ChangeExtension($rel, $null)
}

# ── Main ──────────────────────────────────────────────────────────────────────

$script:VaultRoot = Resolve-Path $VaultRoot -ErrorAction Stop | Select-Object -ExpandProperty Path
$intentsDir = Join-Path $script:VaultRoot $INTENTS_DIR_NAME
$bridgeLog = Join-Path $script:VaultRoot $BRIDGE_LOG_FILE

Write-Log "=== Vault A Bridge Started ===" "INFO"
Write-Log "Vault Root: $script:VaultRoot" "INFO"
Write-Log "Intents Dir: $intentsDir" "INFO"
Write-Log "Dry Run: $DryRun" "INFO"

if (-not (Test-Path $intentsDir)) {
    Write-Log "Intents directory does not exist: $intentsDir" "WARN"
    Write-Log "=== Vault A Bridge Complete: 0 applied ===" "INFO"
    exit 0
}

# Collect intent files
$intentFiles = @(Get-ChildItem -Path $intentsDir -Filter "*.json" -File | Sort-Object Name)

if ($IntentIds) {
    $selectedIds = $IntentIds -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $intentFiles = @($intentFiles | Where-Object { $selectedIds -contains $_.BaseName })
}

if (-not $intentFiles -or $intentFiles.Count -eq 0) {
    Write-Log "No matching intent files found" "INFO"
    Write-Log "=== Vault A Bridge Complete: 0 applied ===" "INFO"
    exit 0
}

$applied = 0
$failed = 0
$skipped = 0
$results = @()

foreach ($intentFile in $intentFiles) {
    $intentId = $intentFile.BaseName
    Write-VerboseLog "Processing intent: $intentId"

    try {
        $intentJson = Get-Content $intentFile.FullName -Raw -Encoding UTF8
        $intent = $intentJson | ConvertFrom-Json

        # Validate intent structure
        if (-not $intent.intent_id -or -not $intent.action -or -not $intent.path -or -not $intent.content) {
            throw "Invalid intent structure: missing required fields"
        }
        if ($intent.action -notin @('create','update')) {
            throw "Invalid action: $($intent.action) (must be create or update)"
        }

        $targetPath = Resolve-VaultPath $intent.path $intent.action
        $relPath = Get-SafeRelPath $targetPath

        # Re-validate for update
        $oldSha256 = $null
        if ($intent.action -eq 'update') {
            if (-not (Test-Path $targetPath)) {
                throw "Note no longer exists: $relPath"
            }
            if ($intent.expected_sha256) {
                $currentSha256 = Get-SHA256 $targetPath
                if ($currentSha256 -ne $intent.expected_sha256) {
                    throw "Conflict: current SHA256 ($($currentSha256.Substring(0,16))...) != expected ($($intent.expected_sha256.Substring(0,16))...)"
                }
            }
            $oldSha256 = Get-SHA256 $targetPath
        } else {
            if (Test-Path $targetPath) {
                throw "Cannot create: note already exists: $relPath"
            }
        }

        $newSha256 = Get-SHA256String $intent.content

        if ($DryRun) {
            $result = @{
                intent_id = $intentId
                success = $true
                path = $relPath
                action = $intent.action
                old_sha256 = $oldSha256
                new_sha256 = $newSha256
                message = "[DRY RUN] Would $($intent.action): $relPath"
            }
            $results += $result
            $skipped++
            Write-Log "[DRY RUN] $($intent.action) $relPath" "INFO"
            continue
        }

        # Apply the intent
        $targetDir = Split-Path $targetPath -Parent
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }
        # Use UTF8NoBOM to avoid BOM bytes affecting SHA256
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($intent.content)
        [System.IO.File]::WriteAllBytes($targetPath, $bytes)

        # Verify write
        $verifySha256 = Get-SHA256 $targetPath
        if ($verifySha256 -ne $newSha256) {
            throw "Write verification failed: SHA256 mismatch after write"
        }

        # Remove intent file
        Remove-Item $intentFile.FullName -Force -ErrorAction SilentlyContinue

        # Log to bridge log (JSONL)
        $logEntry = @{
            timestamp = (Get-Date).ToString("o")
            intent_id = $intentId
            action = $intent.action
            path = $relPath
            old_sha256 = $oldSha256
            new_sha256 = $newSha256
        } | ConvertTo-Json -Compress
        Add-Content -Path $bridgeLog -Value $logEntry -Encoding UTF8

        $result = @{
            intent_id = $intentId
            success = $true
            path = $relPath
            action = $intent.action
            old_sha256 = $oldSha256
            new_sha256 = $newSha256
            message = "$($intent.action) $relPath"
        }
        $results += $result
        $applied++
        Write-Log "Applied: $($intent.action) $relPath" "INFO"

    } catch {
        $errMsg = $_.Exception.Message
        $result = @{
            intent_id = $intentId
            success = $false
            message = $errMsg
        }
        $results += $result
        $failed++
        Write-Log "FAILED $($intentId): $errMsg" "ERROR"
    }
}

# Summary
$summary = @{
    applied = $applied
    failed = $failed
    skipped = $skipped
    total = $intentFiles.Count
    dry_run = $DryRun
    results = $results
    timestamp = (Get-Date).ToString("o")
} | ConvertTo-Json -Depth 10 -Compress

Write-Log "=== Vault A Bridge Complete ===" "INFO"
Write-Log "Applied: $applied, Failed: $failed, Skipped: $skipped" "INFO"
Write-Log "Summary: $summary" "INFO"

# Output JSON summary to stdout for programmatic consumption
$summary | Write-Host

exit $failed