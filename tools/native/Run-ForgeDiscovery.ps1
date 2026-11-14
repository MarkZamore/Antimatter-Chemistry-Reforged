[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ExpectedIntakeSha256,
    [string]$RunLabel = 'antimatter-reforged-203',
    [string]$Jdk = $env:JAVA_HOME,
    [string]$HostLabel = 'native-host',
    [ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ReopenLevelSha256,
    [switch]$NativeHost,
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path "$PSScriptRoot/../../../..").Path
if ($RunLabel -notmatch '^[a-zA-Z0-9_-]+$' -or $HostLabel -notmatch '^[a-zA-Z0-9_-]+$') {
    throw 'Expected single run and receipt names.'
}
if ($ReopenLevelSha256 -and !$NativeHost) { throw 'A saved world can only be opened in the native host check.' }
$run = Join-Path $project "artifacts/agent-runs/$RunLabel"
if (!(Test-Path -LiteralPath "$run/RUN.json") -or (Get-Item -LiteralPath $run).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Expected an owned QA run directory.'
}
$cache = "$project/Minecraft/Launcher"
$runtime = "$run/native-loader"
$stage = "$run/stage/game"
$intake = "$run/stage/intake.json"
$game = "$run/native-discovery-game"
$evidence = "$run/evidence"
$scratch = "$run/native-discovery-temp"
if ($NativeHost) {
    $game = "$run/runtime-qa/Minecraft/Personal/Instances/Antimatter Chemistry Reforged"
    $evidence = "$run/runtime-qa/evidence/$HostLabel"
    $scratch = "$run/runtime-qa/native-host-temp"
}
$heap = if ($NativeHost) { 6144 } else { 1024 }
$java = "$cache/JavaRuntimes/runtime/windows-x64/java-17/bin/java.exe"
$jdkBin = if ($Jdk) { "$Jdk/bin" } else { 'C:/Tools/jdk-25.0.2/bin' }
$profileId = '1.20.1-forge-47.4.10'
$assemblyRoot = "$cache/Runtime/e86ff2d180aeab13cf0d77bf6f0d1b1fceaae5ec8ae8d8969cb68bb9ecf49cab"
$pins = @{
    "$assemblyRoot/LANMinecraft.dll" = '86690AEE6344917788EA4B733D7589FC14CF69226991B99B597C0AFE23E6D593'
    $java = '1977F302375ADBB920D41DAC65C7E22EB9C2ED8E1E8D6258964154FF16F14406'
    $intake = $ExpectedIntakeSha256
}
foreach ($pair in $pins.GetEnumerator()) {
    if ((Get-FileHash -LiteralPath $pair.Key -Algorithm SHA256).Hash -ine $pair.Value) {
        throw "Unexpected input $($pair.Key)."
    }
}
$lock = Get-Content -LiteralPath $intake -Raw | ConvertFrom-Json
if ($lock.client.sha256 -ine '23e5968067ad91b55e60bbd85ecd0de3b5a8a46cf7d06f6684c8d565f0d62580') {
    throw 'The stage does not originate from the exact 2.0.3 client archive.'
}
$forgeJar = "$runtime/libraries/net/minecraftforge/forge/1.20.1-47.4.10/forge-1.20.1-47.4.10-client.jar"
if ((Get-FileHash -LiteralPath $forgeJar -Algorithm SHA1).Hash -ine '4d8a9a63dc16a45d7fc5c54c627234f601d0cc17') {
    throw 'The native Forge client differs from the official patch.'
}
foreach ($name in 'CmlLib.Core.Commons.dll','CmlLib.Core.dll','LANMinecraft.dll') {
    $assembly = [Reflection.Assembly]::LoadFrom("$assemblyRoot/$name")
}
$descriptor = [Minecraft.PackManifestService]::Load($stage)
if ($descriptor.MinecraftVersion -ne '1.20.1' -or $descriptor.Loader.Version -ne '47.4.10' -or !$descriptor.PreserveWorldSettingsOnShare) {
    throw 'The prepared descriptor differs from the reviewed Forge Steam profile.'
}
$transport = [Minecraft.SteamTransportCatalog]::Find($descriptor)
$managed = "$cache/ManagedComponents/e4steam/$($transport.CacheFileId)/$($transport.FileName)"
if ($transport.Sha256 -ne '3f397fc193f14d3c543b5ef9b4613bc149a21ca8e14bd93c39de3d1bc6f9553c' -or
    (Get-FileHash -LiteralPath $managed -Algorithm SHA256).Hash -ine $transport.Sha256) {
    throw 'Unexpected launcher-managed transport.'
}
$paths = [CmlLib.Core.MinecraftPath]::new($game)
$paths.Library = "$runtime/libraries"
$paths.Versions = "$runtime/versions"
$paths.Assets = "$cache/Shared/assets"
$paths.Resource = "$cache/Shared/resources"
$paths.Runtime = "$cache/Shared/runtime"
$parameters = [CmlLib.Core.MinecraftLauncherParameters]::CreateDefault($paths)
$parameters.VersionLoader = [CmlLib.Core.VersionLoader.LocalJsonVersionLoader]::new($paths)
$launcher = [CmlLib.Core.MinecraftLauncher]::new($parameters)
$profile = $launcher.GetVersionAsync($profileId, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
$jars = @(Get-ChildItem -LiteralPath "$stage/mods" -File -Filter '*.jar')
$expectedJars = @($lock.files | Where-Object { $_.path -like 'mods/*.jar' })
if ($jars.Count -ne $expectedJars.Count -or $jars.Count -eq 0 -or
    ($jars | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint -or $_.Name -match '^e4(mc|steam)' })) {
    throw 'The exact candidate stage has missing JARs, linked JARs or a conflicting transport.'
}
foreach ($file in $expectedJars) {
    $item = Get-Item -LiteralPath "$stage/$($file.path)"
    if ($item.Length -ne $file.sizeBytes -or (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash -ine $file.sha256) {
        throw "The actual staged JAR differs from the pinned file $($file.path)."
    }
}
$proof = @{ profile=$profile.Id; launcherVersion=500; intakeSha256=$ExpectedIntakeSha256.ToLowerInvariant();
           stageJars=$jars.Count; steamSha256=$transport.Sha256; heapMiB=$heap; nativeHost=$NativeHost.IsPresent }
if ($Plan) { $proof | ConvertTo-Json -Compress; return }
$free = [math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
if ($free -lt $heap + 4096) { throw "Insufficient available memory for the isolated Forge probe ($free MiB)." }
$receipt = if ($NativeHost) { "$evidence/native-steam-qa.jsonl" } else { "$evidence/forge-discovery.tsv" }
if (((Test-Path -LiteralPath $game) -and !$ReopenLevelSha256) -or
    (Test-Path -LiteralPath $scratch) -or (Test-Path -LiteralPath $receipt)) {
    throw 'Use a fresh discovery instance and evidence.'
}
if ($ReopenLevelSha256) {
    $saved = "$game/saves/LanMcSteamQa120ACReforged/level.dat"
    if ((Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ine $ReopenLevelSha256) {
        throw 'The saved QA world differs from the closed client receipt.'
    }
}
foreach ($path in $evidence, "$game/config", "$game/mods", "$scratch/classes", "$scratch/home/AppData/Local", "$scratch/home/AppData/Roaming") {
    $null = [IO.Directory]::CreateDirectory($path)
}
if (!$ReopenLevelSha256) {
    foreach ($jar in $jars) {
        $null = New-Item -ItemType HardLink -Path "$game/mods/$($jar.Name)" -Target $jar.FullName
    }
    [IO.File]::Copy($managed, "$game/mods/$($transport.FileName)")
}
$appPaths = [Minecraft.AppPaths]::new($run)
$logger = [Minecraft.Logger]::new("$scratch/launcher.log")
if ($NativeHost) {
    if (!$ReopenLevelSha256) {
        foreach ($file in Get-ChildItem -LiteralPath $stage -Force) {
            if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked stage entry.' }
            if ($file.Name -eq 'mods') { continue }
            if ($file.Name -eq 'config') {
                Get-ChildItem -LiteralPath $file.FullName -Force | ForEach-Object {
                    Copy-Item -LiteralPath $_.FullName -Destination "$game/config" -Recurse
                }
            } else { Copy-Item -LiteralPath $file.FullName -Destination $game -Recurse }
        }
    }
    $baseJar = "$runtime/versions/1.20.1/1.20.1.jar"
    [void][Minecraft.OptionsDefaultsService]::new($logger).Apply($stage, $game, $descriptor.MinecraftVersion, $false, $baseJar)
    $prepared = [Minecraft.PreparedRuntime]::new($runtime, $profileId, $java, $baseJar, $descriptor)
    $adapter = [Minecraft.PortableIdentityAdapterService]::new($appPaths, $logger)
    try {
        $instanceArgs = @($adapter.PrepareJvmArgumentsAsync($prepared, $game, [Threading.CancellationToken]::None).GetAwaiter().GetResult())
    } finally { $adapter.Dispose() }
    $presentation = $assembly.GetType('Minecraft.GameWindowPresentation', $true).GetMethod('Prepare', [Reflection.BindingFlags]'NonPublic, Static')
    $instanceArgs += @($presentation.Invoke($null, [object[]]@($appPaths, $prepared, $profile, $stage, $game)))
    $instanceArgs += [Minecraft.PackJvmArgumentsService]::new().Load($game)
    $instanceArgs += @('-Dlink.e4steam.launcherPlayerName=LanMcPackQa', "-Dlanminecraft.steamqa.run=$run",
        "-Dlanminecraft.steamqa.game=$game", "-Dlanminecraft.steamqa.evidence=$evidence", '-Dlanminecraft.steamqa.minecraftVersion=1.20.1',
        '-Dlanminecraft.steamqa.worldSuffix=ACReforged', '-Dlanminecraft.steamqa.worldPreset=minecraft:normal',
        '-Dlanminecraft.steamqa.requireDefaultWorldPreset=true', '-Dlanminecraft.steamqa.expectedInitialItem=minecraft:water_bucket',
        '-Dlanminecraft.steamqa.expectedWindowTitle=Antimatter Chemistry Reforged')
    if ($ReopenLevelSha256) { $instanceArgs += "-Dlanminecraft.steamqa.reopenLevelSha256=$ReopenLevelSha256" }
    $class = 'ReforgedHostQa'
    $sources = @("$PSScriptRoot/$class.java", "$project/tools/PackData/CurseForge/Forge118SteamQaAgent.java")
} else {
    [IO.File]::WriteAllText("$game/config/fml.toml", "earlyWindowControl=false`n")
    $instanceArgs = @('-Djava.awt.headless=true', '-XX:ActiveProcessorCount=2',
        "-Dlanminecraft.discovery.run=$run", "-Dorg.lwjgl.glfw.libname=$scratch/unavailable-glfw.dll")
    $class = 'ForgeDiscoveryAgent'
    $sources = @("$PSScriptRoot/$class.java")
}
& "$jdkBin/javac.exe" --release 17 -encoding UTF-8 -d "$scratch/classes" @sources
if ($LASTEXITCODE) { throw 'Compilation of the native observer failed.' }
@('Manifest-Version: 1.0',"Premain-Class: lanminecraft.qa.$class",'') |
    Set-Content -LiteralPath "$scratch/agent.mf" -Encoding ascii
& "$jdkBin/jar.exe" cfm "$scratch/agent.jar" "$scratch/agent.mf" -C "$scratch/classes" .
if ($LASTEXITCODE) { throw 'Packaging of the native observer failed.' }

$options = [CmlLib.Core.ProcessBuilder.MLaunchOption]::new()
$options.Path = $paths
$options.JavaPath = $java
$options.NativesDirectory = "$scratch/natives"
$options.MinimumRamMb = 384
$options.MaximumRamMb = $heap
$options.ScreenWidth = 960
$options.ScreenHeight = 540
$options.FullScreen = $false
$options.Session = [CmlLib.Core.Auth.MSession]::CreateOfflineSession('LanMcPackQa')
$options.GameLauncherName = 'LANMinecraft'
$options.GameLauncherVersion = '500'
$options.VersionType = $profileId
$extra = [Collections.Generic.List[CmlLib.Core.ProcessBuilder.MArgument]]::new()
foreach ($argument in @('-Dfile.encoding=UTF-8', "-Duser.home=$scratch/home", "-Djava.io.tmpdir=$scratch",
    "-XX:ErrorFile=$scratch/hs_err_pid%p.log", "-javaagent:$scratch/agent.jar") + $instanceArgs) {
    $extra.Add([CmlLib.Core.ProcessBuilder.MArgument]::new($argument))
}
$options.ExtraJvmArguments = $extra
$flags = [Reflection.BindingFlags]'NonPublic, Static'
$build = $assembly.GetType('Minecraft.MinecraftLaunchArguments', $true).GetMethod('BuildProcess', $flags)
$process = $build.Invoke($null, [object[]]@($launcher, $profile, $options))
$start = $process.StartInfo
$start.WorkingDirectory = $game
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
foreach ($key in 'SteamAppId','SteamGameId','SteamOverlayGameId','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS') {
    $null = $start.Environment.Remove($key)
}
if ($NativeHost) {
    $appId = [Minecraft.SteamworksApiFacade]::SharedAppId.ToString([Globalization.CultureInfo]::InvariantCulture)
    $start.Environment['SteamAppId'] = $appId
    $start.Environment['SteamGameId'] = $appId
}
foreach ($pair in @{ HOME="$scratch/home"; USERPROFILE="$scratch/home"; APPDATA="$scratch/home/AppData/Roaming";
    LOCALAPPDATA="$scratch/home/AppData/Local"; TEMP=$scratch; TMP=$scratch }.GetEnumerator()) {
    $start.Environment[$pair.Key] = $pair.Value
}
$builder = $assembly.GetType('Minecraft.JavaLaunchArgumentFile', $true).GetMethod('Prepare', $flags)
$complete = $assembly.GetType('Minecraft.MinecraftProcessService', $true).GetMethod('CompleteJvmArguments', $flags)
$arguments = [string[]]$complete.Invoke($null, [object[]]@($start, $profile, $game, [Minecraft.PackJvmArgumentsService]::new(), $null))
$main = [Array]::IndexOf($arguments, [string]$profile.MainClass)
$argFile = $builder.Invoke($null, [object[]]@($appPaths, $start, $arguments, 17, $main, $logger))
$stdout = [IO.File]::OpenWrite("$scratch/stdout.log")
$stderr = [IO.File]::OpenWrite("$scratch/stderr.log")
$started = $false
try {
    if (!$process.Start()) { throw 'Could not start the isolated Forge discovery process.' }
    $started = $true
    $process.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
    $process.Id | Set-Content -LiteralPath "$scratch/owned.pid"
    $output = $process.StandardOutput.BaseStream.CopyToAsync($stdout)
    $errors = $process.StandardError.BaseStream.CopyToAsync($stderr)
    $deadline = [DateTime]::UtcNow.AddSeconds($(if ($NativeHost) { 660 } else { 115 }))
    while (!$process.WaitForExit(500)) {
        if ([DateTime]::UtcNow -ge $deadline -or $stdout.Length + $stderr.Length -gt 6MB) {
            throw 'Forge discovery exceeded its time or log limit.'
        }
    }
    [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($output, $errors))
    if ($process.ExitCode -ne 0 -or !(Test-Path -LiteralPath $receipt)) {
        throw "Forge probe did not produce a native receipt. See $scratch."
    }
    $proof.freeMiBAtStart = $free
    $proof.exitCode = $process.ExitCode
    $proof.discoverySha256 = (Get-FileHash -LiteralPath $receipt -Algorithm SHA256).Hash.ToLowerInvariant()
    $proof | ConvertTo-Json | Set-Content -LiteralPath "$evidence/process.json"
    if (!$NativeHost) { $proof | ConvertTo-Json | Set-Content -LiteralPath "$evidence/forge-discovery.json" }
} finally {
    if ($started -and !$process.HasExited) { $process.Kill($true); $process.WaitForExit() }
    if ($argFile) { $argFile.Dispose() }
    $stderr.Dispose()
    $stdout.Dispose()
    $process.Dispose()
}
