from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v7_pointer_gyro_toggle.py <cemu-source-root>")

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
# 1) Per-Joy-Con pointer enable state + multi-button toggle hotkey.
# -----------------------------------------------------------------------------
controller_h = root / "src/input/api/SDL/SDLController.h"
replace_once(
    controller_h,
    '''\tstd::vector<uint32> get_vertical_hotkey() const;\n\tstd::vector<uint32> get_sideways_hotkey() const;\n\tvoid set_vertical_hotkey(std::vector<uint32> buttons);\n\tvoid set_sideways_hotkey(std::vector<uint32> buttons);\n''',
    '''\tstd::vector<uint32> get_vertical_hotkey() const;\n\tstd::vector<uint32> get_sideways_hotkey() const;\n\tstd::vector<uint32> get_pointer_hotkey() const;\n\tvoid set_vertical_hotkey(std::vector<uint32> buttons);\n\tvoid set_sideways_hotkey(std::vector<uint32> buttons);\n\tvoid set_pointer_hotkey(std::vector<uint32> buttons);\n\tbool is_pointer_enabled() const { return m_pointer_enabled.load(std::memory_order_relaxed); }\n\tvoid set_pointer_enabled(bool enabled, bool notify = true);\n''',
    "pointer public controller API",
)
replace_once(
    controller_h,
    '''\tstd::vector<uint32> m_vertical_hotkey{};\n\tstd::vector<uint32> m_sideways_hotkey{};\n\tbool m_vertical_hotkey_latched = false;\n\tbool m_sideways_hotkey_latched = false;\n''',
    '''\tstd::vector<uint32> m_vertical_hotkey{};\n\tstd::vector<uint32> m_sideways_hotkey{};\n\tstd::vector<uint32> m_pointer_hotkey{};\n\tstd::atomic_bool m_pointer_enabled{ true };\n\tbool m_vertical_hotkey_latched = false;\n\tbool m_sideways_hotkey_latched = false;\n\tbool m_pointer_hotkey_latched = false;\n''',
    "pointer controller state",
)

controller_cpp = root / "src/input/api/SDL/SDLController.cpp"
replace_once(
    controller_cpp,
    '''std::vector<uint32> SDLController::get_sideways_hotkey() const\n{\n\tstd::scoped_lock lock(m_controller_mutex);\n\treturn m_sideways_hotkey;\n}\n\nvoid SDLController::set_vertical_hotkey''',
    '''std::vector<uint32> SDLController::get_sideways_hotkey() const\n{\n\tstd::scoped_lock lock(m_controller_mutex);\n\treturn m_sideways_hotkey;\n}\n\nstd::vector<uint32> SDLController::get_pointer_hotkey() const\n{\n\tstd::scoped_lock lock(m_controller_mutex);\n\treturn m_pointer_hotkey;\n}\n\nvoid SDLController::set_vertical_hotkey''',
    "pointer hotkey getter",
)
replace_once(
    controller_cpp,
    '''void SDLController::set_sideways_hotkey(std::vector<uint32> buttons)\n{\n\tnormalize_hotkey(buttons);\n\tstd::scoped_lock lock(m_controller_mutex);\n\tm_sideways_hotkey = std::move(buttons);\n\tm_sideways_hotkey_latched = false;\n}\n\nstd::vector<uint32> SDLController::get_pressed_buttons_for_hotkey''',
    '''void SDLController::set_sideways_hotkey(std::vector<uint32> buttons)\n{\n\tnormalize_hotkey(buttons);\n\tstd::scoped_lock lock(m_controller_mutex);\n\tm_sideways_hotkey = std::move(buttons);\n\tm_sideways_hotkey_latched = false;\n}\n\nvoid SDLController::set_pointer_hotkey(std::vector<uint32> buttons)\n{\n\tnormalize_hotkey(buttons);\n\tstd::scoped_lock lock(m_controller_mutex);\n\tm_pointer_hotkey = std::move(buttons);\n\tm_pointer_hotkey_latched = false;\n}\n\nvoid SDLController::set_pointer_enabled(bool enabled, bool notify)\n{\n\tif (!is_joycon())\n\t\treturn;\n\n\tconst bool previous = m_pointer_enabled.exchange(enabled, std::memory_order_relaxed);\n\tif (notify && previous != enabled)\n\t{\n\t\tconst char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";\n\t\tLatteOverlay_pushNotification(fmt::format("{} Pointer {}", side, enabled ? "ON" : "OFF"), 2200);\n\t}\n}\n\nstd::vector<uint32> SDLController::get_pressed_buttons_for_hotkey''',
    "pointer hotkey setter and enable OSD",
)

