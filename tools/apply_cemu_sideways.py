from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_sideways.py <cemu-source-root>")

root = Path(sys.argv[1])

def read(rel):
    return (root / rel).read_text(encoding="utf-8")

def write(rel, text):
    path = root / rel
    path.write_text(text, encoding="utf-8")
    print(f"Patched {path}")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

# SDLControllerProvider.h
rel = "src/input/api/SDL/SDLControllerProvider.h"
text = read(rel)
old = "\tMotionSample motion_sample(SDL_JoystickID diid);\n"
new = old + "\tvoid set_joycon_orientation(SDL_JoystickID diid, bool is_left, bool vertical);\n\tvoid clear_joycon_orientation(SDL_JoystickID diid);\n"
text = replace_once(text, old, new, "provider header methods")
old = "\tinline static std::unordered_map<SDL_JoystickID, MotionState> s_motion_states{};\n"
new = """\tstruct JoyConOrientationState
\t{
\t\tbool is_left{};
\t\tbool vertical{};
\t};

\tinline static std::unordered_map<SDL_JoystickID, MotionState> s_motion_states{};
\tinline static std::unordered_map<SDL_JoystickID, JoyConOrientationState> s_joycon_orientation_states{};
"""
text = replace_once(text, old, new, "provider header state map")
write(rel, text)

# SDLControllerProvider.cpp
rel = "src/input/api/SDL/SDLControllerProvider.cpp"
text = read(rel)
old = """MotionSample SDLControllerProvider::motion_sample(SDL_JoystickID diid)
{
\tstd::shared_lock lock(s_mutex);
\tauto it = s_motion_states.find(diid);
\treturn (it != s_motion_states.end()) ? it->second.data : MotionSample{};
}
"""
new = old + """
void SDLControllerProvider::set_joycon_orientation(SDL_JoystickID diid, bool is_left, bool vertical)
{
\tif (diid < 0)
\t\treturn;

\tstd::scoped_lock lock(s_mutex);
\tconst auto it = s_joycon_orientation_states.find(diid);
\tif (it == s_joycon_orientation_states.end() ||
\t\tit->second.is_left != is_left ||
\t\tit->second.vertical != vertical)
\t{
\t\ts_motion_states.erase(diid);
\t}
\ts_joycon_orientation_states[diid] = { is_left, vertical };
}

void SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)
{
\tif (diid < 0)
\t\treturn;

\tstd::scoped_lock lock(s_mutex);
\ts_joycon_orientation_states.erase(diid);
\ts_motion_states.erase(diid);
}
"""
text = replace_once(text, old, new, "provider orientation methods")
old = "\tSDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH, \"1\");\n\tSDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH2, \"1\");\n\tSDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_JOY_CONS, \"1\");\n"
new = old + "\t// Keep each Joy-Con independent in SDL mini-gamepad mode. Cemu applies\n\t// per-device Vertical/Sideways transforms at runtime.\n\tSDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS, \"0\");\n\tSDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS, \"0\");\n"
text = replace_once(text, old, new, "provider SDL hints")
old = "\t\t\ts_motion_states.erase(event.gdevice.which);\n\t\t\tbreak;\n"
new = "\t\t\ts_motion_states.erase(event.gdevice.which);\n\t\t\ts_joycon_orientation_states.erase(event.gdevice.which);\n\t\t\tbreak;\n"
text = replace_once(text, old, new, "provider remove cleanup")
old = """\t\t\tauto& state = s_motion_states[id];
\t\t\tauto& tracking = state.tracking;

\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)
"""
new = """\t\t\tauto& state = s_motion_states[id];
\t\t\tauto& tracking = state.tracking;

\t\t\tfloat sensor_data[3] = {
\t\t\t\tevent.gsensor.data[0],
\t\t\t\tevent.gsensor.data[1],
\t\t\t\tevent.gsensor.data[2]
\t\t\t};

\t\t\t// SDL rotates a standalone Joy-Con IMU in mini-gamepad mode. Undo that
\t\t\t// rotation only for this physical Joy-Con when its Cemu mode is Vertical.
\t\t\tif (const auto config = s_joycon_orientation_states.find(id);
\t\t\t\tconfig != s_joycon_orientation_states.end() && config->second.vertical)
\t\t\t{
\t\t\t\tconst float x = sensor_data[0];
\t\t\t\tconst float y = sensor_data[1];
\t\t\t\tconst float z = sensor_data[2];
\t\t\t\tif (config->second.is_left)
\t\t\t\t{
\t\t\t\t\t// SDL L mini: vertical (x,y,z) -> (z,y,-x)
\t\t\t\t\tsensor_data[0] = -z;
\t\t\t\t\tsensor_data[1] = y;
\t\t\t\t\tsensor_data[2] = x;
\t\t\t\t}
\t\t\t\telse
\t\t\t\t{
\t\t\t\t\t// SDL R mini: vertical (x,y,z) -> (-z,y,x)
\t\t\t\t\tsensor_data[0] = z;
\t\t\t\t\tsensor_data[1] = y;
\t\t\t\t\tsensor_data[2] = -x;
\t\t\t\t}
\t\t\t}

\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)
"""
text = replace_once(text, old, new, "provider sensor transform")
for idx in range(3):
    text = text.replace(f"tracking.acc[{idx}] = -event.gsensor.data[{idx}] / 9.81f;", f"tracking.acc[{idx}] = -sensor_data[{idx}] / 9.81f;")
