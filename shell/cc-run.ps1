# cc-quota-guard: makes `cc-run` callable from PowerShell.
#
# Why this is needed: a plugin's bin/ directory is only added to PATH for
# Claude Code's OWN internal Bash tool calls — not for your regular
# terminal. And cc-run is a bash script, so PowerShell can't run it
# directly anyway. This function shells out to Git Bash and resolves the
# plugin's current install path each time, so it keeps working across
# plugin updates (the cache path changes on every version bump).
#
# Setup (one time): append this file's content to your PowerShell profile,
# then restart your terminal (or dot-source it in the current session):
#
#   Get-Content shell\cc-run.ps1 | Add-Content $PROFILE
#   . $PROFILE
#
# Requires: Git for Windows (for Git Bash) installed at the default path.
# If yours is elsewhere, edit $gitBash below.

function cc-run {
    $gitBash = "C:\Program Files\Git\bin\bash.exe"
    if (-not (Test-Path $gitBash)) {
        Write-Error "Git Bash not found at $gitBash. Install Git for Windows, or edit `$gitBash in this function."
        return
    }
    $info = claude plugin list --json | ConvertFrom-Json | Where-Object { $_.id -eq "cc-quota-guard@cc-quota-guard" }
    if (-not $info) {
        Write-Error "cc-quota-guard plugin not found. Run: claude plugin list"
        return
    }
    $script = Join-Path $info.installPath "bin\cc-run"
    & $gitBash $script @args
}
