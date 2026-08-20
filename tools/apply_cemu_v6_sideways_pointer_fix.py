from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v6_sideways_pointer_fix.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


def regex_once(path: Path, pattern: str, replacement: str, label: str):
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    path.write_text(new_text, encoding="utf-8")
    print(f"Patched {path}: {label}")


# -----------------------------------------------------------------------------
# 1) Restore the real SDL3 semantics.
#    Cemu keeps SDL_HINT_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS=0, so SDL already
#    exposes a single Joy-Con as a horizontal mini-gamepad. Therefore:
#       Sideways = SDL state as-is (NO stick/button rotation)
#       Vertical = Cemu's explicit apply_vertical_transform()
#    V5 inverted this relationship and caused sideways buttons/axes to be rotated.
# -----------------------------------------------------------------------------
controller = root / "src/input/api/SDL/SDLController.cpp"
replace_once(
    controller,
    '''\t\t// The internal transform enum is opposite to the physical Joy-Con\n\t\t// orientation because SDL is permanently kept in mini-gamepad mode.\n\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n''',
    '''\t\t// SDL mini-gamepad mode is already the physical Sideways layout.\n\t\t// Only Vertical needs Cemu's explicit 90-degree transform.\n\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);\n''',
    "restore direct physical orientation hotkey semantics",
)
replace_once(
    controller,
    '''\t\t// Internal Vertical is the physical Sideways transform and vice versa.\n\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Sideways" : "Vertical";\n''',
    '''\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Vertical" : "Sideways";\n''',
    "restore direct orientation OSD label",
)

panel = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"
replace_once(
    panel,
    '''\t// Internal Vertical == physical Sideways; internal Sideways == physical Vertical.\n\tconst int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 0 : 1;\n''',
    '''\tconst int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 1 : 0;\n''',
    "restore direct orientation choice display",
)
replace_once(
    panel,
    '''\t\tjoycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Sideways : SDLController::JoyConOrientation::Vertical);\n''',
    '''\t\tjoycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);\n''',
    "restore direct orientation choice action",
)


# -----------------------------------------------------------------------------
# 2) Restore the empirical motion sign correction to the PHYSICAL combinations
#    reported on real hardware:
#       Joy-Con L + Vertical
#       Joy-Con R + Sideways
#    Sideways buttons/stick remain untouched and are supplied directly by SDL.
# -----------------------------------------------------------------------------
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
replace_once(
    provider,
    '''\t\t\t\tconst bool flip_horizontal_motion =\n\t\t\t\t\t(config->second.is_left && !config->second.vertical) ||\n\t\t\t\t\t(!config->second.is_left && config->second.vertical);\n''',
    '''\t\t\t\tconst bool flip_horizontal_motion =\n\t\t\t\t\t(config->second.is_left && config->second.vertical) ||\n\t\t\t\t\t(!config->second.is_left && !config->second.vertical);\n''',
    "restore physical L-Vertical and R-Sideways motion sign",
)


# -----------------------------------------------------------------------------
# 3) Replace V5's fused-Euler pointer integration with gyro-rate integration.
#    The V5 pointer differentiated the fused orientation angles and amplified
#    wrapping/fusion jitter. V6 integrates the filtered angular velocity using
#    real frame time, adds a small dead-zone, and keeps the pointer relative.
# -----------------------------------------------------------------------------
wpad_h = root / "src/input/emulated/WPADController.h"
replace_once(
    wpad_h,
    '''\tglm::vec2 m_joycon_pointer_last_orientation{};\n\tbool m_joycon_pointer_initialized = false;\n''',
    '''\tglm::vec2 m_joycon_pointer_filtered_gyro{};\n\tstd::chrono::steady_clock::time_point m_joycon_pointer_last_update{};\n\tbool m_joycon_pointer_initialized = false;\n''',
    "replace pointer orientation delta state with gyro filter state",
)

