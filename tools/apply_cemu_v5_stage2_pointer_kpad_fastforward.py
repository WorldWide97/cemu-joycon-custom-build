from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v5_stage2_pointer_kpad_fastforward.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# Stage 1 already added update_joycon_pointer() and corrected orientation/motion.
# Use narrow anchors here so minor whitespace in upstream KPAD code cannot break V5.
wpad_cpp = root / "src/input/emulated/WPADController.cpp"

# KPAD: preserve Cemu's native positional source path. Only replace the no-position
# fallback with our Joy-Con gyro pointer fallback.
replace_once(
    wpad_cpp,
    '''\telse\n\t\tstatus.dpd_valid_fg = 0;\n\n\tswitch (type())\n''',
    '''\telse\n\t{\n\t\tglm::vec2 position{}, previous{};\n\t\tif (update_joycon_pointer(position, previous))\n\t\t{\n\t\t\tstatus.dpd_valid_fg = 2;\n\t\t\tconst auto pos = (position * 2.0f) - 1.0f;\n\t\t\tstatus.pos.x = pos.x;\n\t\t\tstatus.pos.y = pos.y;\n\t\t\tconst auto delta = position - previous;\n\t\t\tstatus.vec.x = delta.x;\n\t\t\tstatus.vec.y = delta.y;\n\t\t\tstatus.speed = glm::length(delta);\n\t\t}\n\t\telse\n\t\t\tstatus.dpd_valid_fg = 0;\n\t}\n\n\tswitch (type())\n''',
    "route Joy-Con gyro pointer into KPAD fallback",
)

# Raw WPADRead: synthesize sensor-bar DPD dots from the same gyro pointer.
replace_once(
    wpad_cpp,
    '''\t// todo fill position api from wiimote\n\n\tswitch (m_data_format)\n''',
    '''\t// Joy-Con has no physical IR camera, so synthesize two sensor-bar dots\n\t// around the gyro pointer for games that read raw WPAD DPD objects.\n\tglm::vec2 joycon_pointer{}, joycon_pointer_prev{};\n\tconst bool has_joycon_pointer = update_joycon_pointer(joycon_pointer, joycon_pointer_prev);\n\n\tswitch (m_data_format)\n''',
    "prepare raw WPAD Joy-Con pointer",
)

replace_once(
    wpad_cpp,
    '''\tstatus->dev = get_device_type();\n\tstatus->err = WPAD_ERR_NONE;\n}\n\nvoid WPADController::KPADRead''',
    '''\tif (has_joycon_pointer)\n\t{\n\t\tfor (auto& object : status->obj)\n\t\t{\n\t\t\tobject.x = 0x03FF;\n\t\t\tobject.y = 0x03FF;\n\t\t\tobject.size = 0;\n\t\t\tobject.traceId = 0xFF;\n\t\t}\n\n\t\tconst int center_x = std::clamp((int)std::lround(joycon_pointer.x * 1023.0f), 0, 1023);\n\t\tconst int center_y = std::clamp((int)std::lround(joycon_pointer.y * 767.0f), 0, 767);\n\t\tconstexpr int half_bar_width = 36;\n\t\tstatus->obj[0].x = (uint16)std::clamp(center_x - half_bar_width, 0, 1023);\n\t\tstatus->obj[0].y = (uint16)center_y;\n\t\tstatus->obj[0].size = 8;\n\t\tstatus->obj[0].traceId = 0;\n\t\tstatus->obj[1].x = (uint16)std::clamp(center_x + half_bar_width, 0, 1023);\n\t\tstatus->obj[1].y = (uint16)center_y;\n\t\tstatus->obj[1].size = 8;\n\t\tstatus->obj[1].traceId = 1;\n\t}\n\n\tstatus->dev = get_device_type();\n\tstatus->err = WPAD_ERR_NONE;\n}\n\nvoid WPADController::KPADRead''',
    "emit raw WPAD DPD objects from Joy-Con pointer",
)


# Frame-driven fast-forward: Cemu's CPU TimerShiftFactor alone does not make
# games paced by virtual GX2/Latte VSync visibly advance faster.
latte = root / "src/Cafe/HW/Latte/Core/LatteTiming.cpp"
replace_once(
    latte,
    '''#include "config/CemuConfig.h"\n#include "Cafe/CafeSystem.h"\n''',
    '''#include "config/CemuConfig.h"\n#include "config/ActiveSettings.h"\n#include "Cafe/CafeSystem.h"\n''',
    "include timer speed for virtual VSync",
)

replace_once(
    latte,
    '''\treturn tick;\n}\n\nvoid LatteTiming_setCustomVsyncFrequency''',
    '''\tconst uint8 timerShift = ActiveSettings::GetTimerShiftFactor();\n\tif (timerShift < 3)\n\t\ttick >>= (3 - timerShift);\n\telse if (timerShift > 3)\n\t\ttick <<= (timerShift - 3);\n\treturn std::max<HRTick>(tick, (HRTick)1);\n}\n\nvoid LatteTiming_setCustomVsyncFrequency''',
    "scale virtual VSync with timer speed",
)

replace_once(
    latte,
    '''\tif (elapsedPeriods >= 10)\n\t{\n\t\ts_lastHostVsync = nowTimePoint;\n\t}\n\telse\n\t\ts_lastHostVsync += vsyncPeriod;\n\n\tLatteTiming_signalVsync();\n}\n''',
    '''\tif (elapsedPeriods >= 10)\n\t{\n\t\ts_lastHostVsync = nowTimePoint;\n\t}\n\telse\n\t\ts_lastHostVsync += vsyncPeriod * elapsedPeriods;\n\n\tuint64 signalCount = 1;\n\tif (ActiveSettings::GetTimerShiftFactor() < 3)\n\t\tsignalCount = std::clamp<uint64>(elapsedPeriods, 1, 8);\n\tfor (uint64 i = 0; i < signalCount; ++i)\n\t\tLatteTiming_signalVsync();\n}\n''',
    "emit multiple host-driven VSyncs during fast-forward",
)

print("Cemu Joy-Con V5 stage 2 KPAD/WPAD pointer + frame fast-forward applied successfully.")
