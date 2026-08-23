from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v23_mario_kart_kpad.py <cemu-source-root>")

root = Path(sys.argv[1])
wpad = root / "src/input/emulated/WPADController.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V22 fixed the physical Joy-Con game-motion basis. That changed the coordinate
# frame reaching WPAD/KPAD, while V16's accVertical formula was intentionally left
# untouched. Hardware testing now confirms general Wii motion is correct but Mario
# Kart steering remains wrong.
#
# For Sideways Joy-Con motion, V22 maps the former V16 accelerometer basis A into N:
#   N.x = -A.z
#   N.y =  A.y
#   N.z =  A.x
# V16's known KPAD contract was:
#   down.x = abs(A.x + A.y)
#   down.y = -A.z
# Expressing the same physical vector in V22's new basis gives exactly:
#   down.x = abs(N.z + N.y)
#   down.y = N.x
#
# This patch therefore changes ONLY KPAD accVertical reconstruction. Raw
# accelerometer, general motion, R 180 correction, gyro, pointer, buttons and
# sticks remain exactly V22. No deadzone/smoothing is introduced yet; first restore
# the correct steering axis without reducing the user's small natural movements.
replace_once(
    wpad,
    '''\t\t// V16 restores the exact V7/upstream Cemu KPAD down contract.\n\t\t// X is the non-negative horizontal magnitude; Y retains signed roll.\n\t\t// Mario Kart consumed this exact pair correctly in the known-good builds.\n\t\tstatus.accVertical.x = std::min(1.0f, std::abs(acc.x + acc.y));\n\t\tstatus.accVertical.y = std::min(std::max(-1.0f, -acc.z), 1.0f);\n''',
    '''\t\t// V23: reconstruct the V16 KPAD down vector from V22's corrected\n\t\t// physical Sideways accelerometer basis. This is KPAD-only: raw motion\n\t\t// remains untouched for Mario Party and every other motion consumer.\n\t\t// V22 N = {-A.z, A.y, A.x}; therefore V16 down becomes:\n\t\t//   down.x = abs(N.z + N.y), down.y = N.x.\n\t\tstatus.accVertical.x = std::min(1.0f, std::abs(acc.z + acc.y));\n\t\tstatus.accVertical.y = std::min(std::max(-1.0f, acc.x), 1.0f);\n''',
    "remap KPAD down vector into V22 motion basis for Mario Kart",
)

print("Applied V23 Mario Kart KPAD basis correction only")
