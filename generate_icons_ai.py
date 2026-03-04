#!/usr/bin/env python3
"""Batch-generate item icons from BasicItems.c5m via a HF Space API.

This script:
1) Reads every `newitem` + `spr` pair from BasicItems.c5m.
2) Uses the currently referenced icon size as the target canvas.
3) Calls the text-to-image API with an item-specific prompt.
4) Overwrites icons in-place (after creating a backup).
"""

from __future__ import annotations

import json
import random
import re
import shutil
import time
import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gradio_client import Client
from PIL import Image

ROOT = Path(__file__).resolve().parent
C5M_PATH = ROOT / "BasicItems.c5m"
DEFAULT_SPACE_ID = "Nick088/Stable-Diffusion-3-Medium-SuperPrompt"

NEGATIVE_PROMPT = (
    "stretched, squashed, cropped, cut off, blurry, low detail, "
    "anti-aliased smear, multiple objects, background scene, text, "
    "logo, watermark, frame, border"
)


@dataclass(frozen=True)
class ItemSprite:
    item_name: str
    spr_rel_path: str


ITEM_TRAITS = {
    "Demonslayer": "holy demon-slaying longsword, steel blade with bright gold holy runes",
    "Frost Bite": "enchanted icy sword, pale blue blade with frost crystals and cold mist",
    "Blazing Blade": "enchanted flaming sword, orange-red blade with ember glow",
    "Steel Dagger": "simple steel dagger, compact blade and dark leather hilt",
    "Recurve Bow": "wooden recurve bow with taut string and subtle metal tips",
    "Dragon Scale Armor": "dragon scale chest armor, layered red scales and metal trim",
    "Robe of the Archmage": "ornate archmage robe, deep blue cloth with arcane sigils",
    "Boots of the Wind": "light magical boots, feather motifs and wind swirl accents",
    "Dragon Scale Helm": "dragon scale helmet with sharp crest and metal frame",
    "Helm of Truth": "polished silver helmet with glowing eye slit and sacred engravings",
    "Staff of Restoration": "healer staff with green crystal head and gentle life aura",
    "Staff of the Lich King": "dark necromancer staff with skull top and violet aura",
    "Staff of Iron Will": "battle mage staff with iron bands and sturdy blunt head",
    "Heart of Iron": "cursed iron heart relic, heavy metal texture, faint dark pulse",
    "Frost Gauntlets": "icy gauntlets with frozen spikes and blue frost glow",
}

RING_TRAITS = {
    "Dark Prayers": "forbidden prayer ring with black silver filigree and cursed glyphs",
    "Infernal": "obsidian ring with crimson gem and flame motif",
    "Pyromancy": "fire mage ring with orange ruby and ember sparks",
    "Hydromancy": "water mage ring with blue sapphire and wave motif",
    "Storm": "storm ring with pale gem and tiny lightning arcs",
    "Geomancy": "earth ring with green gem and carved stone bands",
    "Unlife": "undead ring with bone details and sickly green glow",
    "Dark": "dark arcane ring with black gem and shadow aura",
    "Blood": "blood magic ring with deep red gem and ritual markings",
    "White": "holy white ring with pearl gem and clean light aura",
    "Spiritism": "spirit ring with cyan gem and ghostly wisps",
    "Solar": "sun ring with golden gem and radiant rays motif",
    "Serpent": "nature-serpent ring with emerald gem and vine engraving",
    "Dawn": "dawn ring with warm amber gem and sunrise motif",
    "Iron": "iron arcana ring with steel band and etched sigils",
    "Kuro": "mystic kuro ring with dark blue gem and eastern glyphs",
    "Prayers": "prayer ring with silver band and sacred rune marks",
    "Frost": "frost ring with icy gem and crystalline edges",
    "Wizardry": "wizard ring with violet gem and arcane circles",
    "Night": "night ring with indigo gem and moonlit shadow aura",
    "Necromancy": "necromancy ring with bone motifs and toxic green gem",
    "Witchery": "witchery ring with amethyst gem and occult carvings",
    "Troll": "troll magic ring, rugged band with mossy green gem",
    "Void": "void ring with dark purple gem and cosmic cracks",
    "Illusionism": "illusion ring with prismatic gem and mirage shimmer",
    "High": "high arcana ring with brilliant star gem and complex runes",
    "Moon": "moon ring with silver-blue gem and crescent symbols",
    "Silver": "silver arcana ring with bright silver band and clear runes",
    "Alchemy": "alchemy ring with brass band and transmutation symbols",
    "Gold": "gold arcana ring with polished gold band and glowing runes",
    "Astrology": "astrology ring with midnight gem and star chart engravings",
}


