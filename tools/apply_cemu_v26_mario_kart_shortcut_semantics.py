from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v26_mario_kart_shortcut_semantics.py <cemu-source-root>")

root = Path(sys.argv[1])
controller = root / "src/input/api/SDL/SDLController.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V26 deliberately leaves the hardware-approved V25-Z KPAD math untouched.
# V5 historically swapped the hotkey dispatch because the old SDL orientation
# semantics were inverted. V21/V22 later fixed the actual orientation enum/UI,
# but the old hotkey swap remained. The hardware result in Mario Kart proves it:
# pressing the hotkey labelled Vertical selects the internal Sideways state that
# gives the correct horizontal wheel. V26 fixes ONLY Mario Kart 8 shortcut dispatch.
replace_once(
    controller,
    '#include "input/api/SDL/SDLControllerProvider.h"\n',
    '#include "input/api/SDL/SDLControllerProvider.h"\n#include "Cafe/CafeSystem.h"\n',
    "include foreground title for Mario Kart-only shortcut routing",
)

replace_once(
    controller,
    '''\t\t// The internal transform enum is opposite to the physical Joy-Con\n\t\t// orientation because SDL is permanently kept in mini-gamepad mode.\n\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n''',
    '''\t\t// V26: V5's legacy hotkey swap is still required by older custom-build\n\t\t// behavior outside Mario Kart. Mario Kart 8 alone uses the now-correct\n\t\t// 1:1 shortcut semantics, so Sideways selects the exact internal Sideways\n\t\t// state that hardware-validated V25-Z at 100%. No motion math changes here.\n\t\tconst TitleId foreground_base_title = TitleIdParser::MakeBaseTitleId(CafeSystem::GetForegroundTitleId());\n\t\tconst bool v26_mario_kart_8 =\n\t\t\tforeground_base_title == 0x000500001010EB00ULL ||\n\t\t\tforeground_base_title == 0x000500001010EC00ULL ||\n\t\t\tforeground_base_title == 0x000500001010ED00ULL;\n\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(v26_mario_kart_8 ? JoyConOrientation::Vertical : JoyConOrientation::Sideways);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(v26_mario_kart_8 ? JoyConOrientation::Sideways : JoyConOrientation::Vertical);\n''',
    "make Mario Kart Sideways/Vertical hotkeys map 1:1 without changing other titles",
)

replace_once(
    controller,
    '''\t\t// Internal Vertical is the physical Sideways transform and vice versa.\n\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Sideways" : "Vertical";\n''',
    '''\t\t// V26: Mario Kart's shortcut semantics are now 1:1. Other titles retain\n\t\t// the V5 legacy presentation so their hardware-approved behavior is untouched.\n\t\tconst TitleId foreground_base_title = TitleIdParser::MakeBaseTitleId(CafeSystem::GetForegroundTitleId());\n\t\tconst bool v26_mario_kart_8 =\n\t\t\tforeground_base_title == 0x000500001010EB00ULL ||\n\t\t\tforeground_base_title == 0x000500001010EC00ULL ||\n\t\t\tforeground_base_title == 0x000500001010ED00ULL;\n\t\tconst char* mode = v26_mario_kart_8\n\t\t\t? (orientation == JoyConOrientation::Vertical ? "Vertical" : "Sideways")\n\t\t\t: (orientation == JoyConOrientation::Vertical ? "Sideways" : "Vertical");\n''',
    "show correct Mario Kart orientation name in hotkey OSD",
)

text = controller.read_text(encoding="utf-8")
required = [
    "V26: V5's legacy hotkey swap",
    "v26_mario_kart_8",
    "TitleIdParser::MakeBaseTitleId(CafeSystem::GetForegroundTitleId())",
    "v26_mario_kart_8 ? JoyConOrientation::Vertical : JoyConOrientation::Sideways",
    "v26_mario_kart_8 ? JoyConOrientation::Sideways : JoyConOrientation::Vertical",
    '? (orientation == JoyConOrientation::Vertical ? "Vertical" : "Sideways")',
]
for item in required:
    if item not in text:
        raise RuntimeError(f"V26 verification marker missing: {item}")

print("Applied Cemu V26 Mario Kart-only 1:1 Sideways/Vertical shortcut semantics")
