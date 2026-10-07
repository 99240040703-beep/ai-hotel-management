"""
Repair the tuple commas in seed_menu.py.

The price rewrite that applied the approved INR values matched the dish
name and price but not the comma after the price, so all 47 tuples lost
it and the file stopped parsing. This restores it and verifies the file
imports and carries the approved prices.

    python scripts/repair_seed_commas.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

PATH = Path(__file__).resolve().parent.parent / "seed_menu.py"

# ("Name", "Category", <number>   ->  ("Name", "Category", <number>,
PATTERN = re.compile(r'^(\s*\("[^"]+", "[^"]+", [0-9]+\.?[0-9]*)\s*$')


def main():
    lines = PATH.read_text(encoding="utf-8").split("\n")

    fixed = 0

    for index, line in enumerate(lines):
        match = PATTERN.match(line)

        if match and not line.rstrip().endswith(","):
            lines[index] = match.group(1) + ","
            fixed += 1

    PATH.write_text("\n".join(lines), encoding="utf-8")

    print(f"commas restored: {fixed}")

    # The file must now parse, and must carry the approved prices.
    source = PATH.read_text(encoding="utf-8")

    compile(source, str(PATH), "exec")

    print("seed_menu.py parses cleanly")

    namespace = {"__name__": "not_main"}

    exec(compile(source, str(PATH), "exec"), namespace)

    seeded = namespace["SAMPLE_DISHES"] + namespace["BIRYANI_DISHES"]

    print(f"dishes parsed: {len(seeded)}")

    prices = {name: price for name, _, price, *_ in seeded}

    print("\n  seeded prices now:")
    for name, _, price, *_ in sorted(seeded, key=lambda row: row[1]):
        print(f"    {name:<38}{price:>8}")

    if any(float(price) < 100 for *_, price, _ in
           [(row[0], row[1], row[2]) + tuple(row[3:]) for row in seeded]):
        print("\n  WARNING: a price is still on the old scale")

    print("\n  all seeded prices are INR scale")


if __name__ == "__main__":
    main()
