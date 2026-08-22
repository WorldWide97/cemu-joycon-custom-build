from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v20_r_sideways_gyro.py <cemu-source-root>")

root = Path(sys.argv[1])
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V20 is a surgical correction on top of V19/V16.
# Hardware testing confirmed Joy-Con L Sideways is correct and Joy-Con R is not.
# raw_gyro has already been reconstructed from SDL mini-gamepad coordinates into
# the physical/native Joy-Con frame. In that frame the natural horizontal grip is
# opposite for the two halves: L = RotateZ(-90), R = RotateZ(+90).
#
# Do not touch V16 accelerometer/KPAD/pointer/UI and do not alter the working L path.
replace_once(
    provider,
    '''\t\t\t\t\t\telse\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\t// User/hardware-proven Joy-Con R Sideways orientation: RotateZ(180).\n\t\t\t\t\t\t\tgame_gyro.x = -game_gyro.x;\n\t\t\t\t\t\t\tgame_gyro.y = -game_gyro.y;\n\t\t\t\t\t\t}\n''',
    '''\t\t\t\t\t\telse\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\t// V20: Joy-Con R natural Sideways physical orientation is RotateZ(+90).\n\t\t\t\t\t\t\t// L remains the already hardware-correct RotateZ(-90) path above.\n\t\t\t\t\t\t\tconst float old_x = game_gyro.x;\n\t\t\t\t\t\t\tgame_gyro.x = -game_gyro.y;\n\t\t\t\t\t\t\tgame_gyro.y = old_x;\n\t\t\t\t\t\t}\n''',
    "correct Joy-Con R Sideways gyro from 180 degrees to +90 degrees",
)

print("Applied V20 Joy-Con R Sideways gyro correction; L and all V16 behavior preserved")