text = text.replace("tracking.gyro[0] = event.gsensor.data[0];", "tracking.gyro[0] = sensor_data[0];")
text = text.replace("tracking.gyro[1] = -event.gsensor.data[1];", "tracking.gyro[1] = -sensor_data[1];")
text = text.replace("tracking.gyro[2] = -event.gsensor.data[2];", "tracking.gyro[2] = -sensor_data[2];")
write(rel, text)

# SDLController.h
rel = "src/input/api/SDL/SDLController.h"
text = read(rel)
old = "class SDLController : public Controller<SDLControllerProvider>\n{\npublic:\n"
new = """class SDLController : public Controller<SDLControllerProvider>
{
public:
\tenum class JoyConOrientation : uint8
\t{
\t\tSideways = 0,
\t\tVertical = 1,
\t};

"""
text = replace_once(text, old, new, "controller enum")
old = "\tstd::string get_button_name(uint64 button) const override;\n\tconst SDL_GUID& get_guid() const { return m_guid; }\n"
new = """\tstd::string get_button_name(uint64 button) const override;
\tconst SDL_GUID& get_guid() const { return m_guid; }

\tbool is_left_joycon() const { return m_guid == kLeftJoyCon; }
\tbool is_right_joycon() const { return m_guid == kRightJoyCon; }
\tbool is_joycon() const { return is_left_joycon() || is_right_joycon(); }

\tJoyConOrientation get_joycon_orientation() const { return m_joycon_orientation.load(std::memory_order_relaxed); }
\tvoid set_joycon_orientation(JoyConOrientation orientation);
\tstd::vector<uint32> get_vertical_hotkey() const;
\tstd::vector<uint32> get_sideways_hotkey() const;
\tvoid set_vertical_hotkey(std::vector<uint32> buttons);
\tvoid set_sideways_hotkey(std::vector<uint32> buttons);
\tstd::vector<uint32> get_pressed_buttons_for_hotkey();

\tvoid save(pugi::xml_node& node) override;
\tvoid load(const pugi::xml_node& node) override;
"""
text = replace_once(text, old, new, "controller public API")
text = replace_once(text, "\tstd::recursive_mutex m_controller_mutex;\n", "\tmutable std::recursive_mutex m_controller_mutex;\n", "controller mutex")
old = "\tstd::array<bool, SDL_GAMEPAD_BUTTON_COUNT> m_buttons{};\n\tstd::array<bool, SDL_GAMEPAD_AXIS_COUNT> m_axis{};\n"
new = """\tstd::array<bool, SDL_GAMEPAD_BUTTON_COUNT> m_buttons{};
\tstd::array<bool, SDL_GAMEPAD_AXIS_COUNT> m_axis{};

\tstd::atomic<JoyConOrientation> m_joycon_orientation{ JoyConOrientation::Sideways };
\tstd::vector<uint32> m_vertical_hotkey{};
\tstd::vector<uint32> m_sideways_hotkey{};
\tbool m_vertical_hotkey_latched = false;
\tbool m_sideways_hotkey_latched = false;

\tbool is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const;
\tvoid consume_hotkey(ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const;
\tvoid apply_vertical_transform(ControllerState& state) const;
\tvoid normalize_hotkey(std::vector<uint32>& buttons) const;
"""
text = replace_once(text, old, new, "controller state")
write(rel, text)

