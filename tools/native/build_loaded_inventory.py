"""Bind the observed stock Forge client mod list to the exact approved stage JARs."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote
from zipfile import ZipFile


MINECRAFT = "1.20.1"
FORGE = {"type": "forge", "version": "47.4.10"}
STEAM = "e4steam-forge-mc1.18.2-1.20.2-v0.3.4-lanmc-native-ui.2.jar"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_inventory(stage, evidence):
    lock_path = stage / "intake.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_hash = sha256(lock_path)
    proof = json.loads((evidence / "forge-discovery.json").read_text(encoding="utf-8-sig"))
    receipt = evidence / "forge-discovery.tsv"
    if (proof["intakeSha256"] != lock_hash or proof["discoverySha256"] != sha256(receipt) or
            proof["exitCode"] != 0 or proof["profile"] != "1.20.1-forge-47.4.10"):
        raise ValueError("The Forge discovery evidence does not match the reviewed stage")
    game = stage / "game"
    actual_jars = {p.relative_to(game).as_posix(): sha256(p) for p in (game / "mods").glob("*.jar")}
    locked_jars = {row["path"]: row["sha256"] for row in lock["files"] if row["path"].endswith(".jar")}
    if actual_jars != locked_jars or proof["stageJars"] != len(actual_jars):
        raise ValueError("The staged mod JARs do not match their lock")

    rows = {}
    for line in receipt.read_text(encoding="ascii").splitlines():
        mod_id, name, version, filename, owner = (bytes.fromhex(col).decode() for col in line.split("\t"))
        if mod_id in rows or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", mod_id) or not name or not version:
            raise ValueError(f"Invalid native mod entry {mod_id}")
        rows[mod_id] = (name, version, filename, unquote(owner))
    if (rows["minecraft"][1] != MINECRAFT or rows["forge"][1] != FORGE["version"] or
            rows["e4steam"][2:] != (STEAM, f"mods/{STEAM}")):
        raise ValueError("The actual native game, loader or transport does not match the expected profile")

    mods = []
    for mod_id, (name, version, filename, owner) in sorted(rows.items()):
        if mod_id in ("minecraft", "forge", "e4steam"):
            continue
        source, *nested = re.split(r"#\d+!/", owner)
        if source not in actual_jars or PurePosixPath((nested or [source])[-1]).name != filename:
            raise ValueError(f"The native mod {mod_id} is not bound to its shipped owner")
        data = (game / source).read_bytes()
        for rel in nested:
            with ZipFile(io.BytesIO(data)) as archive:
                data = archive.read(rel)
        with ZipFile(io.BytesIO(data)) as archive:
            if "META-INF/mods.toml" not in archive.namelist():
                raise ValueError(f"Native nested path {filename} contains no Forge metadata")
        row = {"id": mod_id, "name": name, "version": version, "nativeSourceFile": filename, "source": source}
        if nested:
            row["nativeNestedPaths"] = nested
        mods.append(row)
    return {"schemaVersion": 1, "minecraftVersion": MINECRAFT, "loader": FORGE, "sourceJars": actual_jars,
            "upstreamLockSha256": lock_hash, "mods": mods}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = build_inventory(args.stage, args.evidence)
    args.destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(result['mods'])} actual pack mod IDs backed by {len(result['sourceJars'])} verified shipped JARs")


if __name__ == "__main__":
    main()
