# Native Forge QA for Antimatter Chemistry Reforged 2.0.3

The native fixture uses an isolated installation of the verified pack stage, stock Minecraft 1.20.1 and Forge 47.4.10, Java 17, public launcher 500, and the exact Steam transport selected by that launcher.

The official client archive is CurseForge project 1771794, file 9558909, 2,214,600 bytes with SHA256 `23e5968067ad91b55e60bbd85ecd0de3b5a8a46cf7d06f6684c8d565f0d62580`. The approved stage intake SHA256 is `570a966dc7c95bd9c1a4f8e27c48bfa70ce022853b9cdbb697b11093ac85428c`.

## Discovery and shipped inventory

Forge's client-side `LoadingModList` reported 176 native IDs with no preload errors or broken files. Excluding Minecraft, Forge, and launcher-managed e4steam gives the 173 pack IDs in `library/loaded-mods.json`, based on 161 fully verified JARs. Eleven selected IDs came from nested JARs. The receipt SHA256 is `13cd7fc1dfd1c079fbd17cddfd0010a6b642b89b739140f9e01d02ff34eaf710`. `library/loaded-mods.json` SHA256 is `791b54053f29f8182d9e188f1cabf8e630affa294f95401a8a4dd695d0aeb338`.

The discovery observer stops the stock Forge bootstrap after native mod validation. The full-host fixture runs separately and uses the shared `Forge118SteamQaAgent`. It opens the actual default `minecraft:normal` preset, verifies window title, reads native dimension generation, and verifies the first-join water bucket delivered by the author's `amworld:first_join`. That exact function delivers items to inventory once, using the `amworld.init` player tag. The first-join receipt should identify the real flat generator and biome `amworld:antimatter_flats`.

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

The host check uses one 6 GiB client and requires an active Steam session. The shared QA agent records the generated world, native publication state, window title, actual command state and Steam metadata. Record a real incoming two-player test separately. Retain the compact receipts and remove the test instance, saved world, generated loader view and raw logs when the run is finished.