# SDLController.cpp
rel = "src/input/api/SDL/SDLController.cpp"
text = read(rel)
text = replace_once(text, "#include \"input/api/SDL/SDLControllerProvider.h\"\n", "#include \"input/api/SDL/SDLControllerProvider.h\"\n\n#include <pugixml.hpp>\n#include <sstream>\n", "controller includes")
old = """SDLController::~SDLController()
{
\tif (m_controller)
\t{
\t\tSDL_CloseGamepad(m_controller);
\t\tm_controller = nullptr;
\t}
}
"""
new = """SDLController::~SDLController()
{
\tif (m_diid >= 0)
\t\tm_provider->clear_joycon_orientation(m_diid);

\tif (m_controller)
\t{
\t\tSDL_CloseGamepad(m_controller);
\t\tm_controller = nullptr;
\t}
}

namespace
{
std::string SerializeJoyConHotkey(const std::vector<uint32>& hotkey)
{
\tstd::string value;
\tfor (size_t i = 0; i < hotkey.size(); ++i)
\t{
\t\tif (i)
\t\t\tvalue.push_back(',');
\t\tvalue += fmt::format("{}", hotkey[i]);
\t}
\treturn value;
}

std::vector<uint32> ParseJoyConHotkey(std::string_view value)
{
\tstd::vector<uint32> result;
\tstd::stringstream stream(std::string{ value });
\tstd::string token;
\twhile (std::getline(stream, token, ','))
\t{
\t\tif (token.empty())
\t\t\tcontinue;
\t\ttry
\t\t{
\t\t\tconst auto id = ConvertString<uint32>(token);
\t\t\tif (id < SDL_GAMEPAD_BUTTON_COUNT)
\t\t\t\tresult.emplace_back(id);
\t\t}
\t\tcatch (...)
\t\t{
\t\t}
\t}
\treturn result;
}
}

void SDLController::normalize_hotkey(std::vector<uint32>& buttons) const
{
\tstd::erase_if(buttons, [](uint32 id) { return id >= SDL_GAMEPAD_BUTTON_COUNT; });
\tstd::sort(buttons.begin(), buttons.end());
\tbuttons.erase(std::unique(buttons.begin(), buttons.end()), buttons.end());
\tif (buttons.size() < 2)
\t\tbuttons.clear();
}

std::vector<uint32> SDLController::get_vertical_hotkey() const
{
\tstd::scoped_lock lock(m_controller_mutex);
\treturn m_vertical_hotkey;
}

std::vector<uint32> SDLController::get_sideways_hotkey() const
{
\tstd::scoped_lock lock(m_controller_mutex);
\treturn m_sideways_hotkey;
}

void SDLController::set_vertical_hotkey(std::vector<uint32> buttons)
{
\tnormalize_hotkey(buttons);
\tstd::scoped_lock lock(m_controller_mutex);
\tm_vertical_hotkey = std::move(buttons);
\tm_vertical_hotkey_latched = false;
}

void SDLController::set_sideways_hotkey(std::vector<uint32> buttons)
{
\tnormalize_hotkey(buttons);
\tstd::scoped_lock lock(m_controller_mutex);
\tm_sideways_hotkey = std::move(buttons);
\tm_sideways_hotkey_latched = false;
}

std::vector<uint32> SDLController::get_pressed_buttons_for_hotkey()
{
\tstd::vector<uint32> result;
\tstd::scoped_lock lock(m_controller_mutex);
\tif (!m_controller || !SDL_GamepadConnected(m_controller))
\t\treturn result;

\tfor (uint32 i = 0; i < SDL_GAMEPAD_BUTTON_COUNT; ++i)
\t{
\t\tif (m_buttons[i] && SDL_GetGamepadButton(m_controller, (SDL_GamepadButton)i))
\t\t\tresult.emplace_back(i);
\t}
\treturn result;
}

void SDLController::set_joycon_orientation(JoyConOrientation orientation)
{
\tif (!is_joycon())
\t\treturn;

\tstd::scoped_lock lock(m_controller_mutex);
\tm_joycon_orientation.store(orientation, std::memory_order_relaxed);
\tif (m_diid >= 0)
\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), orientation == JoyConOrientation::Vertical);
}

bool SDLController::is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const
{
\tif (hotkey.size() < 2)
\t\treturn false;
\treturn std::all_of(hotkey.cbegin(), hotkey.cend(), [&buttons](uint32 id) {
\t\treturn buttons.GetButtonState(id);
\t});
}

void SDLController::consume_hotkey(ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const
{
\tfor (const auto id : hotkey)
\t\tbuttons.SetButtonState(id, false);
}

void SDLController::apply_vertical_transform(ControllerState& state) const
{
\tconst auto old_axis = state.axis;
\tconst bool south = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_SOUTH);
\tconst bool east = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_EAST);
\tconst bool west = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_WEST);
\tconst bool north = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_NORTH);

\tif (is_left_joycon())
\t{
\t\tstate.axis.x = -old_axis.y;
\t\tstate.axis.y = old_axis.x;
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_NORTH, west);
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_EAST, north);
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_SOUTH, east);
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_WEST, south);
\t}
\telse if (is_right_joycon())
\t{
\t\tstate.axis.x = old_axis.y;
\t\tstate.axis.y = -old_axis.x;
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_NORTH, east);
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_EAST, south);
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_SOUTH, west);
\t\tstate.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_WEST, north);
\t}
}

void SDLController::save(pugi::xml_node& node)
{
\tbase_type::save(node);
\tif (!is_joycon())
\t\treturn;
\tnode.append_child("joycon_orientation").append_child(pugi::node_pcdata).set_value(fmt::format("{}", (int)get_joycon_orientation()).c_str());
\tnode.append_child("joycon_vertical_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_vertical_hotkey()).c_str());
\tnode.append_child("joycon_sideways_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_sideways_hotkey()).c_str());
}

void SDLController::load(const pugi::xml_node& node)
{
\tbase_type::load(node);
\tif (!is_joycon())
\t\treturn;
\tif (const auto value = node.child("joycon_vertical_hotkey"))
\t\tset_vertical_hotkey(ParseJoyConHotkey(value.child_value()));
\tif (const auto value = node.child("joycon_sideways_hotkey"))
\t\tset_sideways_hotkey(ParseJoyConHotkey(value.child_value()));
\tJoyConOrientation orientation = JoyConOrientation::Sideways;
\tif (const auto value = node.child("joycon_orientation"))
\t{
\t\tif (ConvertString<int>(value.child_value()) == (int)JoyConOrientation::Vertical)
\t\t\torientation = JoyConOrientation::Vertical;
\t}
\tset_joycon_orientation(orientation);
}
"""
text = replace_once(text, old, new, "controller implementation")
old = """\tif (SDL_GamepadHasSensor(m_controller, SDL_SENSOR_GYRO))
\t\tm_has_gyro = SDL_SetGamepadSensorEnabled(m_controller, SDL_SENSOR_GYRO, true);
\tm_has_rumble = SDL_RumbleGamepad(m_controller, 0, 0, 0);
\treturn true;
"""
new = """\tif (SDL_GamepadHasSensor(m_controller, SDL_SENSOR_GYRO))
\t\tm_has_gyro = SDL_SetGamepadSensorEnabled(m_controller, SDL_SENSOR_GYRO, true);
\tm_has_rumble = SDL_RumbleGamepad(m_controller, 0, 0, 0);
\tif (is_joycon())
\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), get_joycon_orientation() == JoyConOrientation::Vertical);
\treturn true;
"""
text = replace_once(text, old, new, "controller connect")
old = """\tif (m_axis[SDL_GAMEPAD_AXIS_RIGHT_TRIGGER])
\t\tresult.trigger.y = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) / 32767.0f;

\treturn result;
}
"""
new = """\tif (m_axis[SDL_GAMEPAD_AXIS_RIGHT_TRIGGER])
\t\tresult.trigger.y = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) / 32767.0f;

\tif (is_joycon())
\t{
\t\tconst bool vertical_pressed = is_hotkey_pressed(result.buttons, m_vertical_hotkey);
\t\tconst bool sideways_pressed = is_hotkey_pressed(result.buttons, m_sideways_hotkey);
\t\tif (vertical_pressed && !m_vertical_hotkey_latched)
\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);
\t\tif (sideways_pressed && !m_sideways_hotkey_latched)
\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);
\t\tm_vertical_hotkey_latched = vertical_pressed;
\t\tm_sideways_hotkey_latched = sideways_pressed;
\t\tif (vertical_pressed)
\t\t\tconsume_hotkey(result.buttons, m_vertical_hotkey);
\t\tif (sideways_pressed)
\t\t\tconsume_hotkey(result.buttons, m_sideways_hotkey);
\t\tif (get_joycon_orientation() == JoyConOrientation::Vertical)
\t\t\tapply_vertical_transform(result);
\t}

\treturn result;
}
"""
text = replace_once(text, old, new, "controller raw state")
write(rel, text)

