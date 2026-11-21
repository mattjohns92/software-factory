$ErrorActionPreference = 'Stop'

function Get-PropertyValue {
    param(
        [object]$Object,
        [string[]]$Names
    )

    foreach ($Name in $Names) {
        $Property = $Object.PSObject.Properties[$Name]
        if ($null -ne $Property) {
            return $Property.Value
        }
    }
    return $null
}

function Write-Deny {
    param([string]$Reason)
    @{ permissionDecision = 'deny'; permissionDecisionReason = $Reason } |
        ConvertTo-Json -Compress
    exit 0
}

function Get-CanonicalPath {
    param(
        [string]$Value,
        [string]$RepositoryRoot
    )

    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '[\x00]' -or
        $Value -match '(^|[\\/])\.\.([\\/]|$)' -or
        $Value.StartsWith('\\') -or $Value.StartsWith('//')) {
        throw 'Path is malformed, traverses, or uses a UNC/device location.'
    }
    if ([IO.Path]::IsPathRooted($Value)) {
        return [IO.Path]::GetFullPath($Value)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $Value))
}

function Test-WithinPath {
    param(
        [string]$Path,
        [string]$Root
    )

    $CanonicalRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $CanonicalPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    return [string]::Equals($CanonicalPath, $CanonicalRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $CanonicalPath.StartsWith($CanonicalRoot + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Get-ArgumentTargets {
    param([object]$Arguments)

    $Targets = [System.Collections.Generic.List[string]]::new()
    foreach ($Name in @('path', 'filePath', 'file_path', 'target', 'directory')) {
        $Value = Get-PropertyValue -Object $Arguments -Names @($Name)
        if ($Value -is [string]) {
            $Targets.Add($Value)
        } elseif ($Value -is [array]) {
            foreach ($Item in $Value) {
                if ($Item -is [string]) { $Targets.Add($Item) }
            }
        }
    }

    $Patch = Get-PropertyValue -Object $Arguments -Names @('patch')
    if ($Patch -is [string]) {
        foreach ($Match in [regex]::Matches($Patch, '(?m)^\*\*\* (?:Update|Add|Delete) File: (.+)$')) {
            $Targets.Add($Match.Groups[1].Value.Trim())
        }
    }

    return $Targets.ToArray()
}

try {
    if ([string]::IsNullOrWhiteSpace($env:FACTORY_POLICY_PATH) -or
        -not (Test-Path -LiteralPath $env:FACTORY_POLICY_PATH -PathType Leaf)) {
        Write-Deny 'Factory policy is unavailable.'
    }
    if ([string]::IsNullOrWhiteSpace($env:FACTORY_REPOSITORY_ROOT)) {
        Write-Deny 'Factory repository root is unavailable.'
    }

    $Event = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $Policy = Get-Content -LiteralPath $env:FACTORY_POLICY_PATH -Raw | ConvertFrom-Json
    if ($Policy.schema_version -ne 1 -or $Policy.phase -notin @('planning', 'implementation')) {
        Write-Deny 'Factory policy schema or phase is invalid.'
    }
    $KnownTools = @('view', 'read', 'glob', 'grep', 'create', 'edit', 'apply_patch', 'powershell', 'list_agents', 'task')
    if ($Policy.allowed_tools -isnot [array] -or
        @($Policy.allowed_tools | Where-Object { $_ -notin $KnownTools }).Count -gt 0 -or
        @($Policy.allowed_tools | Select-Object -Unique).Count -ne $Policy.allowed_tools.Count) {
        Write-Deny 'Factory policy contains unknown or duplicate tools.'
    }
    $KnownAgents = @('engineer', 'code-reviewer', 'code-review')
    if ($Policy.allowed_agents -isnot [array] -or
        @($Policy.allowed_agents | Where-Object { $_ -notin $KnownAgents }).Count -gt 0 -or
        @($Policy.allowed_agents | Select-Object -Unique).Count -ne $Policy.allowed_agents.Count) {
        Write-Deny 'Factory policy contains unknown or duplicate agents.'
    }
    $Tool = Get-PropertyValue -Object $Event -Names @('toolName', 'tool_name')
    $Arguments = Get-PropertyValue -Object $Event -Names @('toolArgs', 'tool_input', 'arguments')
    if ($Arguments -is [string]) {
        $Arguments = $Arguments | ConvertFrom-Json
    }
    $PolicyTool = if ($Tool -eq 'view') { 'read' } else { $Tool }
    if ([string]::IsNullOrWhiteSpace($Tool) -or $null -eq $Arguments -or
        $PolicyTool -notin $Policy.allowed_tools) {
        Write-Deny 'Tool request is malformed or not allowlisted.'
    }

    $AgentContextNames = @('agentId', 'agent_id', 'agentType', 'agent_type')
    $HasAgentContext = @($Event.PSObject.Properties.Name | Where-Object { $_ -in $AgentContextNames }).Count -gt 0
    if ($HasAgentContext) {
        $AgentId = Get-PropertyValue -Object $Event -Names @('agentId', 'agent_id')
        $AgentType = Get-PropertyValue -Object $Event -Names @('agentType', 'agent_type')
        if ([string]::IsNullOrWhiteSpace($AgentId) -or
            [string]::IsNullOrWhiteSpace($AgentType) -or
            $AgentType -notin $Policy.allowed_agents) {
            Write-Deny 'Subagent identity or type is not allowlisted.'
        }
        if ($Tool -notin @('view', 'read', 'glob', 'grep')) {
            Write-Deny 'Subagents are limited to read-only tools.'
        }
    }

    if ($Tool -eq 'powershell') {
        $Command = Get-PropertyValue -Object $Arguments -Names @('command', 'script')
        $WorkingDirectory = Get-PropertyValue -Object $Arguments -Names @('working_directory', 'workingDirectory', 'cwd')
        $CommandAllowed = $false
        foreach ($Allowed in $Policy.allowed_commands) {
            $AllowedDirectory = Get-CanonicalPath -Value $Allowed.working_directory -RepositoryRoot $env:FACTORY_REPOSITORY_ROOT
            $RequestedDirectory = Get-CanonicalPath -Value $WorkingDirectory -RepositoryRoot $env:FACTORY_REPOSITORY_ROOT
            if ($Command -ceq $Allowed.command -and
                [string]::Equals($RequestedDirectory, $AllowedDirectory, [StringComparison]::OrdinalIgnoreCase)) {
                $CommandAllowed = $true
            }
        }
        if (-not $CommandAllowed) {
            Write-Deny 'PowerShell command or working directory is not allowlisted.'
        }
        @{ permissionDecision = 'allow' } | ConvertTo-Json -Compress
        exit 0
    }

    if ($Tool -eq 'list_agents') {
        @{ permissionDecision = 'allow' } | ConvertTo-Json -Compress
        exit 0
    }
    if ($Tool -eq 'task') {
        $TaskKeys = @($Arguments.PSObject.Properties.Name)
        $AgentTypeKeys = @($TaskKeys | Where-Object { $_ -in @('agent_type', 'agentType') })
        $UnknownTaskKeys = @($TaskKeys | Where-Object { $_ -notin @('agent_type', 'agentType', 'prompt', 'description', 'mode', 'name') })
        $TaskAgentType = Get-PropertyValue -Object $Arguments -Names @('agent_type', 'agentType')
        $Prompt = Get-PropertyValue -Object $Arguments -Names @('prompt')
        $DescriptionProperty = $Arguments.PSObject.Properties['description']
        $ModeProperty = $Arguments.PSObject.Properties['mode']
        $NameProperty = $Arguments.PSObject.Properties['name']
        if ($UnknownTaskKeys.Count -gt 0 -or $AgentTypeKeys.Count -ne 1) {
            Write-Deny 'Task payload is malformed.'
        }
        if ([string]::IsNullOrWhiteSpace($TaskAgentType) -or
            [string]::IsNullOrWhiteSpace($Prompt) -or
            ($null -ne $DescriptionProperty -and
                ($DescriptionProperty.Value -isnot [string] -or
                    [string]::IsNullOrWhiteSpace($DescriptionProperty.Value))) -or
            ($null -ne $ModeProperty -and
                ($ModeProperty.Value -isnot [string] -or $ModeProperty.Value -cne 'sync')) -or
            ($null -ne $NameProperty -and
                ($NameProperty.Value -isnot [string] -or
                    [string]::IsNullOrWhiteSpace($NameProperty.Value)))) {
            Write-Deny 'Task payload requires an agent type and non-empty prompt.'
        }
        if ($TaskAgentType -notin $Policy.allowed_agents) {
            Write-Deny 'Task agent type is not allowlisted.'
        }
        @{ permissionDecision = 'ask' } | ConvertTo-Json -Compress
        exit 0
    }

    $Targets = @(Get-ArgumentTargets -Arguments $Arguments)
    if ($Tool -eq 'glob' -and $Targets.Count -eq 0) {
        $Pattern = Get-PropertyValue -Object $Arguments -Names @('pattern')
        if ($Pattern -is [string]) {
            $Targets = @(($Pattern -split '[*?\[]', 2)[0].TrimEnd('\', '/'))
            if ([string]::IsNullOrWhiteSpace($Targets[0])) { $Targets = @('.') }
        }
    }
    if ($Targets.Count -eq 0) {
        Write-Deny 'Tool request does not identify a target path.'
    }

    foreach ($Target in $Targets) {
        $Path = Get-CanonicalPath -Value $Target -RepositoryRoot $env:FACTORY_REPOSITORY_ROOT
        $Denied = $false
        foreach ($BlockedPath in $Policy.denied_paths) {
            $Blocked = Get-CanonicalPath -Value $BlockedPath -RepositoryRoot $env:FACTORY_REPOSITORY_ROOT
            if ((Test-WithinPath -Path $Path -Root $Blocked) -or
                (Test-WithinPath -Path $Blocked -Root $Path)) {
                $Denied = $true
            }
        }
        if ($Denied) { Write-Deny 'Target path is denied.' }

        $Scopes = @($Policy.writable_paths)
        if ($Tool -notin @('create', 'edit', 'apply_patch')) {
            $Scopes += @($Policy.read_only_paths)
        }
        $AllowedPath = $false
        foreach ($ScopePath in $Scopes) {
            $Scope = Get-CanonicalPath -Value $ScopePath -RepositoryRoot $env:FACTORY_REPOSITORY_ROOT
            if (Test-WithinPath -Path $Path -Root $Scope) { $AllowedPath = $true }
        }
        if (-not $AllowedPath) { Write-Deny 'Target path is outside the allowed paths.' }
    }

    @{ permissionDecision = 'allow' } | ConvertTo-Json -Compress
    exit 0
} catch {
    Write-Deny 'Factory policy rejected a malformed or unresolvable request.'
}