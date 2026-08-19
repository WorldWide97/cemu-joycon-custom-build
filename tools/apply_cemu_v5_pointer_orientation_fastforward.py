from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v5_pointer_orientation_fastforward.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# -----------------------------------------------------------------------------
# 1) Correct the user-facing Orientation semantics.
# -----------------------------------------------------------------------------
controller = root / "src/input/api/SDL/SDLController.cpp"

replace_once(
    controller,
    '''\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);\n''',
    '''\t\t// The internal transform enum is opposite to the physical Joy-Con\n\t\t// orientation because SDL is permanently kept in mini-gamepad mode.\n\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n''',
    "swap physical orientation hotkey semantics",
)

replace_once(
    controller,
    '''\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Vertical" : "Sideways";\n''',
    '''\t\t// Internal Vertical is the physical Sideways transform and vice versa.\n\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Sideways" : "Vertical";\n''',
    "correct orientation OSD label",
)

panel = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"
replace_once(
    panel,
    '''\tconst int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 1 : 0;\n''',
    '''\t// Internal Vertical == physical Sideways; internal Sideways == physical Vertical.\n\tconst int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 0 : 1;\n''',
    "correct orientation choice display",
)
replace_once(
    panel,
    '''\t\tjoycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);\n''',
    '''\t\tjoycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Sideways : SDLController::JoyConOrientation::Vertical);\n''',
    "correct orientation choice action",
)


# -----------------------------------------------------------------------------
# 2) Correct horizontal motion in the two PHYSICAL modes reported reversed.
# -----------------------------------------------------------------------------
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
replace_once(
    provider,
    '''\t\t\t\tconst bool flip_horizontal_motion =\n\t\t\t\t\t(config->second.is_left && config->second.vertical) ||\n\t\t\t\t\t(!config->second.is_left && !config->second.vertical);\n''',
    '''\t\t\t\tconst bool flip_horizontal_motion =\n\t\t\t\t\t(config->second.is_left && !config->second.vertical) ||\n\t\t\t\t\t(!config->second.is_left && config->second.vertical);\n''',
    "correct physical L-Vertical and R-Sideways motion sign",
)


# -----------------------------------------------------------------------------
# 3) Gyro pointer for Joy-Con when emulating Wii Remote.
# -----------------------------------------------------------------------------
wpad_h = root / "src/input/emulated/WPADController.h"
replace_once(
    wpad_h,
    '''private:\n\tuint32be m_last_holdvalue = 0;\n\n\tstd::chrono::steady_clock::time_point m_last_hold_change{}, m_last_pulse{};\n''',
    '''private:\n\tbool update_joycon_pointer(glm::vec2& position, glm::vec2& previous);\n\n\tglm::vec2 m_joycon_pointer{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_prev{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_last_orientation{};\n\tbool m_joycon_pointer_initialized = false;\n\tstd::string m_joycon_pointer_uuid{};\n\tuint8 m_joycon_pointer_orientation = 0xFF;\n\n\tuint32be m_last_holdvalue = 0;\n\n\tstd::chrono::steady_clock::time_point m_last_hold_change{}, m_last_pulse{};\n''',
    "add Wii Remote Joy-Con gyro pointer state",
)

wpad_cpp = root / "src/input/emulated/WPADController.cpp"
replace_once(
    wpad_cpp,
    '''#include <api/Controller.h>\n#include "input/emulated/WPADController.h"\n''',
    '''#include <api/Controller.h>\n#include "input/emulated/WPADController.h"\n#include "input/api/SDL/SDLController.h"\n\n#include <cmath>\n''',
    "add SDL Joy-Con pointer include",
)

