from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v16_restore_v7_kpad_down.py <cemu-source-root>")

root = Path(sys.argv[1])
wpad = root / "src/input/emulated/WPADController.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# Hardware testing established that Mario Kart remained broken after V11's
# signed experiment and V15's normalized-radial experiment. V5/V6/V7 were the
# last known-good game-motion builds. Restore their exact upstream Cemu KPAD
# contract: down.x is the absolute horizontal magnitude and down.y is signed
# roll. Keep all V15 sensor-basis, R Sideways, pointer, and UI changes intact.
replace_once(
    wpad,
    '''\t\t// KPAD calls this field `down`: it is a normalized 2D direction.\n\t\t// X is the non-negative horizontal radius; Y is signed wheel roll.\n\t\t// Keeping this on the correct half-plane is required by Mario Kart.\n\t\tconst float down_horizontal = std::sqrt(acc.x * acc.x + acc.y * acc.y);\n\t\tconst float down_length = std::sqrt(down_horizontal * down_horizontal + acc.z * acc.z);\n\t\tif (down_length > 0.0001f)\n\t\t{\n\t\t\tstatus.accVertical.x = std::clamp(down_horizontal / down_length, 0.0f, 1.0f);\n\t\t\tstatus.accVertical.y = std::clamp(-acc.z / down_length, -1.0f, 1.0f);\n\t\t}\n\t\telse\n\t\t{\n\t\t\tstatus.accVertical.x = 0.0f;\n\t\t\tstatus.accVertical.y = 0.0f;\n\t\t}\n''',
    '''\t\t// V16 restores the exact V7/upstream Cemu KPAD down contract.\n\t\t// X is the non-negative horizontal magnitude; Y retains signed roll.\n\t\t// Mario Kart consumed this exact pair correctly in the known-good builds.\n\t\tstatus.accVertical.x = std::min(1.0f, std::abs(acc.x + acc.y));\n\t\tstatus.accVertical.y = std::min(std::max(-1.0f, -acc.z), 1.0f);\n''',
    "restore exact V7 KPAD down values for Mario Kart",
)

print("Applied Cemu V16 exact V7 KPAD down restoration")
