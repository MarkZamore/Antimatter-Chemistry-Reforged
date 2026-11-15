"""Check that the generated preset covers the saved client bindings without overlap."""

from itertools import combinations

from build_preset import HERE, PRESET, RESERVED, UNKNOWN, layout, read_bindings, render, vanilla


def main():
    inventory = read_bindings(HERE / "registered-keys.txt")
    preset = read_bindings(PRESET)
    if preset.keys() != inventory.keys() or any(preset[name] != value for name, value in vanilla(inventory).items()):
        raise SystemExit("Coverage or vanilla controls differ from the reviewed inventory")
    if PRESET.read_bytes() != render(layout(inventory)):
        raise SystemExit("Regenerate and review the controls preset")
    bound = {name: value for name, value in preset.items() if value != UNKNOWN}
    if any(":" in key or key in RESERVED for key in bound.values()):
        raise SystemExit("The verified layout must use one plain, non-reserved key per bound action")
    for (a, ka), (b, kb) in combinations(bound.items(), 2):
        if ka == kb:
            raise SystemExit(f"Potential simultaneous conflict: {a} / {b}: {ka}")
    print(f"{len(inventory)} entries, {len(bound)} bound, {len(preset) - len(bound)} unbound, "
          f"{len(bound) * (len(bound) - 1) // 2} pairs checked, no physical key collisions")


if __name__ == "__main__":
    main()
