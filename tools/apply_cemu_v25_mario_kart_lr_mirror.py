from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: apply_cemu_v25_mario_kart_lr_mirror.py <cemu-source-root> <X|Z>")

root = Path(sys.argv[1])
variant = sys.argv[2].strip().upper()
if variant not in {"X", "Z"}:
    raise SystemExit("variant must be X or Z")

wpad = root / "src/input/emulated/WPADController.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


replace_once(
    wpad,
    '#include <api/Controller.h>\n#include "input/emulated/WPADController.h"\n',
    '#include <api/Controller.h>\n#include "input/emulated/WPADController.h"\n#include "Cafe/CafeSystem.h"\n',
    "include foreground title id for Mario Kart-only KPAD routing",
)

mirror = (
    '\t\t\t// V25-X: single-axis steering mirror after the proven V24-A plane transform.\n'
    '\t\t\tacc.x = -acc.x;\n'
    if variant == "X" else
    '\t\t\t// V25-Z: single-axis steering mirror after the proven V24-A plane transform.\n'
    '\t\t\tacc.z = -acc.z;\n'
)
marker = f"V25-{variant}: single-axis steering mirror"

old = '''\t\tglm::vec3 acc;\n\t\tmotion_sample.getAccelerometer(&acc[0]);\n\t\tstatus.acc.x = acc.x;\n\t\tstatus.acc.y = acc.y;\n\t\tstatus.acc.z = acc.z;\n'''

new = '''\t\tglm::vec3 acc;\n\t\tmotion_sample.getAccelerometer(&acc[0]);\n\n\t\t// V25 is deliberately restricted to Mario Kart 8 + emulated Wiimote +\n\t\t// MotionPlus OFF + an SDL Joy-Con source. V22 remains untouched for every\n\t\t// other title and every non-KPAD motion consumer.\n\t\tconst uint64 foreground_title = CafeSystem::GetForegroundTitleId();\n\t\tconst bool is_mario_kart_8 =\n\t\t\tforeground_title == 0x000500001010EB00ULL ||\n\t\t\tforeground_title == 0x000500001010EC00ULL ||\n\t\t\tforeground_title == 0x000500001010ED00ULL;\n\n\t\tbool joycon_left = false;\n\t\tbool joycon_right = false;\n\t\tfor (const auto& source_controller : get_controllers())\n\t\t{\n\t\t\tif (!source_controller)\n\t\t\t\tcontinue;\n\t\t\tconst auto& source_name = source_controller->display_name();\n\t\t\tif (source_name.find("Joy-Con") == std::string::npos)\n\t\t\t\tcontinue;\n\t\t\tjoycon_left |= source_name.find("(L)") != std::string::npos;\n\t\t\tjoycon_right |= source_name.find("(R)") != std::string::npos;\n\t\t}\n\n\t\tif (type() == Wiimote && !is_mpls_attached() && is_mario_kart_8 && (joycon_left || joycon_right))\n\t\t{\n\t\t\t// Hardware result: on the Vertical->horizontal-wheel route, Joy-Con L\n\t\t\t// reaches the same physical basis as R only after a 180-degree turn.\n\t\t\t// Reproduce that turn inside Mario Kart KPAD only.\n\t\t\tif (joycon_left && !joycon_right)\n\t\t\t{\n\t\t\t\tacc.x = -acc.x;\n\t\t\t\tacc.z = -acc.z;\n\t\t\t}\n\n\t\t\t// Reproduce V24-A's hardware-proven plane conversion: +90 around KPAD Y.\n\t\t\tconst float pre_quarter_x = acc.x;\n\t\t\tacc.x = acc.z;\n\t\t\tacc.z = -pre_quarter_x;\n''' + mirror + '''\t\t}\n\n\t\tstatus.acc.x = acc.x;\n\t\tstatus.acc.y = acc.y;\n\t\tstatus.acc.z = acc.z;\n'''

replace_once(
    wpad,
    old,
    new,
    f"apply V25-{variant} Mario Kart L/R normalization and single-axis mirror",
)

text = wpad.read_text(encoding="utf-8")
required = [
    marker,
    'source_name.find("Joy-Con")',
    'source_name.find("(L)")',
    'source_name.find("(R)")',
    'if (joycon_left && !joycon_right)',
    'acc.x = -acc.x;',
    'acc.z = -acc.z;',
    'const float pre_quarter_x = acc.x;',
    'acc.x = acc.z;',
    'acc.z = -pre_quarter_x;',
    'type() == Wiimote && !is_mpls_attached() && is_mario_kart_8',
    'status.accVertical.x = std::min(1.0f, std::abs(acc.x + acc.y));',
    'status.accVertical.y = std::min(std::max(-1.0f, -acc.z), 1.0f);',
]
for item in required:
    if item not in text:
        raise RuntimeError(f"V25 verification marker missing: {item}")

print(f"Applied Cemu V25-{variant}: Mario Kart Joy-Con L/R normalization + one-axis steering mirror")