replace_once(
    controller_cpp,
    '''\tnode.append_child("joycon_vertical_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_vertical_hotkey()).c_str());\n\tnode.append_child("joycon_sideways_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_sideways_hotkey()).c_str());\n''',
    '''\tnode.append_child("joycon_vertical_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_vertical_hotkey()).c_str());\n\tnode.append_child("joycon_sideways_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_sideways_hotkey()).c_str());\n\tnode.append_child("joycon_pointer_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_pointer_hotkey()).c_str());\n\tnode.append_child("joycon_pointer_enabled").append_child(pugi::node_pcdata).set_value(is_pointer_enabled() ? "1" : "0");\n''',
    "save pointer profile state",
)
replace_once(
    controller_cpp,
    '''\tif (const auto value = node.child("joycon_sideways_hotkey"))\n\t\tset_sideways_hotkey(ParseJoyConHotkey(value.child_value()));\n\tJoyConOrientation orientation = JoyConOrientation::Sideways;\n''',
    '''\tif (const auto value = node.child("joycon_sideways_hotkey"))\n\t\tset_sideways_hotkey(ParseJoyConHotkey(value.child_value()));\n\tif (const auto value = node.child("joycon_pointer_hotkey"))\n\t\tset_pointer_hotkey(ParseJoyConHotkey(value.child_value()));\n\tbool pointer_enabled = true;\n\tif (const auto value = node.child("joycon_pointer_enabled"))\n\t\tpointer_enabled = ConvertString<int>(value.child_value()) != 0;\n\tset_pointer_enabled(pointer_enabled, false);\n\tJoyConOrientation orientation = JoyConOrientation::Sideways;\n''',
    "load pointer profile state",
)

replace_once(
    controller_cpp,
    '''\t\tconst bool vertical_pressed = is_hotkey_pressed(result.buttons, m_vertical_hotkey);\n\t\tconst bool sideways_pressed = is_hotkey_pressed(result.buttons, m_sideways_hotkey);\n''',
    '''\t\tconst bool vertical_pressed = is_hotkey_pressed(result.buttons, m_vertical_hotkey);\n\t\tconst bool sideways_pressed = is_hotkey_pressed(result.buttons, m_sideways_hotkey);\n\t\tconst bool pointer_pressed = is_hotkey_pressed(result.buttons, m_pointer_hotkey);\n''',
    "detect pointer toggle chord",
)
replace_once(
    controller_cpp,
    '''\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n\t\tm_vertical_hotkey_latched = vertical_pressed;\n\t\tm_sideways_hotkey_latched = sideways_pressed;\n''',
    '''\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n\t\tif (pointer_pressed && !m_pointer_hotkey_latched)\n\t\t\tset_pointer_enabled(!is_pointer_enabled());\n\t\tm_vertical_hotkey_latched = vertical_pressed;\n\t\tm_sideways_hotkey_latched = sideways_pressed;\n\t\tm_pointer_hotkey_latched = pointer_pressed;\n''',
    "toggle pointer on hotkey edge",
)
replace_once(
    controller_cpp,
    '''\t\tif (sideways_pressed)\n\t\t\tconsume_hotkey(result.buttons, m_sideways_hotkey);\n''',
    '''\t\tif (sideways_pressed)\n\t\t\tconsume_hotkey(result.buttons, m_sideways_hotkey);\n\t\tif (pointer_pressed)\n\t\t\tconsume_hotkey(result.buttons, m_pointer_hotkey);\n''',
    "consume pointer toggle chord",
)