# WiimoteInputPanel.h
rel = "src/gui/wxgui/input/panels/WiimoteInputPanel.h"
text = read(rel)
text = replace_once(text, "class wxCheckBox;\nclass wxGridBagSizer;\nclass wxInputDraw;\n", "class wxCheckBox;\nclass wxGridBagSizer;\nclass wxInputDraw;\nclass wxChoice;\nclass wxButton;\nclass wxStaticText;\nclass SDLController;\n", "wiimote forwards")
old = "\tstd::vector<wxWindow*> m_nunchuck_items;\n\n\tvoid add_button_row(sint32 row, sint32 column, const WiimoteController::ButtonId &button_id);\n"
new = """\tstd::vector<wxWindow*> m_nunchuck_items;

\tenum class JoyConHotkeyCapture { None, Sideways, Vertical };
\twxPanel* m_joycon_panel = nullptr;
\twxStaticText* m_joycon_name = nullptr;
\twxChoice* m_joycon_orientation = nullptr;
\twxButton* m_joycon_sideways_hotkey = nullptr;
\twxButton* m_joycon_vertical_hotkey = nullptr;
\twxStaticText* m_joycon_status = nullptr;
\tstd::weak_ptr<SDLController> m_active_joycon;
\tJoyConHotkeyCapture m_joycon_capture = JoyConHotkeyCapture::None;
\tbool m_joycon_capture_wait_for_idle = false;
\tbool m_joycon_capture_seen_buttons = false;
\tstd::vector<uint32> m_joycon_capture_buttons;

\tvoid on_joycon_orientation_change(wxCommandEvent& event);
\tvoid on_joycon_hotkey_click(wxCommandEvent& event);
\tvoid on_joycon_hotkey_clear(wxMouseEvent& event);
\tvoid update_joycon_controls(const std::shared_ptr<SDLController>& joycon);
\tvoid update_joycon_hotkey_capture(const std::shared_ptr<SDLController>& joycon);
\twxString joycon_hotkey_label(const std::shared_ptr<SDLController>& joycon, const std::vector<uint32>& buttons) const;

\tvoid add_button_row(sint32 row, sint32 column, const WiimoteController::ButtonId &button_id);
"""
text = replace_once(text, old, new, "wiimote members")
write(rel, text)