constructor = '''WPADController::WPADController(size_t player_index, WPADDataFormat data_format)\n\t: EmulatedController(player_index), m_data_format(data_format)\n{\n}\n'''
pointer_impl = constructor + r'''

bool WPADController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)
{
	std::shared_ptr<SDLController> joycon;
	{
		std::shared_lock lock(m_mutex);
		for (const auto& controller : m_controllers)
		{
			auto candidate = std::dynamic_pointer_cast<SDLController>(controller);
			if (candidate && candidate->is_joycon() && candidate->use_motion())
			{
				joycon = std::move(candidate);
				break;
			}
		}
	}

	if (!joycon || !joycon->is_connected() || !joycon->has_motion())
	{
		m_joycon_pointer_initialized = false;
		m_joycon_pointer_uuid.clear();
		return false;
	}

	glm::vec3 orientation{};
	auto sample = joycon->get_motion_sample();
	sample.getVPADOrientation(&orientation[0]);
	glm::vec2 current{ orientation.x, orientation.y };

	if (!std::isfinite(current.x) || !std::isfinite(current.y))
		return false;

	const uint8 current_mode = static_cast<uint8>(joycon->get_joycon_orientation());
	const bool reset_pointer = !m_joycon_pointer_initialized ||
		m_joycon_pointer_uuid != joycon->uuid() ||
		m_joycon_pointer_orientation != current_mode;

	if (reset_pointer)
	{
		m_joycon_pointer = { 0.5f, 0.5f };
		m_joycon_pointer_prev = m_joycon_pointer;
		m_joycon_pointer_last_orientation = current;
		m_joycon_pointer_initialized = true;
		m_joycon_pointer_uuid = joycon->uuid();
		m_joycon_pointer_orientation = current_mode;
		position = m_joycon_pointer;
		previous = m_joycon_pointer_prev;
		return true;
	}

	auto wrapped_delta = [](float current_value, float previous_value) {
		float delta = current_value - previous_value;
		while (delta > 0.5f) delta -= 1.0f;
		while (delta < -0.5f) delta += 1.0f;
		return delta;
	};

	const glm::vec2 delta{
		wrapped_delta(current.x, m_joycon_pointer_last_orientation.x),
		wrapped_delta(current.y, m_joycon_pointer_last_orientation.y)
	};
	m_joycon_pointer_last_orientation = current;

	if (std::abs(delta.x) > 0.20f || std::abs(delta.y) > 0.20f)
	{
		m_joycon_pointer = { 0.5f, 0.5f };
		m_joycon_pointer_prev = m_joycon_pointer;
	}
	else
	{
		m_joycon_pointer_prev = m_joycon_pointer;
		constexpr float kPointerSensitivity = 4.0f;
		m_joycon_pointer.x = std::clamp(m_joycon_pointer.x + delta.x * kPointerSensitivity, 0.0f, 1.0f);
		m_joycon_pointer.y = std::clamp(m_joycon_pointer.y + delta.y * kPointerSensitivity, 0.0f, 1.0f);
	}

	position = m_joycon_pointer;
	previous = m_joycon_pointer_prev;
	return true;
}
'''
replace_once(wpad_cpp, constructor, pointer_impl, "implement Wii Remote Joy-Con gyro pointer")

old_kpad = '''\tauto visibility = GetPositionVisibility();\n\tif (has_position() && visibility != PositionVisibility::NONE)\n\t{\n\t\tif (visibility == PositionVisibility::FULL)\n\t\t\tstatus.dpd_valid_fg = 2;\n\t\telse\n\t\t\tstatus.dpd_valid_fg = -1;\n\n\t\tconst auto position = get_position();\n\t\tconst auto pos = (position * 2.0f) - 1.0f;\n\t\tstatus.pos.x = pos.x;\n\t\tstatus.pos.y = pos.y;\n\n\t\tconst auto delta = position - get_prev_position();\n\t\tstatus.vec.x = delta.x;\n\t\tstatus.vec.y = delta.y;\n\t\tstatus.speed = glm::length(delta);\n\t}\n\telse\n\t\tstatus.dpd_valid_fg = 0;\n'''
new_kpad = '''\tauto visibility = GetPositionVisibility();\n\tif (has_position() && visibility != PositionVisibility::NONE)\n\t{\n\t\tif (visibility == PositionVisibility::FULL)\n\t\t\tstatus.dpd_valid_fg = 2;\n\t\telse\n\t\t\tstatus.dpd_valid_fg = -1;\n\n\t\tconst auto position = get_position();\n\t\tconst auto pos = (position * 2.0f) - 1.0f;\n\t\tstatus.pos.x = pos.x;\n\t\tstatus.pos.y = pos.y;\n\n\t\tconst auto delta = position - get_prev_position();\n\t\tstatus.vec.x = delta.x;\n\t\tstatus.vec.y = delta.y;\n\t\tstatus.speed = glm::length(delta);\n\t}\n\telse\n\t{\n\t\tglm::vec2 position{}, previous{};\n\t\tif (update_joycon_pointer(position, previous))\n\t\t{\n\t\t\tstatus.dpd_valid_fg = 2;\n\t\t\tconst auto pos = (position * 2.0f) - 1.0f;\n\t\t\tstatus.pos.x = pos.x;\n\t\t\tstatus.pos.y = pos.y;\n\t\t\tconst auto delta = position - previous;\n\t\t\tstatus.vec.x = delta.x;\n\t\t\tstatus.vec.y = delta.y;\n\t\t\tstatus.speed = glm::length(delta);\n\t\t}\n\t\telse\n\t\t\tstatus.dpd_valid_fg = 0;\n\t}\n'''
replace_once(wpad_cpp, old_kpad, new_kpad, "route Joy-Con gyro pointer into KPAD")

