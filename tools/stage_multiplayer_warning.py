"""Rebuild the published KubeJS archive with the reviewed one-file overlay."""

import argparse
import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK / "tools/keybinds"))
from stage_release import encoded, pin, stage

SCRIPT = "kubejs/startup_scripts/14_lava_generators.js"
POLICY = b"""// Set only the Minecraft 1.20.1 equivalent of Do not show this screen again.
ClientEvents.init(() => {
  const options = Client.options || Client.f_91066_
  if ('skipMultiplayerWarning' in options) {
    options.skipMultiplayerWarning = true
  } else {
    options.f_92083_ = true
  }
})
"""


def verify_script(data):
    if data.count(POLICY) != 1 or not data.endswith(POLICY):
        raise ValueError("The final client startup script must set skipMultiplayerWarning to true")


def build(base, old_archive, library, output, revision, date, old_recipe):
    old = json.loads(base.read_bytes())
    previous = json.loads(old_recipe.read_bytes())
    current = json.loads((PACK / "tools/overlay.json").read_bytes())
    previous_patch, = previous.pop("patches")
    patch, = current.pop("patches")
    if current != previous or any(patch[key] != previous_patch[key] for key in ("path", "before", "from")):
        raise ValueError("The candidate contains additional overlay changes")
    path = patch["path"]
    if path != SCRIPT:
        raise ValueError("The policy must be applied to its reviewed startup script")
    old_asset, = [asset for asset in old["assets"] if path in asset["covers"]]
    expected = {row["path"]: {k: row[k] for k in ("sizeBytes", "sha256")} for row in old["files"]}
    if pin(old_archive.read_bytes()) != {k: old_asset[k] for k in ("sizeBytes", "sha256")}:
        raise ValueError("Published KubeJS archive hash changed")
    if expected[path] != previous_patch["after"]:
        raise ValueError("The first patch is not the published script")
    before = previous_patch["to"].encode()
    with ZipFile(old_archive) as archive:
        if sorted(archive.namelist()) != sorted(old_asset["covers"]):
            raise ValueError("Published KubeJS inventory changed")
        sources = {name: archive.read(name) for name in archive.namelist()}
    if any(pin(data) != expected[name] for name, data in sources.items()):
        raise ValueError("Published KubeJS contents changed")
    if sources[path].count(before) != 1:
        raise ValueError("Expected exactly one original script fragment")
    sources[path] = sources[path].replace(before, patch["to"].encode(), 1)
    verify_script(sources[path])
    if pin(sources[path]) != patch["after"]:
        raise ValueError("Candidate script does not match its overlay pin")

    stage(base, library, output, revision, date)
    target = output / "assets/kubejs.zip"
    with ZipFile(target, "x") as archive:
        for source, data in sorted(sources.items()):
            info = ZipInfo(source)
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
    asset_pin = pin(target.read_bytes())
    name = f"r-{asset_pin['sha256'][:12]}-kubejs.zip"
    target.rename(target.with_name(name))
    manifest_path = output / "pack-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["assets"].remove(old_asset)
    manifest["assets"].append({"name": name, "kind": "zipRoot", "covers": old_asset["covers"], **asset_pin})
    manifest["assets"].sort(key=lambda row: row["name"])
    next(row for row in manifest["files"] if row["path"] == path).update(patch["after"])
    manifest_path.write_bytes(encoded(manifest))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verify":
        verify_script((Path(sys.argv[2]) / SCRIPT).read_bytes())
        print("Verified the multiplayer warning option in the prepared client")
        sys.exit(0)
    parser = argparse.ArgumentParser(description=__doc__)
    for parameter in ("base", "old_archive", "library", "output", "old_recipe"):
        parser.add_argument(parameter, type=Path)
    parser.add_argument("revision")
    parser.add_argument("date")
    args = parser.parse_args()
    build(args.base, args.old_archive, args.library, args.output, args.revision, args.date, args.old_recipe)