def parse_item_sprites(c5m_path: Path) -> list[ItemSprite]:
    item_sprites: list[ItemSprite] = []
    current_item: str | None = None

    for raw_line in c5m_path.read_text(encoding="utf-8").splitlines():
        item_match = re.match(r'^\s*newitem\s+"([^"]+)"', raw_line)
        if item_match:
            current_item = item_match.group(1)
            continue

        spr_match = re.match(r'^\s*spr\s+"([^"]+)"', raw_line)
        if spr_match and current_item:
            item_sprites.append(
                ItemSprite(item_name=current_item, spr_rel_path=spr_match.group(1))
            )
            current_item = None

    return item_sprites


def trait_for_item(item_name: str) -> str:
    if item_name in ITEM_TRAITS:
        return ITEM_TRAITS[item_name]

    if item_name.startswith("Ring of "):
        ring_core = item_name.replace("Ring of ", "", 1)
        for key in sorted(RING_TRAITS.keys(), key=len, reverse=True):
            if ring_core.startswith(key):
                return RING_TRAITS[key]
        return "enchanted magic ring with clear gemstone and readable silhouette"

    return "fantasy equipment icon with clear silhouette"


def build_prompt(item_name: str, width: int, height: int) -> str:
    trait = trait_for_item(item_name)
    return (
        f"Pixel art fantasy item icon of {item_name}, {trait}, "
        "single object only, centered, full object visible, "
        "15% transparent padding on all sides, transparent background, "
        "high contrast shading, crisp edges, no text, no watermark, no border. "
        f"Canvas: {width} x {height}."
    )


