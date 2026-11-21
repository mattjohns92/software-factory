[CmdletBinding()]
param(
    [switch]$Launch,
    [string]$PythonPath = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [string]$CopilotPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ValidatorPath = (Resolve-Path (Join-Path $RepositoryRoot 'scripts\validate_specialist_profiles.py')).Path
$PolicyPath = Join-Path $env:TEMP ("factory-engineer-policy-$([guid]::NewGuid().ToString('N')).json")
$EnvironmentNames = @(
    'FACTORY_REPOSITORY_ROOT',
    'FACTORY_POLICY_PATH',
    'PYTHONPATH',
    'COPILOT_ALLOW_ALL',
    'COPILOT_ASSISTED_APPROVAL'
)
$PreviousEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $Value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    $PreviousEnvironment[$Name] = @{ IsSet = $null -ne $Value; Value = $Value }
}
$ExitCode = 0

try {
    $Policy = [ordered]@{
        schema_version = 1
        phase = 'planning'
        approved_plan_digest = $null
        repository_root = $RepositoryRoot
        allowed_agents = @('engineer')
        allowed_tools = @('task', 'read')
        read_only_paths = @($ValidatorPath)
        writable_paths = @()
        denied_paths = @()
        allowed_commands = @()
    }
    $PolicyJson = ConvertTo-Json -InputObject $Policy -Depth 5
    [IO.File]::WriteAllText($PolicyPath, $PolicyJson + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
    $env:FACTORY_REPOSITORY_ROOT = $RepositoryRoot
    $env:FACTORY_POLICY_PATH = [IO.Path]::GetFullPath($PolicyPath)
    $env:PYTHONPATH = Join-Path $RepositoryRoot 'src'
    $env:COPILOT_ALLOW_ALL = 'false'
    $env:COPILOT_ASSISTED_APPROVAL = 'false'

    $LoadedPolicy = Get-Content -LiteralPath $env:FACTORY_POLICY_PATH -Raw | ConvertFrom-Json
    if (-not [string]::Equals([IO.Path]::GetFullPath($LoadedPolicy.repository_root), $RepositoryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        @($LoadedPolicy.allowed_agents).Count -ne 1 -or $LoadedPolicy.allowed_agents[0] -cne 'engineer' -or
        @($LoadedPolicy.allowed_tools).Count -ne 2 -or $LoadedPolicy.allowed_tools -cnotcontains 'task' -or $LoadedPolicy.allowed_tools -cnotcontains 'read' -or
        @($LoadedPolicy.read_only_paths).Count -ne 1 -or -not [string]::Equals([IO.Path]::GetFullPath($LoadedPolicy.read_only_paths[0]), $ValidatorPath, [StringComparison]::OrdinalIgnoreCase) -or
        @($LoadedPolicy.writable_paths).Count -ne 0 -or @($LoadedPolicy.denied_paths).Count -ne 0 -or @($LoadedPolicy.allowed_commands).Count -ne 0 -or
        $LoadedPolicy.phase -cne 'planning' -or $null -ne $LoadedPolicy.approved_plan_digest -or [int]$LoadedPolicy.schema_version -ne 1) {
        throw 'Temporary policy does not match the approved Engineer-only schema.'
    }

    $ValidatorProgram = @'
import json
import os
from software_factory.policy import validate_policy

with open(os.environ["FACTORY_POLICY_PATH"], encoding="utf-8") as policy_file:
    policy = json.load(policy_file)
validate_policy(policy, expected_root=os.environ["FACTORY_REPOSITORY_ROOT"], allow_native_tools=True)
'@
    $ValidatorProgram | & $PythonPath -
    if ($LASTEXITCODE -ne 0) {
        throw "Repository policy validator failed with exit code $LASTEXITCODE."
    }

    $HookConfig = Get-Content -LiteralPath (Join-Path $RepositoryRoot '.github\hooks\factory-policy.json') -Raw | ConvertFrom-Json
    $HookEntry = $HookConfig.hooks.preToolUse[0]
    if ($HookEntry.cwd -cne '.' -or $HookEntry.powershell -notmatch 'factory_pre_tool_use\.ps1') {
        throw 'Configured PowerShell hook does not match the expected repository hook.'
    }
    $PowerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
    function Invoke-ConfiguredHook([hashtable]$Event) {
        $EventJson = ConvertTo-Json -InputObject $Event -Depth 8 -Compress
        $HookOutput = @($EventJson | & $PowerShellPath -NoProfile -Command $HookEntry.powershell)
        if ($LASTEXITCODE -ne 0) {
            throw "Configured PowerShell hook failed with exit code $LASTEXITCODE."
        }
        return (($HookOutput -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop).permissionDecision
    }

    $TaskArguments = @{
        agent_type = 'Engineer'
        description = 'Read-only validator inspection.'
        mode = 'sync'
        name = 'Validator inspection'
        prompt = 'Inspect and explain validation behavior.'
    }
    $EngineerObjectDecision = Invoke-ConfiguredHook @{ toolName = 'task'; toolArgs = $TaskArguments }
    $EngineerStringDecision = Invoke-ConfiguredHook @{ toolName = 'task'; toolArgs = (ConvertTo-Json -InputObject $TaskArguments -Compress) }
    $UnauthorizedDecision = Invoke-ConfiguredHook @{ toolName = 'task'; toolArgs = @{ agent_type = 'code-reviewer'; prompt = 'Not authorized.' } }
    $ReadDecision = Invoke-ConfiguredHook @{ toolName = 'view'; toolArgs = @{ filePath = $ValidatorPath } }
    $OutsideReadDecision = Invoke-ConfiguredHook @{ toolName = 'view'; toolArgs = @{ filePath = (Join-Path $RepositoryRoot '.gitignore') } }
    $WriteDecision = Invoke-ConfiguredHook @{ toolName = 'edit'; toolArgs = @{ filePath = $ValidatorPath } }
    $CommandDecision = Invoke-ConfiguredHook @{ toolName = 'powershell'; toolArgs = @{ command = 'Get-ChildItem'; cwd = $RepositoryRoot } }
    $MalformedDecision = Invoke-ConfiguredHook @{ toolName = 'task'; toolArgs = ($TaskArguments + @{ unexpected = 'not allowed' }) }
    if ($EngineerObjectDecision -cne 'ask' -or $EngineerStringDecision -cne 'ask' -or
        $UnauthorizedDecision -cne 'deny' -or $ReadDecision -cne 'allow' -or
        $OutsideReadDecision -cne 'deny' -or $WriteDecision -cne 'deny' -or
        $CommandDecision -cne 'deny' -or $MalformedDecision -cne 'deny') {
        throw 'Configured hook returned an unexpected decision for one or more synthetic cases.'
    }

    Write-Output 'POLICY_VALIDATOR=PASS'
    Write-Output 'HOOK_TASK_OBJECT=ask; HOOK_TASK_JSON_STRING=ask; UNAUTHORIZED_AGENT=deny; IN_SCOPE_VIEW=allow; OUT_OF_SCOPE_VIEW=deny; WRITE=deny; COMMAND=deny; UNKNOWN_TASK_FIELD=deny'
    Write-Output 'OFFLINE_PREFLIGHT=PASS'

    if ($Launch) {
        if ([string]::IsNullOrWhiteSpace($CopilotPath)) {
            $CopilotPath = (Get-Command copilot -ErrorAction Stop).Source
        }
        $IsWindowsPlatform = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
        if ($IsWindowsPlatform -and $PSVersionTable.PSVersion.Major -lt 6) {
            Set-Variable -Name IsWindows -Value $IsWindowsPlatform -Scope Local
        }
        & $CopilotPath --agent 'Factory Lead' --no-auto-update --no-color --available-tools task view
        if ($LASTEXITCODE -ne 0) {
            throw "Copilot CLI exited with code $LASTEXITCODE."
        }
    }
} catch {
    [Console]::Error.WriteLine("Engineer delegation preflight failed: $($_.Exception.Message)")
    $ExitCode = 1
} finally {
    Remove-Item -LiteralPath $PolicyPath -Force -ErrorAction SilentlyContinue
    foreach ($Name in $EnvironmentNames) {
        $Previous = $PreviousEnvironment[$Name]
        if ($Previous.IsSet) {
            [Environment]::SetEnvironmentVariable($Name, $Previous.Value, 'Process')
        } else {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        }
    }
}

exit $ExitCode