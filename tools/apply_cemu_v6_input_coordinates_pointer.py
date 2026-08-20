from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v6_input_coordinates_pointer.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


def regex_replace_once(path: Path, pattern: str, repl: str, label: str):
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    path.write_text(new_text, encoding="utf-8")
    print(f"Patched {path}: {label}")


# -----------------------------------------------------------------------------
# 1) Make the provider's `vertical` flag mean PHYSICAL/user Vertical again.
#
# V5 intentionally inverted the internal enum only to correct the user-facing UI:
#   internal Sideways == physical Vertical
#   internal Vertical == physical Sideways
# The provider and control transform must therefore use internal Sideways when
# they need the physical-Vertical coordinate conversion.
# -----------------------------------------------------------------------------
controller = root / "src/input/api/SDL/SDLController.cpp"

replace_once(
    controller,
    '''\tif (m_diid >= 0)\n\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), orientation == JoyConOrientation::Vertical);\n''',
    '''\tif (m_diid >= 0)\n\t{\n\t\t// V5 user semantics: internal Sideways == physical Vertical.\n\t\tconst bool physical_vertical = orientation == JoyConOrientation::Sideways;\n\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), physical_vertical);\n\t}\n''',
    "send physical orientation to motion provider",
)

replace_once(
    controller,
    '''\tif (is_joycon())\n\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), get_joycon_orientation() == JoyConOrientation::Vertical);\n''',
    '''\tif (is_joycon())\n\t{\n\t\t// V5 user semantics: internal Sideways == physical Vertical.\n\t\tconst bool physical_vertical = get_joycon_orientation() == JoyConOrientation::Sideways;\n\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), physical_vertical);\n\t}\n''',
    "restore physical orientation on connect",
)

replace_once(
    controller,
    '''\t\tif (get_joycon_orientation() == JoyConOrientation::Vertical)\n\t\t\tapply_vertical_transform(result);\n''',
    '''\t\t// SDL already exposes a separate Joy-Con as a horizontal mini-gamepad.\n\t\t// Rotate controls only when the USER is physically holding it Vertical.\n\t\tif (get_joycon_orientation() == JoyConOrientation::Sideways)\n\t\t\tapply_vertical_transform(result);\n''',
    "apply control rotation only in physical Vertical",
)


# -----------------------------------------------------------------------------
# 2) IMU basis: one clean 3-axis rotation, exactly once, only in physical
# Vertical. Remove the old V4/V5 X-only empirical sign flip; it was calibrated
# while the orientation boolean had the opposite meaning and caused double flips.
# -----------------------------------------------------------------------------
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
pattern = r'''\t\t\t// SDL rotates a standalone Joy-Con IMU in mini-gamepad mode\. Undo that\n.*?\t\t\tif \(event\.gsensor\.sensor == SDL_SENSOR_ACCEL\)'''
replacement = '''\t\t\t// SDL reports each standalone Joy-Con in horizontal mini-gamepad coordinates.\n\t\t\t// Convert that basis to a physically upright Wii-Remote-style basis only\n\t\t\t// when the user selected Vertical. Sideways is left exactly as SDL reports it.\n\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\tconfig != s_joycon_orientation_states.end() && config->second.vertical)\n\t\t\t{\n\t\t\t\tconst float x = sensor_data[0];\n\t\t\t\tconst float y = sensor_data[1];\n\t\t\t\tconst float z = sensor_data[2];\n\t\t\t\tif (config->second.is_left)\n\t\t\t\t{\n\t\t\t\t\t// Joy-Con L: horizontal -> vertical, +90 degrees around Y.\n\t\t\t\t\tsensor_data[0] = -z;\n\t\t\t\t\tsensor_data[1] = y;\n\t\t\t\t\tsensor_data[2] = x;\n\t\t\t\t}\n\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\t// Joy-Con R: horizontal -> vertical, -90 degrees around Y.\n\t\t\t\t\tsensor_data[0] = z;\n\t\t\t\t\tsensor_data[1] = y;\n\t\t\t\t\tsensor_data[2] = -x;\n\t\t\t\t}\n\t\t\t}\n\n\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)'''
regex_replace_once(provider, pattern, replacement, "replace inverted/double IMU transforms with one physical-basis transform")


# -----------------------------------------------------------------------------
# 3) Pointer: replace accumulated per-frame deltas with an absolute position
# relative to the orientation at recenter. This avoids integration drift and the
# frequent hard resets that made V5 practically unusable.
# -----------------------------------------------------------------------------
wpad_h = root / "src/input/emulated/WPADController.h"
replace_once(
    wpad_h,
    '''\tglm::vec2 m_joycon_pointer_last_orientation{};\n''',
    '''\tglm::vec2 m_joycon_pointer_reference{};\n''',
    "store pointer neutral orientation instead of last-frame orientation",
)

wpad_cpp = root / "src/input/emulated/WPADController.cpp"
pattern = r'''bool WPADController::update_joycon_pointer\(glm::vec2& position, glm::vec2& previous\)\n\{.*?\n\}\n\nWPADDataFormat WPADController::get_default_data_format'''
replacement = r'''bool WPADController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)
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
	const glm::vec2 current{ orientation.x, orientation.y };
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
		m_joycon_pointer_reference = current;
		m_joycon_pointer_initialized = true;
		m_joycon_pointer_uuid = joycon->uuid();
		m_joycon_pointer_orientation = current_mode;
		position = m_joycon_pointer;
		previous = m_joycon_pointer_prev;
		return true;
	}

	auto wrapped_relative = [](float value, float reference) {
		float delta = value - reference;
		while (delta > 0.5f) delta -= 1.0f;
		while (delta < -0.5f) delta += 1.0f;
		return delta;
	};

	float horizontal = wrapped_relative(current.x, m_joycon_pointer_reference.x);
	float vertical = wrapped_relative(current.y, m_joycon_pointer_reference.y);

	// Ignore tiny fusion noise around the neutral pose without accumulating drift.
	constexpr float kDeadzone = 0.0025f;
	if (std::abs(horizontal) < kDeadzone) horizontal = 0.0f;
	if (std::abs(vertical) < kDeadzone) vertical = 0.0f;

	// Direct absolute mapping from the neutral pose. A full-screen traversal needs
	// roughly a quarter turn, close to the useful Wii Remote pointing envelope.
	constexpr float kHorizontalGain = 2.0f;
	constexpr float kVerticalGain = 2.0f;
	const glm::vec2 target{
		std::clamp(0.5f + horizontal * kHorizontalGain, 0.0f, 1.0f),
		std::clamp(0.5f + vertical * kVerticalGain, 0.0f, 1.0f)
	};

	m_joycon_pointer_prev = m_joycon_pointer;
	// Mild low-pass filtering removes IMU jitter while retaining quick pointer response.
	constexpr float kPointerFollow = 0.42f;
	m_joycon_pointer += (target - m_joycon_pointer) * kPointerFollow;

	position = m_joycon_pointer;
	previous = m_joycon_pointer_prev;
	return true;
}

WPADDataFormat WPADController::get_default_data_format'''
regex_replace_once(wpad_cpp, pattern, replacement, "replace drifting pointer integrator with absolute neutral-reference pointer")

print("Cemu Joy-Con V6 physical coordinates + absolute pointer patch applied successfully.")
