"""Attach the reviewed preset and bind the library card to the new release revision."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from build_preset import PRESET

PRESET_PATH = "launcher/controls-preset.txt"


def pin(data):
    return {"sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def stage(manifest_path, library_path, output, revision, generated_at):
    manifest = json.loads(manifest_path.read_bytes())
    if manifest["packId"] != "minecraft-17" or manifest["schemaVersion"] != 2:
        raise ValueError("Expected the Reforged v2 manifest")
    library = manifest["library"]
    if library["revision"] != manifest["revision"] or any(
        library[key] != value for key, value in pin(library_path.read_bytes()).items()
    ):
        raise ValueError("Library bytes differ from the base manifest")
    with ZipFile(library_path) as archive:
        if sorted(archive.namelist()) != ["library.json", "preview.jpg"]:
            raise ValueError("Unexpected library member")
        card = json.loads(archive.read("library.json"))
        preview = archive.read("preview.jpg")
    if card["revision"] != manifest["revision"] or card["id"] != manifest["packId"]:
        raise ValueError("Base library card differs from the manifest")

    paths = [asset for asset in manifest["assets"] if PRESET_PATH in asset["covers"]]
    if any(asset["covers"] != [PRESET_PATH] for asset in paths):
        raise ValueError("The previous preset must have a separate asset")
    manifest["assets"] = [asset for asset in manifest["assets"] if asset not in paths]
    manifest["files"] = [row for row in manifest["files"] if row["path"] != PRESET_PATH]
    output.mkdir()
    assets = output / "assets"
    assets.mkdir()
    data = PRESET.read_bytes()
    preset_pin = pin(data)
    name = f"c-{preset_pin['sha256'][:12]}-controls-preset.txt"
    (assets / name).write_bytes(data)
    manifest["files"].append({"path": PRESET_PATH, **preset_pin})
    manifest["assets"].append({"name": name, "kind": "jar", "covers": [PRESET_PATH], **preset_pin})

    if revision != manifest["revision"]:
        card["revision"] = revision
        temporary = assets / "library.zip"
        with ZipFile(temporary, "x") as archive:
            for path, content in (("library.json", encoded(card)), ("preview.jpg", preview)):
                info = ZipInfo(path)
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, content)
        new_pin = pin(temporary.read_bytes())
        library_name = f"library-{new_pin['sha256']}.zip"
        temporary.rename(assets / library_name)
        manifest["library"] = {"name": library_name, "revision": revision, **new_pin}
    manifest.update(revision=revision, generatedAtUtc=generated_at)
    manifest["assets"].sort(key=lambda row: row["name"])
    manifest["files"].sort(key=lambda row: row["path"])
    (output / "pack-manifest.json").write_bytes(encoded(manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("library", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("revision")
    parser.add_argument("generated_at")
    arguments = parser.parse_args()
    stage(arguments.manifest, arguments.library, arguments.output, arguments.revision, arguments.generated_at)
