from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v26_mario_kart_sideways_route.py <cemu-source-root>")

root = Path(sys.argv[1])
wpad = root / "src/input/emulated/WPADController.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V26 is applied AFTER the hardware-approved V25-Z patch. It does not change
# V25-Z's L/R normalization, +90 plane transform, or Z steering mirror. It only
# detects the selected Joy-Con orientation and, when Sideways is selected in
# Mario Kart 8, converts V22's Sideways accelerometer basis into the exact V22
# Vertical basis that V25-Z was hardware-tested against.
replace_once(
    wpad,
    '#include "Cafe/CafeSystem.h"\n',
    '#include "Cafe/CafeSystem.h"\n#include "input/api/SDL/SDLController.h"\n',
    "include SDL Joy-Con orientation accessor",
)

old_detect = '''\t\tbool joycon_left = false;\n\t\tbool joycon_right = false;\n\t\tfor (const auto& source_controller : get_controllers())\n\t\t{\n\t\t\tif (!source_controller)\n\t\t\t\tcontinue;\n\t\t\tconst auto& source_name = source_controller->display_name();\n\t\t\tif (source_name.find("Joy-Con") == std::string::npos)\n\t\t\t\tcontinue;\n\t\t\tjoycon_left |= source_name.find("(L)") != std::string::npos;\n\t\t\tjoycon_right |= source_name.find("(R)") != std::string::npos;\n\t\t}\n'''

new_detect = '''\t\tbool joycon_left = false;\n\t\tbool joycon_right = false;\n\t\tbool joycon_sideways = false;\n\t\tbool joycon_vertical = false;\n\t\tfor (const auto& source_controller : get_controllers())\n\t\t{\n\t\t\tif (!source_controller)\n\t\t\t\tcontinue;\n\t\t\tconst auto sdl_joycon = std::dynamic_pointer_cast<SDLController>(source_controller);\n\t\t\tif (!sdl_joycon || !sdl_joycon->is_joycon())\n\t\t\t\tcontinue;\n\t\t\tjoycon_left |= sdl_joycon->is_left_joycon();\n\t\t\tjoycon_right |= sdl_joycon->is_right_joycon();\n\t\t\tif (sdl_joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Sideways)\n\t\t\t\tjoycon_sideways = true;\n\t\t\telse\n\t\t\t\tjoycon_vertical = true;\n\t\t}\n'''
replace_once(wpad, old_detect, new_detect, "detect exact Joy-Con L/R and selected orientation")

old_scope = '''\t\tif (type() == Wiimote && !is_mpls_attached() && is_mario_kart_8 && (joycon_left || joycon_right))\n\t\t{\n\t\t\t// Hardware result: on the Vertical->horizontal-wheel route, Joy-Con L\n'''

new_scope = '''\t\tif (type() == Wiimote && !is_mpls_attached() && is_mario_kart_8 && (joycon_left || joycon_right))\n\t\t{\n\t\t\t// V26: V25-Z is hardware-approved when the controller setting is Vertical.\n\t\t\t// If Sideways is selected, first convert V22 Sideways into that exact\n\t\t\t// Vertical accelerometer basis. L and R need opposite quarter-turn signs.\n\t\t\t// Vertical itself is deliberately untouched so the proven V25-Z route\n\t\t\t// remains bit-for-bit equivalent from this point onward.\n\t\t\tif (joycon_sideways && !joycon_vertical)\n\t\t\t{\n\t\t\t\tconst float pre_v26_x = acc.x;\n\t\t\t\tif (joycon_left && !joycon_right)\n\t\t\t\t{\n\t\t\t\t\t// L: V22 Sideways -> V22 Vertical = +90 around KPAD Y.\n\t\t\t\t\tacc.x = acc.z;\n\t\t\t\t\tacc.z = -pre_v26_x;\n\t\t\t\t}\n\t\t\t\telse if (joycon_right && !joycon_left)\n\t\t\t\t{\n\t\t\t\t\t// R: V22 Sideways -> V22 Vertical = -90 around KPAD Y.\n\t\t\t\t\tacc.x = -acc.z;\n\t\t\t\t\tacc.z = pre_v26_x;\n\t\t\t\t}\n\t\t\t}\n\n\t\t\t// Hardware result: on the Vertical->horizontal-wheel route, Joy-Con L\n'''
replace_once(wpad, old_scope, new_scope, "route Sideways through the proven V25-Z Vertical input basis")

text = wpad.read_text(encoding="utf-8")
required = [
    'V26: V25-Z is hardware-approved when the controller setting is Vertical.',
    'std::dynamic_pointer_cast<SDLController>(source_controller)',
    'SDLController::JoyConOrientation::Sideways',
    'if (joycon_sideways && !joycon_vertical)',
    '// L: V22 Sideways -> V22 Vertical = +90 around KPAD Y.',
    '// R: V22 Sideways -> V22 Vertical = -90 around KPAD Y.',
    'V25-Z: single-axis steering mirror',
    'acc.z = -acc.z;',
    'type() == Wiimote && !is_mpls_attached() && is_mario_kart_8',
]
for item in required:
    if item not in text:
        raise RuntimeError(f"V26 verification marker missing: {item}")

print("Applied Cemu V26: Mario Kart Sideways routes into hardware-approved V25-Z basis")