def create_backup(item_sprites: list[ItemSprite]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = ROOT / "icons" / f"_backup_ai_{timestamp}"

    copied: set[Path] = set()
    for item in item_sprites:
        src = ROOT / item.spr_rel_path
        if not src.exists() or src in copied:
            continue
        copied.add(src)
        rel_inside_icons = Path(item.spr_rel_path).relative_to("icons")
        dst = backup_root / rel_inside_icons
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return backup_root


def load_target_size(sprite_path: Path) -> tuple[int, int]:
    with Image.open(sprite_path) as image:
        return image.size


def save_image(image_path: str, out_path: Path, size: tuple[int, int]) -> None:
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        resized = rgba.resize(size, Image.Resampling.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix.lower() == ".tga":
            resized.save(out_path, format="TGA")
        else:
            resized.save(out_path, format="PNG")


def generate_image_with_space(
    client: Client, space_id: str, prompt: str, seed: int
) -> str:
    space_key = space_id.lower()

    if "nick088/stable-diffusion-3-medium-superprompt" in space_key:
        result = client.predict(
            prompt,
            False,  # enhance_prompt
            NEGATIVE_PROMPT,
            20,  # num_inference_steps
            512,  # height
            512,  # width
            6.0,  # guidance_scale
            seed,
            1,  # num_images_per_prompt
            api_name="/generate_image",
        )
        gallery, _enhanced_prompt = result
        if not gallery:
            raise RuntimeError("Generation returned no images")
        return gallery[0]["image"]

    if "manjushri/sdxl-turbo-cpu" in space_key or "manjushri-sdxl-turbo-cpu.hf.space" in space_key:
        result = client.predict(
            prompt,
            2,  # steps
            seed,
            api_name="/genie",
        )
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return result.get("path") or result.get("url")
        raise RuntimeError(f"Unexpected response from {space_id}: {type(result)}")

    raise RuntimeError(
        "Unsupported space profile. Use one of: "
        f"{DEFAULT_SPACE_ID} or Manjushri/SDXL-Turbo-CPU"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AI icons for BasicItems mod.")
    parser.add_argument(
        "--space",
        default=DEFAULT_SPACE_ID,
        help=(
            "HF Space ID or direct .hf.space URL. "
            "Supported profiles: Nick088/Stable-Diffusion-3-Medium-SuperPrompt, "
            "Manjushri/SDXL-Turbo-CPU."
        ),
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="1-based item index to start from (default: 1).",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        default=0,
        help="1-based item index to stop at (inclusive). 0 means all remaining items.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Do not create a backup folder before writing generated files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    item_sprites = parse_item_sprites(C5M_PATH)
    if not item_sprites:
        raise RuntimeError(f"No item sprites found in {C5M_PATH}")

    path_counts = Counter(x.spr_rel_path for x in item_sprites)
    dupes = {k: v for k, v in path_counts.items() if v > 1}

    print(f"Found {len(item_sprites)} item sprite entries in {C5M_PATH.name}")
    if dupes:
        print("Shared sprite paths detected:")
        for spr, count in sorted(dupes.items()):
            print(f"  - {spr} (used {count} times)")

    if not args.skip_backup:
        backup_root = create_backup(item_sprites)
        print(f"Backup created at: {backup_root}")
    else:
        print("Backup skipped (--skip-backup)")

    start_index = max(1, args.start_index)
    end_index = args.end_index if args.end_index > 0 else len(item_sprites)
    if end_index < start_index:
        raise RuntimeError("--end-index cannot be less than --start-index")
    selected = item_sprites[start_index - 1 : end_index]
    if not selected:
        raise RuntimeError("No items selected for generation (check start/end indices)")

    client = Client(args.space)
    print(f"Using generator space: {args.space}")
    print(f"Generating items {start_index}..{start_index + len(selected) - 1} of {len(item_sprites)}")

    log_entries: list[dict[str, object]] = []
    total = len(selected)

    for local_idx, item in enumerate(selected, start=1):
        idx = start_index + local_idx - 1
        out_path = ROOT / item.spr_rel_path
        width, height = load_target_size(out_path)
        prompt = build_prompt(item.item_name, width, height)

        print(
            f"[{local_idx:02d}/{total}] #{idx:02d} {item.item_name} -> "
            f"{item.spr_rel_path} ({width}x{height})"
        )

        success = False
        last_error: str | None = None
        for attempt in range(1, 6):
            seed = random.randint(0, 2_147_483_647)
            try:
                generated_path = generate_image_with_space(
                    client=client,
                    space_id=args.space,
                    prompt=prompt,
                    seed=seed,
                )
                if not generated_path:
                    raise RuntimeError("Generation returned an empty image path")
                save_image(generated_path, out_path, (width, height))

                log_entries.append(
                    {
                        "index": idx,
                        "item": item.item_name,
                        "spr": item.spr_rel_path,
                        "size": [width, height],
                        "seed": seed,
                        "attempt": attempt,
                        "prompt": prompt,
                        "negative_prompt": NEGATIVE_PROMPT,
                        "space": args.space,
                        "generated_path": generated_path,
                    }
                )
                print("  saved")
                success = True
                break
            except Exception as exc:  # noqa: BLE001 - keep retry flow simple
                last_error = str(exc)
                wait_s = min(20, 3 * attempt)
                print(f"  attempt {attempt} failed: {last_error}")
                if attempt < 5:
                    time.sleep(wait_s)

        if not success:
            raise RuntimeError(
                f"Failed to generate {item.item_name} ({item.spr_rel_path}): {last_error}"
            )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = ROOT / "icons" / f"_ai_generation_log_{timestamp}.json"
    log_path.write_text(json.dumps(log_entries, indent=2), encoding="utf-8")
    print(f"Done. Log written to: {log_path}")


if __name__ == "__main__":
    main()