# WiimoteInputPanel.cpp
rel = "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"
text = read(rel)
text = replace_once(text, "#include <wx/checkbox.h>\n\n#include \"wxgui/helpers/wxControlObject.h\"\n#include \"input/emulated/WiimoteController.h\"\n", "#include <wx/checkbox.h>\n#include <wx/choice.h>\n\n#include \"wxgui/helpers/wxControlObject.h\"\n#include \"input/emulated/WiimoteController.h\"\n#include \"input/api/SDL/SDLController.h\"\n", "wiimote includes")
old = "\tmain_sizer->Add(horiz_main_sizer, 0, wxEXPAND | wxALL, 5);\n\tmain_sizer->Add(new wxStaticLine(this), 0, wxLEFT | wxRIGHT | wxTOP | wxEXPAND, 5);\n"
new = """\tmain_sizer->Add(horiz_main_sizer, 0, wxEXPAND | wxALL, 5);

\tm_joycon_panel = new wxPanel(this, wxID_ANY);
\tauto* joycon_sizer = new wxBoxSizer(wxHORIZONTAL);
\tm_joycon_name = new wxStaticText(m_joycon_panel, wxID_ANY, _("Joy-Con"));
\tm_joycon_name->SetFont(bold_font);
\tjoycon_sizer->Add(m_joycon_name, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);
\tjoycon_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Orientation:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);
\tm_joycon_orientation = new wxChoice(m_joycon_panel, wxID_ANY);
\tm_joycon_orientation->Append(_("Sideways"));
\tm_joycon_orientation->Append(_("Vertical"));
\tm_joycon_orientation->SetSelection(0);
\tm_joycon_orientation->Bind(wxEVT_CHOICE, &WiimoteInputPanel::on_joycon_orientation_change, this);
\tjoycon_sizer->Add(m_joycon_orientation, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 12);
\tm_joycon_sideways_hotkey = new wxButton(m_joycon_panel, wxID_ANY, _("Sideways hotkey: Not set"));
\tm_joycon_vertical_hotkey = new wxButton(m_joycon_panel, wxID_ANY, _("Vertical hotkey: Not set"));
\tm_joycon_sideways_hotkey->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_hotkey_click, this);
\tm_joycon_vertical_hotkey->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_hotkey_click, this);
\tm_joycon_sideways_hotkey->Bind(wxEVT_RIGHT_UP, &WiimoteInputPanel::on_joycon_hotkey_clear, this);
\tm_joycon_vertical_hotkey->Bind(wxEVT_RIGHT_UP, &WiimoteInputPanel::on_joycon_hotkey_clear, this);
\tm_joycon_sideways_hotkey->SetToolTip(_("Click, release all controller buttons, then press and release a 2+ button combo. Right-click to clear."));
\tm_joycon_vertical_hotkey->SetToolTip(_("Click, release all controller buttons, then press and release a 2+ button combo. Right-click to clear."));
\tjoycon_sizer->Add(m_joycon_sideways_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);
\tjoycon_sizer->Add(m_joycon_vertical_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);
\tm_joycon_status = new wxStaticText(m_joycon_panel, wxID_ANY, _("Hotkeys are independent for each Joy-Con."));
\tjoycon_sizer->Add(m_joycon_status, 1, wxALIGN_CENTER_VERTICAL);
\tm_joycon_panel->SetSizer(joycon_sizer);
\tm_joycon_panel->Hide();
\tmain_sizer->Add(m_joycon_panel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 5);

\tmain_sizer->Add(new wxStaticLine(this), 0, wxLEFT | wxRIGHT | wxTOP | wxEXPAND, 5);
"""
text = replace_once(text, old, new, "wiimote UI")
old = """void WiimoteInputPanel::on_timer(const EmulatedControllerPtr& emulated_controller, const ControllerPtr& controller)
{
\tif (emulated_controller)
\t{
\t\tconst auto wiimote = std::dynamic_pointer_cast<WiimoteController>(emulated_controller);
\t\twxASSERT(wiimote);

\t\twiimote->set_device_type(m_device_type);
\t}

\tInputPanel::on_timer(emulated_controller, controller);

\tif (emulated_controller)
\t{
\t\tconst auto axis = emulated_controller->get_axis();
\t\tm_draw->SetAxisValue(axis);
\t}
}
"""
new = """void WiimoteInputPanel::on_timer(const EmulatedControllerPtr& emulated_controller, const ControllerPtr& controller)
{
\tif (emulated_controller)
\t{
\t\tconst auto wiimote = std::dynamic_pointer_cast<WiimoteController>(emulated_controller);
\t\twxASSERT(wiimote);
\t\twiimote->set_device_type(m_device_type);
\t}

\tInputPanel::on_timer(emulated_controller, controller);

\tconst auto joycon = std::dynamic_pointer_cast<SDLController>(controller);
\tif (joycon && joycon->is_joycon())
\t{
\t\tm_active_joycon = joycon;
\t\tif (!m_joycon_panel->IsShown())
\t\t{
\t\t\tm_joycon_panel->Show();
\t\t\tLayout();
\t\t\tif (GetParent()) GetParent()->Layout();
\t\t}
\t\tupdate_joycon_hotkey_capture(joycon);
\t\tupdate_joycon_controls(joycon);
\t}
\telse
\t{
\t\tm_active_joycon.reset();
\t\tm_joycon_capture = JoyConHotkeyCapture::None;
\t\tm_joycon_capture_buttons.clear();
\t\tif (m_joycon_panel->IsShown())
\t\t{
\t\t\tm_joycon_panel->Hide();
\t\t\tLayout();
\t\t\tif (GetParent()) GetParent()->Layout();
\t\t}
\t}

\tif (emulated_controller)
\t{
\t\tconst auto axis = emulated_controller->get_axis();
\t\tm_draw->SetAxisValue(axis);
\t}
}

wxString WiimoteInputPanel::joycon_hotkey_label(const std::shared_ptr<SDLController>& joycon, const std::vector<uint32>& buttons) const
{
\tif (!joycon || buttons.empty()) return _("Not set");
\twxString result;
\tfor (size_t i = 0; i < buttons.size(); ++i)
\t{
\t\tif (i) result += " + ";
\t\tresult += wxString::FromUTF8(joycon->get_button_name(buttons[i]));
\t}
\treturn result;
}

void WiimoteInputPanel::update_joycon_controls(const std::shared_ptr<SDLController>& joycon)
{
\tif (!joycon) return;
\tm_joycon_name->SetLabel(joycon->is_left_joycon() ? _("Joy-Con L") : _("Joy-Con R"));
\tconst int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 1 : 0;
\tif (m_joycon_orientation->GetSelection() != selection) m_joycon_orientation->SetSelection(selection);
\tif (m_joycon_capture != JoyConHotkeyCapture::Sideways)
\t\tm_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: ") + joycon_hotkey_label(joycon, joycon->get_sideways_hotkey()));
\tif (m_joycon_capture != JoyConHotkeyCapture::Vertical)
\t\tm_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + joycon_hotkey_label(joycon, joycon->get_vertical_hotkey()));
}

void WiimoteInputPanel::on_joycon_orientation_change(wxCommandEvent&)
{
\tif (const auto joycon = m_active_joycon.lock())
\t{
\t\tjoycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);
\t\tupdate_joycon_controls(joycon);
\t}
}

void WiimoteInputPanel::on_joycon_hotkey_click(wxCommandEvent& event)
{
\tif (!m_active_joycon.lock()) return;
\tm_joycon_capture = event.GetEventObject() == m_joycon_vertical_hotkey ? JoyConHotkeyCapture::Vertical : JoyConHotkeyCapture::Sideways;
\tm_joycon_capture_buttons.clear();
\tm_joycon_capture_wait_for_idle = true;
\tm_joycon_capture_seen_buttons = false;
\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical)
\t\tm_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: release all buttons..."));
\telse
\t\tm_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: release all buttons..."));
\tm_joycon_status->SetLabel(_("Then press and release the exact 2+ button combo you want."));
}

void WiimoteInputPanel::on_joycon_hotkey_clear(wxMouseEvent& event)
{
\tif (const auto joycon = m_active_joycon.lock())
\t{
\t\tif (event.GetEventObject() == m_joycon_vertical_hotkey) joycon->set_vertical_hotkey({});
\t\telse joycon->set_sideways_hotkey({});
\t\tm_joycon_capture = JoyConHotkeyCapture::None;
\t\tm_joycon_capture_buttons.clear();
\t\tm_joycon_status->SetLabel(_("Hotkey cleared."));
\t\tupdate_joycon_controls(joycon);
\t}
}

void WiimoteInputPanel::update_joycon_hotkey_capture(const std::shared_ptr<SDLController>& joycon)
{
\tif (!joycon || m_joycon_capture == JoyConHotkeyCapture::None) return;
\tconst auto pressed = joycon->get_pressed_buttons_for_hotkey();
\tif (m_joycon_capture_wait_for_idle)
\t{
\t\tif (!pressed.empty()) return;
\t\tm_joycon_capture_wait_for_idle = false;
\t\tm_joycon_status->SetLabel(_("Press your 2+ button combo now, then release it to save."));
\t\treturn;
\t}
\tif (!pressed.empty())
\t{
\t\tm_joycon_capture_seen_buttons = true;
\t\tfor (const auto id : pressed)
\t\t\tif (std::find(m_joycon_capture_buttons.cbegin(), m_joycon_capture_buttons.cend(), id) == m_joycon_capture_buttons.cend()) m_joycon_capture_buttons.emplace_back(id);
\t\tstd::sort(m_joycon_capture_buttons.begin(), m_joycon_capture_buttons.end());
\t\tconst auto label = joycon_hotkey_label(joycon, m_joycon_capture_buttons);
\t\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical) m_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + label);
\t\telse m_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: ") + label);
\t\treturn;
\t}
\tif (!m_joycon_capture_seen_buttons) return;
\tif (m_joycon_capture_buttons.size() < 2)
\t\tm_joycon_status->SetLabel(_("Not saved: use at least 2 controller buttons."));
\telse
\t{
\t\tif (m_joycon_capture == JoyConHotkeyCapture::Vertical) joycon->set_vertical_hotkey(m_joycon_capture_buttons);
\t\telse joycon->set_sideways_hotkey(m_joycon_capture_buttons);
\t\tm_joycon_status->SetLabel(_("Hotkey saved. It works instantly during gameplay."));
\t}
\tm_joycon_capture = JoyConHotkeyCapture::None;
\tm_joycon_capture_buttons.clear();
\tm_joycon_capture_seen_buttons = false;
\tupdate_joycon_controls(joycon);
}
"""
text = replace_once(text, old, new, "wiimote handlers")
write(rel, text)

print("Cemu Joy-Con per-device orientation + multi-button hotkey V2 patch applied successfully.")