# -----------------------------------------------------------------------------
# 2) Pointer algorithm: calibrated gyro angular displacement -> Wii IR screen.
#
# SDL standard gamepad sensor coordinates:
#   gyro X = pitch, gyro Y = yaw, gyro Z = roll (rad/s).
# V6 normalizes the physical Joy-Con basis so this mapping is the same in both
# user Vertical and Sideways modes. Positive SDL yaw points left, positive pitch
# points up, while DPD screen coordinates grow right/down, hence the two minus signs.
#
# A real Wii Remote IR camera is roughly 33 deg horizontal x 23 deg vertical FOV.
# Mapping angular displacement by that FOV gives physical-looking pointer travel:
# center->edge ~= 16.5 deg horizontally and 11.5 deg vertically.
# -----------------------------------------------------------------------------
wpad_h = root / "src/input/emulated/WPADController.h"
replace_once(
    wpad_h,
    '''\tglm::vec2 m_joycon_pointer_reference{};\n''',
    '''\tstd::chrono::steady_clock::time_point m_joycon_pointer_last_update{};\n''',
    "replace fusion reference with gyro integration clock",
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

	if (!joycon || !joycon->is_connected() || !joycon->has_motion() || !joycon->is_pointer_enabled())
	{
		m_joycon_pointer_initialized = false;
		m_joycon_pointer_uuid.clear();
		return false;
	}

	float gyro[3]{};
	auto sample = joycon->get_motion_sample();
	sample.getGyrometer(gyro);
	if (!std::isfinite(gyro[0]) || !std::isfinite(gyro[1]) || !std::isfinite(gyro[2]))
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
		m_joycon_pointer_initialized = true;
		m_joycon_pointer_uuid = joycon->uuid();
		m_joycon_pointer_orientation = current_mode;
		m_joycon_pointer_last_update = now;
		position = m_joycon_pointer;
		previous = m_joycon_pointer_prev;
		return true;
	}

	float dt = std::chrono::duration<float>(now - m_joycon_pointer_last_update).count();
	m_joycon_pointer_last_update = now;
	if (dt <= 0.000001f)
	{
		position = m_joycon_pointer;
		previous = m_joycon_pointer_prev;
		return true;
	}
	// Do not turn a pause, debugger stop, or frame hitch into a cursor jump.
	if (dt > 0.080f)
		dt = 1.0f / 60.0f;
	else
		dt = std::min(dt, 1.0f / 30.0f);

	auto remove_deadzone = [](float rate) {
		constexpr float kGyroDeadzone = 0.012f; // rad/s; only removes stationary sensor noise
		const float magnitude = std::abs(rate);
		if (magnitude <= kGyroDeadzone)
			return 0.0f;
		return std::copysign(magnitude - kGyroDeadzone, rate);
	};

	const float pitch_rate = remove_deadzone(gyro[0]);
	const float yaw_rate = remove_deadzone(gyro[1]);

	constexpr float kPi = 3.14159265358979323846f;
	constexpr float kHorizontalFov = 33.0f * kPi / 180.0f;
	constexpr float kVerticalFov = 23.0f * kPi / 180.0f;

	// SDL positive yaw points left and positive pitch points up. DPD is right/down.
	const float dx = (-yaw_rate * dt) / kHorizontalFov;
	const float dy = (-pitch_rate * dt) / kVerticalFov;

	m_joycon_pointer_prev = m_joycon_pointer;
	m_joycon_pointer.x = std::clamp(m_joycon_pointer.x + dx, 0.0f, 1.0f);
	m_joycon_pointer.y = std::clamp(m_joycon_pointer.y + dy, 0.0f, 1.0f);

	position = m_joycon_pointer;
	previous = m_joycon_pointer_prev;
	return true;
}

