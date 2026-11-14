[CmdletBinding()]
param(
    [switch]$RunNative,
    [ValidateSet('Both','On','Off')][string]$Commands = 'Both',
    [ValidateSet(4608,6144)][int]$HeapMiB = 6144
)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path "$PSScriptRoot/../../../..").Path
$run = "$project/artifacts/agent-runs/antimatter-reforged-local-guest"
if ($Commands -ne 'Both') { $run += '-' + $Commands.ToLowerInvariant() }
$sharedQa = "$project/artifacts/agent-runs/guest-peer-remaining-20261114"
$cache = "$project/Minecraft/Launcher"
$shared = "$cache/Shared"
$published = "$project/artifacts/agent-runs/antimatter-reforged-203/catalog-probe/pack-manifest.json"
$assembly = "$cache/Runtime/e86ff2d180aeab13cf0d77bf6f0d1b1fceaae5ec8ae8d8969cb68bb9ecf49cab"
$profile = '1.20.1-forge-47.4.10'
$java = "$cache/JavaRuntimes/runtime/windows-x64/java-17/bin/java.exe"
$jdk = 'C:/Tools/jdk-25.0.2/bin'
$state = "$cache/IdentityAdapters/9429948eefa919ab114b3d24ed733fa4e315def552876d4001e4163db95e13c1/adapter-state.json"
$mapping = "$shared/libraries/de/oceanlabs/mcp/mcp_config/1.20.1-20230612.114412/mcp_config-1.20.1-20230612.114412-mappings-merged.txt"
$steam = "$cache/ManagedComponents/e4steam/284738310465590484/e4steam-forge-mc1.18.2-1.20.2-v0.3.4-lanmc-native-ui.2.jar"
$adapter = "$project/artifacts/agent-runs/guest-runtime-20261114/identity-500-release.jar"
$adapterSha = '864774e8355f65f63615bb3cfcac4c849a5454ba058adae9c2f393e1c1c29641'
$mappingSha = '43660881d0a5fff41cbde7a818726a8c950c39b1380b65cbc3b2d3290963bff1'
$propertySha = '17707ebe5b18b3b6fdc56353dacd5b3442b0004e7e2c5878fcfdd5ffd6afea40'
$seed = '201991997'
$pins = @{
    "$assembly/LANMinecraft.dll"='86690aee6344917788ea4b733d7589fc14cf69226991b99b597c0afe23e6d593'
    "$shared/versions/$profile/$profile.json"='de680055791048582f749d061dc3a2fdcfaff9b04ea3058017c8b91ae9d3feaa'
    "$shared/libraries/net/minecraftforge/forge/1.20.1-47.4.10/forge-1.20.1-47.4.10-client.jar"='839b69b60243ec31a6c53f6ac28d82d8251427a8c8bb946e920129618abdc944'
    $adapter=$adapterSha
    $mapping=$mappingSha
    $java='1977f302375adbb920d41dac65c7e22eb9c2ed8e1e8d6258964154ff16f14406'
    $steam='3f397fc193f14d3c543b5ef9b4613bc149a21ca8e14bd93c39de3d1bc6f9553c'
    "$sharedQa/Forge118SteamQaAgent.java"='d0623d005484ade98198e59fed044e9ec9d2f52614dbd657f7bffc17f8736f1d'
    "$sharedQa/Start-ForgeFixture.ps1"='06312dfefdb9d16e65daba9d48aa7c16bf1358bd1e590faf1e53b001b003c4ab'
    "$sharedQa/clean_owned.py"='9fa8960d6c127a76bdc7855030e49c6b830c8f98aa3bde98e078999d02dc6799'
}
foreach ($pin in $pins.GetEnumerator()) {
    if ((Get-FileHash -LiteralPath $pin.Key -Algorithm SHA256).Hash -ine $pin.Value) { throw "Changed QA input $($pin.Key)." }
}
# The launcher can replace its state for another instance. Only the pinned adapter and JVM properties are reused.
$identity = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
[string[]]$names = $identity.properties.PSObject.Properties.Name
[Array]::Sort($names, [StringComparer]::Ordinal)
$canonical = (($names | ForEach-Object { $_ + '=' + $identity.properties.$_ }) -join "`n") + "`n"
$actual = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical)))
if ($identity.adapterSha256 -cne $adapterSha -or $identity.mappingSha256 -cne $mappingSha -or $actual -ine $propertySha) {
    throw 'The cached state does not use the reviewed stock 500 adapter mappings and launch properties.'
}
$modes = @(if ($Commands -eq 'Both') { 'On','Off' } else { $Commands })
$cachedManifest = if (Test-Path -LiteralPath $published) { @('--cached-manifest', $published) } else { @() }
$plan = python -B "$PSScriptRoot/stage_guest_pair.py" $run --plan --commands $Commands @cachedManifest | ConvertFrom-Json
if ($LASTEXITCODE) { throw 'Could not verify the pinned release.' }
$budget = 650MB
$requiredMiB = 2 * $HeapMiB + 4096
$status = [ordered]@{ release=$plan; launcher=500; adapter=$adapterSha; adapterProperties=$propertySha; commands=$modes; mode='Creative'; seed=$seed;
    transport='loopback TCP'; requiresAvailableMiB=$requiredMiB; heapPerRoleMiB=$HeapMiB; maximumUniqueBytes=$budget }
