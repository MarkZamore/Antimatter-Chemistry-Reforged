"""Verify the published pack and prepare serial game pairs with one copy of each immutable JAR."""

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import urllib.request
from zipfile import ZipFile


RELEASE = "https://github.com/MarkZamore/Antimatter-Chemistry-Reforged/releases/download/pack-latest/"
REVISION = "af371899b7e9ea025a84ca2a04ad0e56283c6447"
MANIFEST_SHA = "c6723529775c858ec59cfb70a6af948a56000d19ed152adabc22278ea38088cc"
STEAM_SHA = "3f397fc193f14d3c543b5ef9b4613bc149a21ca8e14bd93c39de3d1bc6f9553c"


def fetch(label, maximum):
    url = RELEASE + label + f"?qa={time.time_ns()}"
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "LANMinecraft local guest QA"})
    with urllib.request.urlopen(request, timeout=50) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"Unexpected public asset size: {label}")
    return data


def check(data, pin, path):
    if len(data) != pin["sizeBytes"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError(f"SHA256/size mismatch: {path}")


def manifest_input(cached):
    data = cached.read_bytes() if cached else fetch("pack-manifest.json", 1_000_000)
    if hashlib.sha256(data).hexdigest() != MANIFEST_SHA:
        raise ValueError("Public manifest changed before guest QA")
    manifest = json.loads(data)
    if manifest["revision"] != REVISION or manifest["packId"] != "minecraft-17":
        raise ValueError("Public manifest describes a different release")
    rows = {row["path"]: row for row in manifest["files"]}
    if (len(rows) != len(manifest["files"]) or
            len({name.casefold() for name in rows}) != len(rows) or
            Counter(name for row in manifest["assets"] for name in row["covers"]) != Counter(rows.keys())):
        raise ValueError("Invalid public manifest coverage")
    return manifest, rows


def safe_parts(name):
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")) or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe manifest path: {name}")
    return path.parts


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def shareable(name):
    path = PurePosixPath(name)
    return len(path.parts) == 2 and path.parts[0] == "mods" and path.suffix == ".jar"


def game_paths(root, modes):
    return [root / "game" / f"{mode}-{role}" for mode in modes for role in ("host", "guest")]


def stage(root, manifest, rows, transport, cached_pack, modes):
    if root.parent.name != "agent-runs" or not (root / "RUN.json").is_file():
        raise ValueError("Use a marked QA run")
    if sha(transport) != STEAM_SHA:
        raise ValueError("Wrong managed e4steam transport")
    roles = game_paths(root, modes)
    for role in roles:
        role.mkdir(parents=True, exist_ok=False)
    roles = [Path("\\\\?\\" + str(role)) if os.name == "nt" else role for role in roles]

    def write(name, data):
        check(data, rows[name], name)
        first = None
        for role in roles:
            target = role.joinpath(*safe_parts(name))
            target.parent.mkdir(parents=True, exist_ok=True)
            if first is not None and shareable(name):
                os.link(first, target)
            else:
                target.write_bytes(data)
                first = target

    for asset in manifest["assets"]:
        remaining = []
        for name in asset["covers"]:
            local = cached_pack.joinpath(*safe_parts(name)) if cached_pack else None
            if (local is not None and local.is_file() and local.resolve(strict=True) == local and
                    local.stat().st_size == rows[name]["sizeBytes"] and sha(local) == rows[name]["sha256"]):
                write(name, local.read_bytes())
            else:
                remaining.append(name)
        if not remaining:
            continue
        data = fetch(asset["name"], asset["sizeBytes"])
        check(data, asset, asset["name"])
        if asset["kind"] == "zipRoot":
            with ZipFile(io.BytesIO(data)) as archive:
                if Counter(archive.namelist()) != Counter(asset["covers"]):
                    raise ValueError(f"Unexpected public archive coverage: {asset['name']}")
                for name in remaining:
                    if archive.getinfo(name).file_size != rows[name]["sizeBytes"]:
                        raise ValueError(f"Unexpected native file size: {name}")
                    write(name, archive.read(name))
        else:
            if asset["kind"] != "jar" or len(remaining) != 1:
                raise ValueError(f"Unexpected direct release asset: {asset['name']}")
            write(remaining[0], data)

    for role in roles:
        steam_config = role / "config/e4steam/e4steam.toml"
        steam_config.parent.mkdir(parents=True, exist_ok=True)
        with steam_config.open("x", encoding="ascii") as output:
            output.write("hostEnabled = false\n")
        (role / "mods" / transport.name).write_bytes(transport.read_bytes())
        with (role / "options.txt").open("x", encoding="ascii") as output:
            output.write("lang:ru_ru\nfullscreen:false\n")


def verify_shared(root, rows, modes):
    seen = 0
    for name, pin in rows.items():
        if not shareable(name):
            continue
        linked = [role / name for role in game_paths(root, modes)]
        for path in linked:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path or info.st_nlink != len(linked) or
                    info.st_size != pin["sizeBytes"] or sha(path) != pin["sha256"]):
                raise ValueError(f"Shared QA immutable JAR changed: {name}")
        if not all(os.path.samefile(linked[0], path) for path in linked[1:]):
            raise ValueError(f"QA paths do not share exactly one immutable JAR: {name}")
        seen += 1
    return seen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--transport", type=Path)
    parser.add_argument("--cached-pack", type=Path)
    parser.add_argument("--cached-manifest", type=Path, help="Previously fetched pinned bytes for plan/post-run verification")
    parser.add_argument("--commands", choices=("Both", "On", "Off"), default="Both")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--verify-shared", action="store_true")
    args = parser.parse_args()
    manifest, rows = manifest_input(args.cached_manifest)
    modes = ("On", "Off") if args.commands == "Both" else (args.commands,)
    total = sum(pin["sizeBytes"] for pin in rows.values())
    shared = sum(pin["sizeBytes"] for name, pin in rows.items() if shareable(name))
    copies = 2 * len(modes)
    unique = copies * total - (copies - 1) * shared
    if args.plan:
        print(json.dumps({"revision": REVISION, "manifestSha256": MANIFEST_SHA, "files": len(rows), "uniqueAuthorBytes": unique,
                          "sharedJarBytes": shared, "maximumAssetBytes": max(row["sizeBytes"] for row in manifest["assets"])}))
        return
    run = args.run.resolve(strict=True)
    if args.verify_shared:
        print(json.dumps({"verifiedSharedJars": verify_shared(run, rows, modes), "sharedBytes": shared}))
        return
    if args.cached_manifest or args.transport is None:
        parser.error("Staging requires the current public manifest and the exact managed transport")
    cache = args.cached_pack.resolve(strict=True) if args.cached_pack and args.cached_pack.exists() else None
    stage(run, manifest, rows, args.transport.resolve(strict=True), cache, modes)
    print(json.dumps({"verifiedFilesPerClient": len(rows), "verifiedSharedJars": verify_shared(run, rows, modes),
                      "uniqueAuthorBytes": unique, "retainedDownloadedArchives": 0}))


if __name__ == "__main__":
    main()
