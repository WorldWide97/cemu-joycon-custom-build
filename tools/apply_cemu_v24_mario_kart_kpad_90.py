from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: apply_cemu_v24_mario_kart_kpad_90.py <cemu-source-root> <A|B>")

root = Path(sys.argv[1])
variant = sys.argv[2].strip().upper()
if variant not in {"A", "B"}:
    raise SystemExit("variant must be A or B")

wpad = root / "src/input/emulated/WPADController.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V24 is deliberately isolated to KPAD/Wii Remote delivery for Mario Kart 8.
# The V22 motion provider, Joy-Con Sideways/Vertical basis, Joy-Con R 180 fix,
# game gyro, pointer, buttons and sticks are untouched.
replace_once(
    wpad,
    '#include <api/Controller.h>\n#include "input/emulated/WPADController.h"\n',
    '#include <api/Controller.h>\n#include "input/emulated/WPADController.h"\n#include "Cafe/CafeSystem.h"\n',
    "include current foreground title id for Mario Kart-only KPAD routing",
)

if variant == "A":
    transform = '''\t\t\t// V24-A: Mario Kart 8 Wii Wheel only, MotionPlus OFF.\n\t\t\t// Quarter-turn +90 degrees around KPAD Y: X'=Z, Y'=Y, Z'=-X.\n\t\t\tconst float old_x = acc.x;\n\t\t\tacc.x = acc.z;\n\t\t\tacc.z = -old_x;\n'''
    marker = "V24-A: Mario Kart 8 Wii Wheel only, MotionPlus OFF."
else:
    transform = '''\t\t\t// V24-B: Mario Kart 8 Wii Wheel only, MotionPlus OFF.\n\t\t\t// Quarter-turn -90 degrees around KPAD Y: X'=-Z, Y'=Y, Z'=X.\n\t\t\tconst float old_x = acc.x;\n\t\t\tacc.x = -acc.z;\n\t\t\tacc.z = old_x;\n'''
    marker = "V24-B: Mario Kart 8 Wii Wheel only, MotionPlus OFF."

old = '''\t\tglm::vec3 acc;\n\t\tmotion_sample.getAccelerometer(&acc[0]);\n\t\tstatus.acc.x = acc.x;\n\t\tstatus.acc.y = acc.y;\n\t\tstatus.acc.z = acc.z;\n'''

new = '''\t\tglm::vec3 acc;\n\t\tmotion_sample.getAccelerometer(&acc[0]);\n\n\t\t// Mario Kart 8 is the only title that receives this KPAD-only correction.\n\t\t// JP/USA/EUR base Title IDs are covered. MotionPlus must be OFF because\n\t\t// Mario Kart 8's Wii Remote path is the core accelerometer Wii Wheel path.\n\t\tconst uint64 foreground_title = CafeSystem::GetForegroundTitleId();\n\t\tconst bool is_mario_kart_8 =\n\t\t\tforeground_title == 0x000500001010EB00ULL ||\n\t\t\tforeground_title == 0x000500001010EC00ULL ||\n\t\t\tforeground_title == 0x000500001010ED00ULL;\n\t\tif (type() == Wiimote && !is_mpls_attached() && is_mario_kart_8)\n\t\t{\n''' + transform + '''\t\t}\n\n\t\tstatus.acc.x = acc.x;\n\t\tstatus.acc.y = acc.y;\n\t\tstatus.acc.z = acc.z;\n'''

replace_once(
    wpad,
    old,
    new,
    f"apply {variant} Mario Kart 8 KPAD-only 90-degree accelerometer quarter-turn",
)

# Keep V16's KPAD down contract, but feed it the same rotated Mario Kart-only
# vector so every accelerometer-facing KPAD field remains internally consistent.
text = wpad.read_text(encoding="utf-8")
required = [
    marker,
    "status.accVertical.x = std::min(1.0f, std::abs(acc.x + acc.y));",
    "status.accVertical.y = std::min(std::max(-1.0f, -acc.z), 1.0f);",
    "foreground_title == 0x000500001010EB00ULL",
    "foreground_title == 0x000500001010EC00ULL",
    "foreground_title == 0x000500001010ED00ULL",
    "type() == Wiimote && !is_mpls_attached() && is_mario_kart_8",
]
for item in required:
    if item not in text:
        raise RuntimeError(f"V24 verification marker missing: {item}")

print(f"Applied Cemu V24-{variant} Mario Kart 8 KPAD-only 90-degree quarter-turn")