if (!$RunNative) { $status | ConvertTo-Json -Depth 5; return }

function Confirm-GameSlot {
    if (Get-Process java,javaw -ErrorAction SilentlyContinue) { throw 'Wait for existing Minecraft tasks to finish.' }
    $memory = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
    if ($memory.AvailableMBytes -lt $requiredMiB -or $memory.PagesInputPersec -gt 256) {
        throw "Wait for $requiredMiB MiB available and stable Windows paging. Available $($memory.AvailableMBytes) MiB."
    }
}

Confirm-GameSlot
$storage = python -B "$project/tools/workspace_storage.py" --check | ConvertFrom-Json
if ($LASTEXITCODE -or !$storage.complete -or $storage.unique_bytes + $budget -gt $storage.budget_bytes) {
    throw 'There is insufficient verified space in the shared QA budget.'
}
if (Test-Path -LiteralPath $run) { throw 'Use a new owned game fixture.' }
$cleanup = "$sharedQa/clean_owned.py"
foreach ($path in $run, "$run/scratch/classes", "$run/result", "$run/game", "$run/evidence", "$run/peer-sync") {
    $null = [IO.Directory]::CreateDirectory($path)
}
@{owner='Antimatter Chemistry Reforged local guest QA'; purpose='Native local Creative command comparison';
  createdUtc=[DateTime]::UtcNow.ToString('o'); maximumBytes=$budget;
  deleteAfterUtc=[DateTime]::UtcNow.AddDays(1).ToString('o'); requiredResults=@('result/inputs.json','result/stage.json','result/shared-after.json')} |
    ConvertTo-Json | Set-Content -LiteralPath "$run/RUN.json"