wpad_cpp = root / "src/input/emulated/WPADController.cpp"
new_pointer = r'''bool WPADController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)
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
		m_joycon_pointer_filtered_gyro = {};
		return false;
	}

	auto sample = joycon->get_motion_sample();
	glm::vec3 gyro_rate{};
	sample.getVPADGyroChange(&gyro_rate[0]);
	if (!std::isfinite(gyro_rate.x) || !std::isfinite(gyro_rate.y))
		return false;

	const auto now = std::chrono::steady_clock::now();
	const uint8 current_mode = static_cast<uint8>(joycon->get_joycon_orientation());
	const bool reset_pointer = !m_joycon_pointer_initialized ||
		m_joycon_pointer_uuid != joycon->uuid() ||
		m_joycon_pointer_orientation != current_mode;

	if (reset_pointer)
	{
		m_joycon_pointer = { 0.5f, 0.5f };
		m_joycon_pointer_prev = m_joycon_pointer;
		m_joycon_pointer_filtered_gyro = {};
		m_joycon_pointer_last_update = now;
		m_joycon_pointer_initialized = true;
		m_joycon_pointer_uuid = joycon->uuid();
		m_joycon_pointer_orientation = current_mode;
		position = m_joycon_pointer;
		previous = m_joycon_pointer_prev;
		return true;
	}

	float dt = std::chrono::duration<float>(now - m_joycon_pointer_last_update).count();
	m_joycon_pointer_last_update = now;
	if (!std::isfinite(dt) || dt <= 0.0f)
		dt = 1.0f / 60.0f;
	if (dt > 0.050f)
	{
		// Ignore pauses/debugger stalls instead of turning them into pointer jumps.
		m_joycon_pointer_filtered_gyro = {};
		dt = 1.0f / 60.0f;
	}

	// VPAD gyro change is expressed in turns/second. Provider-side Joy-Con
	// transforms already normalize the selected Vertical/Sideways orientation,
	// so the same X/Y pointer axes work for both physical Joy-Con sides.
	glm::vec2 target_rate{ gyro_rate.x, gyro_rate.y };
	constexpr float kDeadzone = 0.0040f; // ~1.4 degrees/second
	if (std::abs(target_rate.x) < kDeadzone)
		target_rate.x = 0.0f;
	if (std::abs(target_rate.y) < kDeadzone)
		target_rate.y = 0.0f;

	// Low-pass filter sensor noise while keeping deliberate pointer movement fast.
	constexpr float kFilter = 0.32f;
	m_joycon_pointer_filtered_gyro += (target_rate - m_joycon_pointer_filtered_gyro) * kFilter;
	if (target_rate.x == 0.0f)
		m_joycon_pointer_filtered_gyro.x *= 0.72f;
	if (target_rate.y == 0.0f)
		m_joycon_pointer_filtered_gyro.y *= 0.72f;

	m_joycon_pointer_prev = m_joycon_pointer;
	constexpr float kHorizontalGain = 4.6f;
	constexpr float kVerticalGain = 4.0f;
	m_joycon_pointer.x = std::clamp(m_joycon_pointer.x + m_joycon_pointer_filtered_gyro.x * dt * kHorizontalGain, 0.0f, 1.0f);
	m_joycon_pointer.y = std::clamp(m_joycon_pointer.y + m_joycon_pointer_filtered_gyro.y * dt * kVerticalGain, 0.0f, 1.0f);

	position = m_joycon_pointer;
	previous = m_joycon_pointer_prev;
	return true;
}
'''
regex_once(
    wpad_cpp,
    r'''bool WPADController::update_joycon_pointer\(glm::vec2& position, glm::vec2& previous\)\n\{.*?\n\}\n\nWPADDataFormat''',
    new_pointer + "\nWPADDataFormat",
    "replace pointer with filtered gyro-rate integrator",
)

print("Cemu Joy-Con V6 sideways semantics + motion + pointer correction applied successfully.")