WPADDataFormat WPADController::get_default_data_format'''
regex_replace_once(wpad_cpp, pattern, replacement, "replace fusion pointer with calibrated screen-space gyro pointer")


# -----------------------------------------------------------------------------
# 3) Wii Remote panel controls: pointer checkbox + configurable multi-button
# toggle chord, saved per Joy-Con just like orientation hotkeys.
# -----------------------------------------------------------------------------
panel_h = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.h"
replace_once(
    panel_h,
    '''\tenum class JoyConHotkeyCapture { None, Sideways, Vertical };\n''',
    '''\tenum class JoyConHotkeyCapture { None, Sideways, Vertical, Pointer };\n''',
    "add pointer hotkey capture mode",
)
replace_once(
    panel_h,
    '''\twxButton* m_joycon_sideways_hotkey = nullptr;\n\twxButton* m_joycon_vertical_hotkey = nullptr;\n\twxStaticText* m_joycon_status = nullptr;\n''',
    '''\twxButton* m_joycon_sideways_hotkey = nullptr;\n\twxButton* m_joycon_vertical_hotkey = nullptr;\n\twxCheckBox* m_joycon_pointer_enabled = nullptr;\n\twxButton* m_joycon_pointer_hotkey = nullptr;\n\twxStaticText* m_joycon_status = nullptr;\n''',
    "add pointer UI members",
)
replace_once(
    panel_h,
    '''\tvoid on_joycon_orientation_change(wxCommandEvent& event);\n\tvoid on_joycon_hotkey_click(wxCommandEvent& event);\n''',
    '''\tvoid on_joycon_orientation_change(wxCommandEvent& event);\n\tvoid on_joycon_pointer_enable(wxCommandEvent& event);\n\tvoid on_joycon_hotkey_click(wxCommandEvent& event);\n''',
    "add pointer checkbox handler",
)

panel_cpp = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"
replace_once(
    panel_cpp,
    '''\tjoycon_sizer->Add(m_joycon_sideways_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);\n\tjoycon_sizer->Add(m_joycon_vertical_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);\n\tm_joycon_status = new wxStaticText''',
    '''\tjoycon_sizer->Add(m_joycon_sideways_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);\n\tjoycon_sizer->Add(m_joycon_vertical_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);\n\tm_joycon_pointer_enabled = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Pointer enabled"));\n\tm_joycon_pointer_enabled->SetValue(true);\n\tm_joycon_pointer_enabled->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_pointer_enable, this);\n\tjoycon_sizer->Add(m_joycon_pointer_enabled, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);\n\tm_joycon_pointer_hotkey = new wxButton(m_joycon_panel, wxID_ANY, _("Pointer hotkey: Not set"));\n\tm_joycon_pointer_hotkey->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_hotkey_click, this);\n\tm_joycon_pointer_hotkey->Bind(wxEVT_RIGHT_UP, &WiimoteInputPanel::on_joycon_hotkey_clear, this);\n\tm_joycon_pointer_hotkey->SetToolTip(_("Click, release all controller buttons, then press and release a 2+ button combo to toggle pointer ON/OFF. Right-click to clear."));\n\tjoycon_sizer->Add(m_joycon_pointer_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);\n\tm_joycon_status = new wxStaticText''',
    "add pointer controls to Joy-Con row",
)

replace_once(
    panel_cpp,
    '''\tif (m_joycon_capture != JoyConHotkeyCapture::Vertical)\n\t\tm_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + joycon_hotkey_label(joycon, joycon->get_vertical_hotkey()));\n}\n\nvoid WiimoteInputPanel::on_joycon_orientation_change''',
    '''\tif (m_joycon_capture != JoyConHotkeyCapture::Vertical)\n\t\tm_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + joycon_hotkey_label(joycon, joycon->get_vertical_hotkey()));\n\tm_joycon_pointer_enabled->SetValue(joycon->is_pointer_enabled());\n\tif (m_joycon_capture != JoyConHotkeyCapture::Pointer)\n\t\tm_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: ") + joycon_hotkey_label(joycon, joycon->get_pointer_hotkey()));\n}\n\nvoid WiimoteInputPanel::on_joycon_orientation_change''',
    "refresh pointer controls",
)