$jobs = @()
$staged = $false
Copy-Item -LiteralPath $cleanup -Destination $run
try {
    $status | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$run/result/inputs.json"
    Copy-Item -LiteralPath $adapter -Destination "$run/scratch/portable-identity-adapter.jar"
    $privateState = "$run/scratch/adapter-state.json"
    @{adapterSha256=$adapterSha; properties=$identity.properties} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $privateState
    # The launcher assembly is the pinned public build. The reused fixture historically labelled itself 498.
    $fixture = "$run/Start-ForgeFixture.ps1"
    $fixtureText = [IO.File]::ReadAllText("$sharedQa/Start-ForgeFixture.ps1")
    [IO.File]::WriteAllText($fixture, $fixtureText.Replace('GameLauncherVersion = ''498''','GameLauncherVersion = ''500'''))
    python -B "$PSScriptRoot/stage_guest_pair.py" $run --commands $Commands --transport $steam --cached-pack "$project/Minecraft/Packs/Antimatter Chemistry Reforged" |
        Set-Content -LiteralPath "$run/result/stage.json"
    if ($LASTEXITCODE) { throw 'The public pack could not be staged independently.' }
    $staged = $true
    $agent = "$run/scratch/guest-clock.jar"
    $probeSource = "$run/scratch/Forge118SteamQaAgent.java"
    $probe = [IO.File]::ReadAllText("$sharedQa/Forge118SteamQaAgent.java")
    $anchor = '        activateNativeAction(form, "selectWorld.create");'
    if ([regex]::Matches($probe, [regex]::Escape($anchor)).Count -ne 1) { throw 'Seed marker must target one native Create World action.' }
    $seedCheck = @'
        String qaSeed = System.getProperty(PREFIX + "seed");
        invoke(state, "m_267759_", new Class<?>[] { String.class }, qaSeed);
        require(qaSeed.equals(invoke(state, "m_267707_")), "The native Create World form did not retain the QA seed.");
        event("native_world_seed", Map.of("seed", qaSeed));
'@
    [IO.File]::WriteAllText($probeSource, $probe.Replace($anchor, $seedCheck + "`n" + $anchor))
    & "$jdk/javac.exe" --release 17 -encoding UTF-8 -d "$run/scratch/classes" $probeSource "$PSScriptRoot/ReforgedHostQa.java"
    if ($LASTEXITCODE) { throw 'Could not compile the reviewed native peer agent.' }
    'Premain-Class: lanminecraft.qa.ReforgedHostQa','' | Set-Content -LiteralPath "$run/scratch/agent.mf" -Encoding ascii
    & "$jdk/jar.exe" cfm $agent "$run/scratch/agent.mf" -C "$run/scratch/classes" .
    if ($LASTEXITCODE) { throw 'Could not build the native peer agent.' }
    $status.agentSha256 = (Get-FileHash -LiteralPath $agent -Algorithm SHA256).Hash.ToLowerInvariant()
    $status | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$run/result/inputs.json"
    foreach ($mode in $modes) {
        Confirm-GameSlot
        $sync = "$run/peer-sync/$mode"
        $null = [IO.Directory]::CreateDirectory($sync)
        foreach ($role in 'host','guest') {
            $key = "$mode-$role"
            $props = @("-Dlanminecraft.steamqa.peerSync=$sync", '-Dlanminecraft.steamqa.requireDefaultWorldPreset=true')
            if ($role -eq 'guest') { $props += '-Dlanminecraft.steamqa.peerClient=true' }
            $opts = @{Shared=$shared; Profile=$profile; Java=$java; Game="$run/game/$key"; Evidence="$run/evidence/$key";
                AdapterState=$privateState; Version='1.20.1'; Agent=$agent; Heap=$HeapMiB; Seconds=720; Preset='minecraft:normal';
                Commands=$mode; Seed=$seed; Player="ReforgedQA$role"; TestProperties=$props; AssemblyPath=$assembly;
                LowerPriority=$true; HiddenStartup=$true}
            $jobs += Start-ThreadJob -ArgumentList $fixture,$opts -ScriptBlock {
                param($launch, $options)
                & $launch @options
            }
        }
        $jobs | Wait-Job | Receive-Job
        foreach ($role in 'host','guest') {
            $key = "$mode-$role"
            $folder = "$run/evidence/$key"
            $exit = Get-Content -LiteralPath "$folder/exit.json" -Raw | ConvertFrom-Json
            $events = Get-Content -LiteralPath "$folder/native-steam-qa.jsonl" | ConvertFrom-Json
            $must = if ($role -eq 'host') { 'complete' } else { 'guest_command_checked' }
            if ($exit.exit -ne 0 -or $events.kind -notcontains $must -or $events.kind -contains 'failure') {
                throw "Native $key did not pass. See its bounded receipts."
            }
            if ($role -eq 'host' -and $events.kind -notcontains 'native_world_seed') { throw "Missing seed receipt for $key." }
        }
        $jobs = @()
    }
} finally {
    if ($jobs.Count) { $jobs | Wait-Job | Out-Null }
    $sharedVerified = $true
    if ($staged) {
        python -B "$PSScriptRoot/stage_guest_pair.py" $run --verify-shared --commands $Commands @cachedManifest |
            Set-Content -LiteralPath "$run/result/shared-after.json"
        $sharedVerified = $LASTEXITCODE -eq 0
    }
    foreach ($mode in $modes) {
        foreach ($role in 'host','guest') {
            $key = "$mode-$role"
            $folder = "$run/evidence/$key"
            foreach ($file in 'native-steam-qa.jsonl','exit.json','supplementaries-onboarding.txt') {
                if (Test-Path -LiteralPath "$folder/$file") {
                    Copy-Item -LiteralPath "$folder/$file" -Destination "$run/result/$key-$file"
                }
            }
            foreach ($file in 'stdout.log','stderr.log') {
                if (Test-Path -LiteralPath "$folder/$file") {
                    Get-Content -LiteralPath "$folder/$file" -Tail 20 |
                        ForEach-Object {$_.Substring(0,[math]::Min(240,$_.Length))} |
                        Set-Content -LiteralPath "$run/result/$key-$file"
                }
            }
            foreach ($link in Get-ChildItem -LiteralPath $folder -Filter 'Content.IE5' -Recurse -Force -Attributes ReparsePoint -ErrorAction SilentlyContinue) {
                if ($link.LinkType -eq 'Junction' -and $link.FullName.StartsWith($folder.Replace('/', '\') + '\',[StringComparison]::OrdinalIgnoreCase)) {
                    [IO.Directory]::Delete($link.FullName)
                }
            }
        }
    }
    python -B "$run/clean_owned.py" game evidence scratch peer-sync Minecraft Start-ForgeFixture.ps1
    if ($LASTEXITCODE) { throw 'Temporary QA files remain. Review owned cleanup before closing the task.' }
    [IO.File]::Delete("$run/clean_owned.py")
    if (!$sharedVerified) { throw 'At least one shared immutable QA archive no longer matched its public bytes.' }
}
