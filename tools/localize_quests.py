"""Build the locale overlay from the official export and reviewed Russian text.

Use extract for translators. Reuse carries forward translations by exact
source text and reports the new text that still needs translation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile


PACK = Path(__file__).resolve().parents[1]
QUEST_ROOT = "config/ftbquests/quests/"
LANG_ROOT = "kubejs/assets/reforged_quests/lang/"
NAMESPACE = "lanminecraft.reforged.quests"
GROUPS = QUEST_ROOT + "chapter_groups.snbt"
BOOK_DATA = QUEST_ROOT + "data.snbt"
QUOTED = r'"(?:[^"\\]|\\.)*"'
STRING = re.compile(QUOTED)
FIELDS = re.compile(
    rf'(?m)(?:^[ \t]*|(?<=, ))(?:title|subtitle|description):[ \t]*'
    rf'(?P<values>{QUOTED}|\[\s*(?:{QUOTED}\s*,?\s*)*\])'
)
FORMAT = re.compile(r"(?<!\\)[&§][0-9a-fk-or]", re.IGNORECASE)
URL = re.compile(r"https?://[^\s\"<>]+")


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def fingerprint(data):
    return {"sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def quest_sources(archive):
    with ZipFile(archive) as client:
        members = {}
        for path in client.namelist():
            if path in ("overrides/" + GROUPS, "overrides/" + BOOK_DATA) or re.fullmatch(
                r"overrides/config/ftbquests/quests/chapters/[a-z0-9_.-]+\.snbt", path
            ):
                name = path.removeprefix("overrides/")
                if name in members:
                    raise ValueError(f"Duplicate quest file: {name}")
                members[name] = client.read(path)
        if GROUPS not in members or BOOK_DATA not in members or len(members) < 3:
            raise ValueError("Expected book data, chapter groups and quest chapters in the official client ZIP")
    return dict(sorted(members.items()))


def text_tokens(source):
    for field in FIELDS.finditer(source):
        for quoted in STRING.finditer(source, *field.span("values")):
            value = json.loads(quoted.group())
            if value:
                yield quoted.start(), quoted.end(), value


def text_key(path, english):
    chapter = Path(path).stem
    digest = hashlib.sha256(english.encode()).hexdigest()[:20]
    return f"{NAMESPACE}.{chapter}.{digest}"


def is_component(text):
    return text.startswith('{"')


def label(text):
    return json.loads(text)["text"] if is_component(text) else text


def lang_value(english, text):
    if is_component(english):
        return label(text)
    # Legacy FTB markup expands language entries through I18n, which uses String.format.
    return text.replace("%", "%%")


def localized_component(english, key):
    component = json.loads(english)
    component["fallback"] = component.pop("text")
    component["translate"] = key
    return json.dumps(component, ensure_ascii=False, separators=(",", ":"))


def rewrite(path, data, translations, en_us, ru_ru):
    source = data.decode("utf-8")
    pieces = []
    cursor = 0
    count = 0
    for start, end, english in text_tokens(source):
        russian = translations[english]
        if not isinstance(russian, str) or not russian.strip():
            raise ValueError(f"Empty or invalid Russian text in {path}: {english}")
        if is_component(english):
            source_component = json.loads(english)
            translated_component = json.loads(russian)
            if {**translated_component, "text": source_component["text"]} != source_component:
                raise ValueError(f"Changed link or formatting in {path}: {english}")
        if FORMAT.findall(english) != FORMAT.findall(russian) or URL.findall(english) != URL.findall(russian):
            raise ValueError(f"Changed color codes or URL in {path}: {english}")
        key = text_key(path, english)
        original_value = lang_value(english, english)
        if key in en_us and en_us[key] != original_value:
            raise ValueError(f"Translation key collision: {key}")
        en_us[key] = original_value
        ru_ru[key] = lang_value(english, russian)
        replacement = localized_component(english, key) if is_component(english) else "{" + key + "}"
        pieces.extend((source[cursor:start], json.dumps(replacement, ensure_ascii=False)))
        cursor = end
        count += 1
    pieces.append(source[cursor:])
    if not count:
        raise ValueError(f"No quest text found in {path}")
    return "".join(pieces).encode(), count


def source_strings(members, output, existing=None):
    output.mkdir(parents=True, exist_ok=False)
    missing_count = 0
    for path, data in members.items():
        if path == BOOK_DATA:
            continue
        texts = dict.fromkeys(value for _, _, value in text_tokens(data.decode()))
        stem = Path(path).stem
        if existing is None:
            (output / (stem + ".json")).write_bytes(
                (json.dumps(list(texts), ensure_ascii=False, indent=2) + "\n").encode()
            )
            continue
        translated = {}
        missing = []
        for value in texts:
            key = text_key(path, value)
            if key not in existing:
                missing.append(value)
            elif is_component(value):
                translated[value] = json.dumps({**json.loads(value), "text": existing[key]}, ensure_ascii=False)
            else:
                translated[value] = existing[key].replace("%%", "%")
        (output / (stem + ".json")).write_bytes(json_bytes(translated))
        if missing:
            (output / (stem + ".missing.json")).write_bytes(
                (json.dumps(missing, ensure_ascii=False, indent=2) + "\n").encode()
            )
            missing_count += len(missing)
    if existing is not None:
        print(f"{missing_count} new or changed strings require translation")


def build(members, archive, tables):
    lock_path = PACK / "tools/upstream-lock.json"
    recipe_path = PACK / "tools/overlay.json"
    lock = json.loads(lock_path.read_bytes())
    recipe = json.loads(recipe_path.read_bytes())
    if fingerprint(archive.read_bytes()) != {
        k: lock["client"][k] for k in ("sizeBytes", "sha256")
    } or recipe["authorArchiveSha256"] != lock["client"]["sha256"]:
        raise ValueError("Use the author archive bound to the complete lock and overlay recipe")
    expected = {row["path"]: row for row in lock["overrides"] if row["path"].startswith(QUEST_ROOT)}
    if set(members) != set(expected):
        raise ValueError("Quest inventory differs from the author lock or has unsupported new files")
    source_pins = {path: fingerprint(data) for path, data in members.items()}
    for path, pin in source_pins.items():
        if any(expected[path][key] != value for key, value in pin.items()):
            raise ValueError(f"Source quest differs from the author lock: {path}")

    en_us, ru_ru, outputs = {}, {}, {}
    fields = 0
    for path, data in members.items():
        if path == BOOK_DATA:
            # The book title is a proper name shared by both languages.
            continue
        table = json.loads((tables / (Path(path).stem + ".json")).read_bytes())
        required = {value for _, _, value in text_tokens(data.decode("utf-8"))}
        if set(table) != required:
            raise ValueError(f"{path}: {len(required - table.keys())} missing, {len(table.keys() - required)} extra translations")
        rewritten, count = rewrite(path, data, table, en_us, ru_ru)
        fields += count
        outputs[path] = rewritten

    output_rows = [{
        "path": path, "before": source_pins[path], "inputs": {path: source_pins[path]}, "output": fingerprint(data)
    } for path, data in outputs.items()]
    library_inputs = {
        row["path"]: {key: row[key] for key in ("sizeBytes", "sha256", "fileId", "projectId")}
        for row in lock["files"] if re.fullmatch(r"mods/ftb-(?:quests|library)-forge-.*\.jar", row["path"])
    }
    if len(library_inputs) != 2:
        raise ValueError("Expected one pinned FTB Quests and one FTB Library JAR")
    for locale, translations in (("en_us", en_us), ("ru_ru", ru_ru)):
        path = LANG_ROOT + locale + ".json"
        if any(row["path"] == path for row in lock["overrides"]):
            raise ValueError(f"The author now ships our localization path: {path}")
        data = json_bytes(translations)
        outputs[path] = data
        output_rows.append({"path": path, "inputs": source_pins | library_inputs, "output": fingerprint(data)})

    previous = {row["path"] for row in recipe.get("bookLocalization", [])}
    owner_path = PACK / "launcher/pack-owned.txt"
    owned = set(owner_path.read_text(encoding="utf-8").splitlines()) - previous
    owned_bytes = ("\n".join(sorted(owned | outputs.keys())) + "\n").encode()
    recipe["bookLocalization"] = output_rows
    recipe_data = json_bytes(recipe)
    lock["overlay"].update(
        bookLocalization=output_rows,
        ownership=fingerprint(owned_bytes),
        recipeSha256=fingerprint(recipe_data)["sha256"],
    )
    for path, data in outputs.items():
        target = PACK / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    owner_path.write_bytes(owned_bytes)
    recipe_path.write_bytes(recipe_data)
    lock_path.write_bytes(json_bytes(lock))
    print(f"{len(members) - 2} chapters, {fields} text fields, {len(ru_ru)} Russian locale entries")


def verify_inventory(members):
    recipe = json.loads((PACK / "tools/overlay.json").read_bytes())
    rows = {row["path"]: row for row in recipe["bookLocalization"]}
    sources = {path: fingerprint(data) for path, data in members.items()}
    locale_inputs = rows[LANG_ROOT + "ru_ru.json"]["inputs"]
    pinned = {path: pin for path, pin in locale_inputs.items() if path.startswith(QUEST_ROOT)}
    if pinned != sources:
        raise ValueError("Translate the added or changed author quest files before publication")
    expected = {text_key(path, value) for path, data in members.items() if path != BOOK_DATA
                for _, _, value in text_tokens(data.decode())}
    for locale in ("en_us", "ru_ru"):
        data = (PACK / LANG_ROOT / (locale + ".json")).read_bytes()
        if json.loads(data).keys() != expected:
            raise ValueError(f"{locale} coverage differs from the official source text")
    print(f"Verified localization of {len(members) - 2} chapters and {len(expected)} unique keys")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("extract", "reuse", "build", "verify"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("tables", type=Path, nargs="?")
    args = parser.parse_args()
    members = quest_sources(args.archive)
    if args.action == "verify":
        verify_inventory(members)
    elif args.tables is None:
        parser.error("Provide a translation table directory")
    elif args.action == "build":
        build(members, args.archive, args.tables)
    else:
        existing = json.loads((PACK / LANG_ROOT / "ru_ru.json").read_bytes()) if args.action == "reuse" else None
        source_strings(members, args.tables, existing)


if __name__ == "__main__":
    main()