replace_once(
    wpad_cpp,
    '''\t// todo fill position api from wiimote\n\n\tswitch (m_data_format)\n''',
    '''\t// Joy-Con has no physical IR camera, so synthesize two sensor-bar dots\n\t// around the gyro pointer for games that read raw WPAD DPD objects.\n\tglm::vec2 joycon_pointer{}, joycon_pointer_prev{};\n\tconst bool has_joycon_pointer = update_joycon_pointer(joycon_pointer, joycon_pointer_prev);\n\n\tswitch (m_data_format)\n''',
    "prepare raw WPAD Joy-Con pointer",
)

replace_once(
    wpad_cpp,
    '''\tstatus->dev = get_device_type();\n\tstatus->err = WPAD_ERR_NONE;\n}\n''',
    '''\tif (has_joycon_pointer)\n\t{\n\t\tfor (auto& object : status->obj)\n\t\t{\n\t\t\tobject.x = 0x03FF;\n\t\t\tobject.y = 0x03FF;\n\t\t\tobject.size = 0;\n\t\t\tobject.traceId = 0xFF;\n\t\t}\n\n\t\tconst int center_x = std::clamp((int)std::lround(joycon_pointer.x * 1023.0f), 0, 1023);\n\t\tconst int center_y = std::clamp((int)std::lround(joycon_pointer.y * 767.0f), 0, 767);\n\t\tconstexpr int half_bar_width = 36;\n\t\tstatus->obj[0].x = (uint16)std::clamp(center_x - half_bar_width, 0, 1023);\n\t\tstatus->obj[0].y = (uint16)center_y;\n\t\tstatus->obj[0].size = 8;\n\t\tstatus->obj[0].traceId = 0;\n\t\tstatus->obj[1].x = (uint16)std::clamp(center_x + half_bar_width, 0, 1023);\n\t\tstatus->obj[1].y = (uint16)center_y;\n\t\tstatus->obj[1].size = 8;\n\t\tstatus->obj[1].traceId = 1;\n\t}\n\n\tstatus->dev = get_device_type();\n\tstatus->err = WPAD_ERR_NONE;\n}\n''',
    "emit raw WPAD DPD objects from Joy-Con pointer",
)


# -----------------------------------------------------------------------------
# 4) Real fast-forward for frame-driven Wii U titles.
# -----------------------------------------------------------------------------
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
    '''\tconst uint8 timerShift = ActiveSettings::GetTimerShiftFactor();\n\tif (timerShift < 3)\n\t\ttick >>= (3 - timerShift);\n\telse if (timerShift > 3)\n\t\ttick <<= (timerShift - 3);\n\treturn std::max<HRTick>(tick, 1);\n}\n\nvoid LatteTiming_setCustomVsyncFrequency''',
    "scale virtual VSync with timer speed",
)

replace_once(
    latte,
    '''\tif (elapsedPeriods >= 10)\n\t{\n\t\ts_lastHostVsync = nowTimePoint;\n\t}\n\telse\n\t\ts_lastHostVsync += vsyncPeriod;\n\n\tLatteTiming_signalVsync();\n}\n''',
    '''\tif (elapsedPeriods >= 10)\n\t{\n\t\ts_lastHostVsync = nowTimePoint;\n\t}\n\telse\n\t\ts_lastHostVsync += vsyncPeriod * elapsedPeriods;\n\n\tuint64 signalCount = 1;\n\tif (ActiveSettings::GetTimerShiftFactor() < 3)\n\t\tsignalCount = std::clamp<uint64>(elapsedPeriods, 1, 8);\n\tfor (uint64 i = 0; i < signalCount; ++i)\n\t\tLatteTiming_signalVsync();\n}\n''',
    "emit multiple host-driven VSyncs during fast-forward",
)

print("Cemu Joy-Con V5 pointer/orientation/real-fast-forward patch applied successfully.")
