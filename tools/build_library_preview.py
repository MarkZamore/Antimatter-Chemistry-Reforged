"""Build the library preview from the pack author's pinned CurseForge gallery image."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, __version__ as pillow_version


PROJECT = "https://www.curseforge.com/minecraft/modpacks/antimatter-chemistry-reforged"
SOURCE_URL = "https://media.forgecdn.net/attachments/2122/566/be9rdblnwcnfpbld6t8lvmx3k6dhwddblizugjiz-png.png"
SOURCE_SHA256 = "ad8ddf2a568c1df8133a31c964320e5b33feba5e9fc6ceff440aa579747e072a"
SOURCE_BYTES = 238683
OUTPUT_SIZE = (1280, 720)


def fingerprint(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data)}


def build(pack_source, check):
    lock = json.loads((pack_source / "tools/upstream-client-lock.json").read_bytes())
    client = lock["client"]
    if (client["projectId"], client["fileId"]) != (1771794, 9558909):
        raise ValueError("Review the author gallery against the new pack version")
    request = Request(SOURCE_URL, headers={"User-Agent": "LANMinecraft library preview"})
    with urlopen(request, timeout=15) as response:
        if response.geturl() != SOURCE_URL:
            raise ValueError("The pinned gallery image URL redirected")
        data = response.read(SOURCE_BYTES + 1)
    source_fingerprint = fingerprint(data)
    if source_fingerprint != {"sha256": SOURCE_SHA256, "sizeBytes": SOURCE_BYTES}:
        raise ValueError("The gallery image differs from the recorded author upload")

    output = io.BytesIO()
    with Image.open(io.BytesIO(data)) as source:
        if source.format != "PNG" or source.size != (1920, 1009):
            raise ValueError("The gallery image format or dimensions changed")
        preview = ImageOps.fit(source.convert("RGB"), OUTPUT_SIZE, Image.Resampling.LANCZOS)
        preview.save(output, "JPEG", quality=92, subsampling=0, optimize=True)
    image = output.getvalue()
    receipt = {
        "schemaVersion": 1,
        "author": "big_energy",
        "projectUrl": PROJECT,
        "fileUrl": f"{PROJECT}/files/{client['fileId']}",
        "authorArchiveSha256": client["sha256"],
        "source": {
            "galleryUrl": f"{PROJECT}/gallery",
            "imageUrl": SOURCE_URL,
            "width": 1920,
            "height": 1009,
            **source_fingerprint,
        },
        "preview": {"width": OUTPUT_SIZE[0], "height": OUTPUT_SIZE[1], **fingerprint(image)},
        "transformation": {
            "format": "JPEG",
            "method": "center crop and Lanczos resize",
            "optimize": True,
            "pillowVersion": pillow_version,
            "quality": 92,
            "subsampling": 0,
        },
    }
    files = {
        "preview.jpg": image,
        "preview-source.json": (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    for name, content in files.items():
        path = pack_source / "library" / name
        if check:
            if path.read_bytes() != content:
                raise ValueError(f"{name} differs from the generated preview")
        else:
            path.write_bytes(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check both tracked outputs without rewriting them")
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.check)
