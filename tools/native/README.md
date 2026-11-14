# Native Forge QA for Antimatter Chemistry Reforged 2.0.3

The native fixture uses an isolated installation of the verified pack stage, stock Minecraft 1.20.1 and Forge 47.4.10, Java 17, public launcher 500, and the exact Steam transport selected by that launcher.

The official client archive is CurseForge project 1771794, file 9558909, 2,214,600 bytes with SHA256 `23e5968067ad91b55e60bbd85ecd0de3b5a8a46cf7d06f6684c8d565f0d62580`. The approved stage intake SHA256 is `570a966dc7c95bd9c1a4f8e27c48bfa70ce022853b9cdbb697b11093ac85428c`.

## Discovery and shipped inventory

Forge's client-side `LoadingModList` reported 176 native IDs with no preload errors or broken files. Excluding Minecraft, Forge, and launcher-managed e4steam gives the 173 pack IDs in `library/loaded-mods.json`, based on 161 fully verified JARs. Eleven selected IDs came from nested JARs. The receipt SHA256 is `13cd7fc1dfd1c079fbd17cddfd0010a6b642b89b739140f9e01d02ff34eaf710`. `library/loaded-mods.json` SHA256 is `791b54053f29f8182d9e188f1cabf8e630affa294f95401a8a4dd695d0aeb338`.

The discovery observer stops the stock Forge bootstrap after native mod validation. The full native title reported all 176 of the same IDs, versions, and native JAR filenames. The host fixture uses the shared `Forge118SteamQaAgent`. Its pack-side adapter waits for the Supplementaries message countdown and invokes the normal close action without selecting the persistent disable option. Minecraft's native accessibility onboarding is also completed in the disposable instance.

## Native host result

The exact game window title was verified at startup, before opening the world to Steam, and after publication. The default `minecraft:normal` preset created a `FlatLevelSource` Overworld with biome `amworld:antimatter_flats`. The author gave the water bucket in native inventory slot 4 using `amworld:first_join`; the function delivers items once using the `amworld.init` player tag.

The native pause action opened the world with one press, retained Survival with commands disabled for the host and the synthetic guest, and exposed the Reports button. A real Steam lobby was created with matching world name, launcher player name and display flag. Native chat showed one local port row and one ready Steam row with the expected actions. The world saved and the client exited normally. The host JSONL SHA256 is `ee175d4250273ace6d5bae9b1ef5ff080151e3e2099a7624f238567e8c59c531`. The saved `level.dat` SHA256 after that client fully exited was `d807b3e985126f6310cb299e1472dfc746fcbbf839564bf3bad5cc6b78f66342`.

The saved world reopened under the same test identity and passed the checks again, including preserved biome, starter inventory and another real Steam lobby. The reopen receipt SHA256 is `422ec29c6615850fe1c52b8153aa601f4b243e88ee8b9906bffaf7f8c259a4bf` and the final clean-shutdown `level.dat` SHA256 is `a5ad8f9b16b17b82b788ad1fb6737f9b3b44337dfd441f7675257a58fb6abc3f`. Actual incoming guest, commands-on world, and remote account discovery are untested.

The reopen log records 36 distinct Malum advancement parse errors, 14 warnings about missing NuclearCraft fluid tags, eight TFMG model load errors, and one JER plugin error during a lookup for `nuclearcraft:wasteland`. Cyclic logs four errors about recipe content involving KubeJS identifiers. The game still loaded the world and opened Steam access. Authored files were not changed to suppress these messages. A separate production launcher options check seeded `lang:ru_ru` on the empty instance and preserved a subsequent saved `lang:en_us` selection. The full gameplay fixture ran in English because it used the existing test options.

## Repeat the checks

First verify the full pack stage under an owned `artifacts/agent-runs/<label>` using `release_overlay.py stage --locked` and the approved `upstream-lock.json`. The native profile view uses the official exact Forge installer SHA256 `1912760b4cb6b803d8a826de603c9076b1da71ec2765e9a1f8c1ca78f65278e3` and the official patched client SHA1 `4d8a9a63dc16a45d7fc5c54c627234f601d0cc17`. Use the exact Forge profile preparer in [Escape The End's shared platform calibration](https://github.com/MarkZamore/Escape-The-End/blob/f0e52ee/tools/prepare_native_forge.py). It verifies the source profile, reuses the launcher cache, and writes only under the marked test run. Put its output under `native-loader` in the same owned run.

```powershell
$qa = 'LocalSources/Antimatter-Chemistry-Reforged/tools/native'
$expected = '570a966dc7c95bd9c1a4f8e27c48bfa70ce022853b9cdbb697b11093ac85428c'
$run = 'artifacts/agent-runs/antimatter-reforged-203'
pwsh -NoProfile -File "$qa/Run-ForgeDiscovery.ps1" -ExpectedIntakeSha256 $expected
python -B "$qa/build_loaded_inventory.py" "$run/stage" "$run/evidence" "$run/evidence/loaded-mods.json"
pwsh -NoProfile -File "$qa/Run-ForgeDiscovery.ps1" -ExpectedIntakeSha256 $expected -NativeHost
```

For a reopen, remove only the completed runner's `runtime-qa/native-host-temp` directory after the Java process has exited, retaining the test game. Hash the closed world's `level.dat` and pass `-HostLabel native-host-reopen -ReopenLevelSha256 <sha256>` to the same `-NativeHost` command.

The host check uses one 6 GiB client and requires an active Steam session. The shared QA agent records the generated world, native publication state, window title, actual command state and Steam metadata. Record a real incoming two-player test separately. Retain the compact receipts and remove the test instance, saved world, generated loader view and raw logs when the run is finished.