replace_once(
    panel_cpp,
    '''void WiimoteInputPanel::on_joycon_hotkey_click(wxCommandEvent& event)\n{\n\tif (!m_active_joycon.lock()) return;\n\tm_joycon_capture = event.GetEventObject() == m_joycon_vertical_hotkey ? JoyConHotkeyCapture::Vertical : JoyConHotkeyCapture::Sideways;\n''',
    '''void WiimoteInputPanel::on_joycon_pointer_enable(wxCommandEvent&)\n{\n\tif (const auto joycon = m_active_joycon.lock())\n\t{\n\t\tjoycon->set_pointer_enabled(m_joycon_pointer_enabled->GetValue());\n\t\tm_joycon_status->SetLabel(joycon->is_pointer_enabled() ? _("Pointer ON. It recenters when enabled.") : _("Pointer OFF. No IR/DPD data will be sent."));\n\t}\n}\n\nvoid WiimoteInputPanel::on_joycon_hotkey_click(wxCommandEvent& event)\n{\n\tif (!m_active_joycon.lock()) return;\n\tif (event.GetEventObject() == m_joycon_pointer_hotkey)\n\t\tm_joycon_capture = JoyConHotkeyCapture::Pointer;\n\telse\n\t\tm_joycon_capture = event.GetEventObject() == m_joycon_vertical_hotkey ? JoyConHotkeyCapture::Vertical : JoyConHotkeyCapture::Sideways;\n''',
    "pointer checkbox handler and capture selection",
)
replace_once(
    panel_cpp,
    '''\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical)\n\t\tm_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: release all buttons..."));\n\telse\n\t\tm_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: release all buttons..."));\n''',
    '''\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical)\n\t\tm_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: release all buttons..."));\n\telse if (m_joycon_capture == JoyConHotkeyCapture::Pointer)\n\t\tm_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: release all buttons..."));\n\telse\n\t\tm_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: release all buttons..."));\n''',
    "pointer capture prompt",
)
replace_once(
    panel_cpp,
    '''\t\tif (event.GetEventObject() == m_joycon_vertical_hotkey) joycon->set_vertical_hotkey({});\n\t\telse joycon->set_sideways_hotkey({});\n''',
    '''\t\tif (event.GetEventObject() == m_joycon_vertical_hotkey) joycon->set_vertical_hotkey({});\n\t\telse if (event.GetEventObject() == m_joycon_pointer_hotkey) joycon->set_pointer_hotkey({});\n\t\telse joycon->set_sideways_hotkey({});\n''',
    "clear pointer hotkey",
)
replace_once(
    panel_cpp,
    '''\t\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical) m_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + label);\n\t\telse m_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: ") + label);\n''',
    '''\t\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical) m_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + label);\n\t\telse if (m_joycon_capture == JoyConHotkeyCapture::Pointer) m_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: ") + label);\n\t\telse m_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: ") + label);\n''',
    "show pointer chord while capturing",
)
replace_once(
    panel_cpp,
    '''\t\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical) joycon->set_vertical_hotkey(m_joycon_capture_buttons);\n\t\telse joycon->set_sideways_hotkey(m_joycon_capture_buttons);\n''',
    '''\t\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical) joycon->set_vertical_hotkey(m_joycon_capture_buttons);\n\t\telse if (m_joycon_capture == JoyConHotkeyCapture::Pointer) joycon->set_pointer_hotkey(m_joycon_capture_buttons);\n\t\telse joycon->set_sideways_hotkey(m_joycon_capture_buttons);\n''',
    "save pointer toggle chord",
)

print("Cemu Joy-Con V7 calibrated gyro pointer + pointer toggle hotkey patch applied successfully.")
