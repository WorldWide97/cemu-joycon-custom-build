#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

PRE1257 = "4b9c7c0d307495c679127381d6f00bab9f0c2933"


def replace_cpp_function(text: str, signature: str, replacement: str) -> str:
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Function signature not found: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Function body not found: {signature}")
    depth = 0
    i = brace
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                return text[:start] + replacement.rstrip() + text[end:]
        i += 1
    raise RuntimeError(f"Unterminated function: {signature}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def replace_exact(text: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{label}: expected {expected} match(es), found {count}")
    return text.replace(old, new)


def text_between(text: str, start: str, end: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start anchor not found")
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        raise RuntimeError(f"{label}: end anchor not found")
    return text[start_index:end_index]


def copy_runtime_file(snapshot: Path, cemu: Path, rel: str) -> None:
    src = snapshot / rel
    dst = cemu / "src" / rel
    if not src.is_file():
        raise RuntimeError(f"V26 snapshot file missing: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"Copied exact V26 runtime file: src/{rel}")


def adapt_sdl_controller_header(snapshot: Path, cemu: Path) -> None:
    rel = "input/api/SDL/SDLController.h"
    text = (snapshot / rel).read_text(encoding="utf-8")
    replacements = [
        ("<SDL3/SDL_gamepad.h>", "<SDL2/SDL_gamecontroller.h>"),
        ("SDL_GUID", "SDL_JoystickGUID"),
        ("SDL_Gamepad*", "SDL_GameController*"),
        ("SDL_GAMEPAD_BUTTON_COUNT", "SDL_CONTROLLER_BUTTON_MAX"),
        ("SDL_GAMEPAD_AXIS_COUNT", "SDL_CONTROLLER_AXIS_MAX"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    if "SDL3/" in text or "SDL_GUID" in text or "SDL_GAMEPAD_" in text:
        raise RuntimeError("Unadapted SDL3 tokens remain in SDLController.h")
    write_text(cemu / "src" / rel, text)
    print("Adapted V26 SDLController.h to PRE SDL2")


def adapt_sdl_controller_cpp(snapshot: Path, cemu: Path) -> None:
    rel = "input/api/SDL/SDLController.cpp"
    text = (snapshot / rel).read_text(encoding="utf-8")

    replacements = [
        # Adapt the full SDL3 helper name before the generic SDL_GUID type
        # replacement. Otherwise SDL_GUIDToString becomes the nonexistent
        # SDL_JoystickGUIDToString and no longer matches this rule.
        ("SDL_GUIDToString", "SDL_JoystickGetGUIDString"),
        ("SDL_GUID", "SDL_JoystickGUID"),
        ("SDL_CloseGamepad", "SDL_GameControllerClose"),
        ("SDL_GetGamepadType", "SDL_GameControllerGetType"),
        ("SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT", "SDL_CONTROLLER_TYPE_NINTENDO_SWITCH_JOYCON_LEFT"),
        ("SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT", "SDL_CONTROLLER_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT"),
        ("SDL_GAMEPAD_BUTTON_COUNT", "SDL_CONTROLLER_BUTTON_MAX"),
        ("SDL_GAMEPAD_AXIS_COUNT", "SDL_CONTROLLER_AXIS_MAX"),
        ("SDL_GAMEPAD_BUTTON_SOUTH", "SDL_CONTROLLER_BUTTON_A"),
        ("SDL_GAMEPAD_BUTTON_EAST", "SDL_CONTROLLER_BUTTON_B"),
        ("SDL_GAMEPAD_BUTTON_WEST", "SDL_CONTROLLER_BUTTON_X"),
        ("SDL_GAMEPAD_BUTTON_NORTH", "SDL_CONTROLLER_BUTTON_Y"),
        ("SDL_GAMEPAD_AXIS_LEFTX", "SDL_CONTROLLER_AXIS_LEFTX"),
        ("SDL_GAMEPAD_AXIS_LEFTY", "SDL_CONTROLLER_AXIS_LEFTY"),
        ("SDL_GAMEPAD_AXIS_RIGHTX", "SDL_CONTROLLER_AXIS_RIGHTX"),
        ("SDL_GAMEPAD_AXIS_RIGHTY", "SDL_CONTROLLER_AXIS_RIGHTY"),
        ("SDL_GAMEPAD_AXIS_LEFT_TRIGGER", "SDL_CONTROLLER_AXIS_TRIGGERLEFT"),
        ("SDL_GAMEPAD_AXIS_RIGHT_TRIGGER", "SDL_CONTROLLER_AXIS_TRIGGERRIGHT"),
        ("SDL_GamepadButton", "SDL_GameControllerButton"),
        ("SDL_GamepadAxis", "SDL_GameControllerAxis"),
        ("SDL_GamepadConnected", "SDL_GameControllerGetAttached"),
        ("SDL_GetGamepadButton", "SDL_GameControllerGetButton"),
        ("SDL_GetGamepadAxis", "SDL_GameControllerGetAxis"),
        ("SDL_GetGamepadStringForButton", "SDL_GameControllerGetStringForButton"),
        ("SDL_GetGamepadName", "SDL_GameControllerName"),
        ("SDL_GamepadHasButton", "SDL_GameControllerHasButton"),
        ("SDL_GamepadHasAxis", "SDL_GameControllerHasAxis"),
        ("SDL_GamepadHasSensor", "SDL_GameControllerHasSensor"),
        ("SDL_SetGamepadSensorEnabled", "SDL_GameControllerSetSensorEnabled"),
        ("SDL_RumbleGamepad", "SDL_GameControllerRumble"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)

    # SDL2 sensor event timestamps are milliseconds; V26/SDL3 timestamps are ns.
    text = text.replace(
        "static_cast<float>(sensor_timestamp - m_dolphin_pointer_last_sensor_timestamp) / 1000000000.0f;",
        "static_cast<float>(sensor_timestamp - m_dolphin_pointer_last_sensor_timestamp) / 1000.0f;",
    )

    connect_impl = r'''bool SDLController::connect()
{
	if (is_connected())
		return true;

	m_has_rumble = false;
	const auto index = m_provider->get_index(m_guid_index, m_guid);
	if (index < 0)
		return false;

	std::scoped_lock lock(m_controller_mutex);
	m_diid = SDL_JoystickGetDeviceInstanceID(index);
	if (m_diid == -1)
		return false;

	m_controller = SDL_GameControllerOpen(index);
	if (!m_controller)
		return false;

	if (const char* name = SDL_GameControllerName(m_controller))
		m_display_name = name;

	for (size_t i = 0; i < SDL_CONTROLLER_BUTTON_MAX; ++i)
		m_buttons[i] = SDL_GameControllerHasButton(m_controller, (SDL_GameControllerButton)i);
	for (size_t i = 0; i < SDL_CONTROLLER_AXIS_MAX; ++i)
		m_axis[i] = SDL_GameControllerHasAxis(m_controller, (SDL_GameControllerAxis)i);

	if (SDL_GameControllerHasSensor(m_controller, SDL_SENSOR_ACCEL))
		m_has_accel = SDL_GameControllerSetSensorEnabled(m_controller, SDL_SENSOR_ACCEL, SDL_TRUE) == 0;
	if (SDL_GameControllerHasSensor(m_controller, SDL_SENSOR_GYRO))
		m_has_gyro = SDL_GameControllerSetSensorEnabled(m_controller, SDL_SENSOR_GYRO, SDL_TRUE) == 0;
	m_has_rumble = SDL_GameControllerRumble(m_controller, 0, 0, 0) == 0;

	if (is_joycon())
	{
		// Preserve V26 semantics: internal Sideways == physical Vertical.
		const bool physical_vertical = get_joycon_orientation() == JoyConOrientation::Sideways;
		m_provider->set_joycon_orientation(m_diid, is_left_joycon(), physical_vertical);
		m_provider->set_joycon_motion_scale(m_diid, 1.0f, 1.0f, 1.0f);
		m_provider->set_joycon_dolphin_motion_settings(m_diid,
			m_dolphin_gyro_deadzone_degrees.load(std::memory_order_relaxed),
			m_dolphin_calibration_period_seconds.load(std::memory_order_relaxed));
		m_provider->set_joycon_pointer_calibration_period(m_diid,
			m_pointer_calibration_period_seconds.load(std::memory_order_relaxed));
	}
	return true;
}'''
    text = replace_cpp_function(text, "bool SDLController::connect()", connect_impl)

    # SDL2 rumble returns 0 on success; the remaining calls are commands where
    # the return value is intentionally ignored.
    text = text.replace("m_has_rumble = SDL_GameControllerRumble(m_controller, 0, 0, 0);",
                        "m_has_rumble = SDL_GameControllerRumble(m_controller, 0, 0, 0) == 0;")

    bad = [
        "SDL3/",
        "SDL_GUID",
        "SDL_GAMEPAD_",
        "SDL_OpenGamepad",
        "SDL_GetGamepads",
        "SDL_JoystickGUIDToString",
    ]
    for token in bad:
        if token in text:
            raise RuntimeError(f"Unadapted SDL3 token in SDLController.cpp: {token}")
    write_text(cemu / "src" / rel, text)
    print("Adapted V26 SDLController.cpp to PRE SDL2")


def adapt_sdl_provider_header(snapshot: Path, cemu: Path) -> None:
    rel = "input/api/SDL/SDLControllerProvider.h"
    text = (snapshot / rel).read_text(encoding="utf-8")
    text = text.replace("<SDL3/SDL_joystick.h>", "<SDL2/SDL_joystick.h>")
    text = text.replace("SDL_GUID", "SDL_JoystickGUID")
    if "SDL3/" in text or "SDL_GUID" in text:
        raise RuntimeError("Unadapted SDL3 token in SDLControllerProvider.h")
    write_text(cemu / "src" / rel, text)
    print("Adapted V26 SDLControllerProvider.h to PRE SDL2")


def adapt_sdl_provider_cpp(snapshot: Path, cemu: Path) -> None:
    rel = "input/api/SDL/SDLControllerProvider.cpp"
    text = (snapshot / rel).read_text(encoding="utf-8")

    text = text.replace("<SDL3/SDL.h>", "<SDL2/SDL.h>")
    text = text.replace("SDL_GUID", "SDL_JoystickGUID")

    event_replacements = [
        ("SDL_EVENT_QUIT", "SDL_QUIT"),
        ("SDL_EVENT_GAMEPAD_AXIS_MOTION", "SDL_CONTROLLERAXISMOTION"),
        ("SDL_EVENT_GAMEPAD_BUTTON_DOWN", "SDL_CONTROLLERBUTTONDOWN"),
        ("SDL_EVENT_GAMEPAD_BUTTON_UP", "SDL_CONTROLLERBUTTONUP"),
        ("SDL_EVENT_GAMEPAD_ADDED", "SDL_CONTROLLERDEVICEADDED"),
        ("SDL_EVENT_GAMEPAD_REMOVED", "SDL_CONTROLLERDEVICEREMOVED"),
        ("SDL_EVENT_GAMEPAD_REMAPPED", "SDL_CONTROLLERDEVICEREMAPPED"),
        ("SDL_EVENT_GAMEPAD_TOUCHPAD_DOWN", "SDL_CONTROLLERTOUCHPADDOWN"),
        ("SDL_EVENT_GAMEPAD_TOUCHPAD_MOTION", "SDL_CONTROLLERTOUCHPADMOTION"),
        ("SDL_EVENT_GAMEPAD_TOUCHPAD_UP", "SDL_CONTROLLERTOUCHPADUP"),
        ("SDL_EVENT_GAMEPAD_SENSOR_UPDATE", "SDL_CONTROLLERSENSORUPDATE"),
        ("event.gdevice", "event.cdevice"),
        ("event.gsensor", "event.csensor"),
    ]
    for old, new in event_replacements:
        text = text.replace(old, new)

    # SDL2 controller sensor timestamps are milliseconds rather than SDL3 ns.
    text = text.replace("10000000000", "10000")
    text = text.replace(" * 1000000000.0f", " * 1000.0f")
    text = text.replace(" / 1000000000.0;", " / 1000.0;")
    text = text.replace(" / 1000000000.0f;", " / 1000.0f;")

    get_controllers_impl = r'''std::vector<std::shared_ptr<ControllerBase>> SDLControllerProvider::get_controllers()
{
	std::vector<std::shared_ptr<ControllerBase>> result;
	std::unordered_map<SDL_JoystickGUID, size_t, SDL_JoystickGUIDHash> guid_counter;
	TempState lock(SDL_LockJoysticks, SDL_UnlockJoysticks);
	for (int i = 0; i < SDL_NumJoysticks(); ++i)
	{
		if (SDL_JoystickGetDeviceType(i) != SDL_JOYSTICK_TYPE_GAMECONTROLLER)
			continue;
		const auto guid = SDL_JoystickGetDeviceGUID(i);
		const auto it = guid_counter.try_emplace(guid, 0);
		if (auto* controller = SDL_GameControllerOpen(i))
		{
			const char* name = SDL_GameControllerName(controller);
			if (name)
				result.emplace_back(std::make_shared<SDLController>(guid, it.first->second, name));
			else
				result.emplace_back(std::make_shared<SDLController>(guid, it.first->second));
			SDL_GameControllerClose(controller);
		}
		else
			result.emplace_back(std::make_shared<SDLController>(guid, it.first->second));
		++it.first->second;
	}
	return result;
}'''
    get_index_impl = r'''int SDLControllerProvider::get_index(size_t guid_index, const SDL_JoystickGUID& guid) const
{
	size_t index = 0;
	TempState lock(SDL_LockJoysticks, SDL_UnlockJoysticks);
	for (int i = 0; i < SDL_NumJoysticks(); ++i)
	{
		if (SDL_JoystickGetDeviceType(i) != SDL_JOYSTICK_TYPE_GAMECONTROLLER)
			continue;
		if (guid == SDL_JoystickGetDeviceGUID(i))
		{
			if (index == guid_index)
				return i;
			++index;
		}
	}
	return -1;
}'''
    init_impl = r'''void SDLControllerProvider::InitSDL()
{
	SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS4, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS5, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS4_RUMBLE, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS5_RUMBLE, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_GAMECUBE, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_JOY_CONS, "1");
	// Critical V26 behavior: expose L/R separately and keep SDL in mini-gamepad basis.
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS, "0");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS, "0");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_STADIA, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_STEAM, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_LUNA, "1");

	if (SDL_InitSubSystem(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER | SDL_INIT_HAPTIC | SDL_INIT_EVENTS) < 0)
		throw std::runtime_error(fmt::format("couldn't initialize SDL: {}", SDL_GetError()));
	if (SDL_GameControllerEventState(SDL_ENABLE) < 0)
		cemuLog_log(LogType::Force, "Couldn't enable SDL gamecontroller event polling: {}", SDL_GetError());
}'''
    shutdown_impl = r'''void SDLControllerProvider::ShutdownSDL()
{
	SDL_QuitSubSystem(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER | SDL_INIT_HAPTIC | SDL_INIT_EVENTS);
}'''

    text = replace_cpp_function(text, "std::vector<std::shared_ptr<ControllerBase>> SDLControllerProvider::get_controllers()", get_controllers_impl)
    text = replace_cpp_function(text, "int SDLControllerProvider::get_index(size_t guid_index, const SDL_JoystickGUID& guid) const", get_index_impl)
    text = replace_cpp_function(text, "void SDLControllerProvider::InitSDL()", init_impl)
    text = replace_cpp_function(text, "void SDLControllerProvider::ShutdownSDL()", shutdown_impl)

    # SDL2 has no Switch 2 hint and no SDL3 gamepad enumeration/event helpers.
    text = re.sub(r'^.*SDL_HINT_JOYSTICK_HIDAPI_SWITCH2.*\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'^.*SDL_HINT_JOYSTICK_ENHANCED_REPORTS.*\n', '', text, flags=re.MULTILINE)

    bad = ["SDL3/", "SDL_GUID", "SDL_EVENT_GAMEPAD", "event.gsensor", "event.gdevice",
           "SDL_GetGamepads", "SDL_GetGamepad", "SDL_SetGamepadEventsEnabled", "SDL_GamepadEventsEnabled",
           "SDL_INIT_GAMEPAD"]
    for token in bad:
        if token in text:
            raise RuntimeError(f"Unadapted SDL3 token in SDLControllerProvider.cpp: {token}")

    write_text(cemu / "src" / rel, text)
    print("Adapted V26 SDLControllerProvider.cpp to PRE SDL2, preserving V26 motion/calibration math")


def adapt_input_settings_gui(cemu: Path) -> None:
    """Backport only V26's resizable/scrolled input layout onto PRE's wx GUI."""
    path = cemu / "src/gui/input/InputSettings2.cpp"
    text = path.read_text(encoding="utf-8")
    replacements = [
        (
            "#include <wx/bmpbuttn.h>\n",
            "#include <wx/bmpbuttn.h>\n#include <wx/scrolwin.h>\n",
            "add wxScrolledWindow include",
        ),
        (
            ': wxDialog(parent, wxID_ANY, _("Input settings"))',
            ': wxDialog(parent, wxID_ANY, _("Input settings"), wxDefaultPosition, wxDefaultSize, wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER | wxMAXIMIZE_BOX)',
            "make input settings resizable",
        ),
        (
            "\t\tauto* page = new wxPanel(m_notebook, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxTAB_TRAVERSAL);\n",
            "\t\tauto* page = new wxScrolledWindow(m_notebook, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxTAB_TRAVERSAL | wxVSCROLL);\n\t\tpage->SetScrollRate(0, 12);\n",
            "use scrolled controller pages",
        ),
        (
            "\tFit();\n\n    panel->Hide();",
            "\tFit();\n\tSetMinSize(wxSize(700, 500));\n\tSetSize(wxSize(1000, 720));\n\n    panel->Hide();",
            "set useful V26 input window size",
        ),
        (
            "\tauto* sizer = new wxGridBagSizer();\n\n\t{",
            "\tauto* sizer = new wxGridBagSizer();\n\tsizer->AddGrowableCol(1, 1);\n\tsizer->AddGrowableRow(7, 1);\n\n\t{",
            "grow controller page content",
        ),
        (
            "\tpage->SetSizer(sizer);\n\tpage->Layout();\n\n\tpage->SetClientObject",
            "\tpage->SetSizer(sizer);\n\tpage->Layout();\n\tif (auto* scrolled = dynamic_cast<wxScrolledWindow*>(page))\n\t\tscrolled->FitInside();\n\n\tpage->SetClientObject",
            "fit initial scrolled controller page",
        ),
        (
            "\t\tpage->wxWindowBase::Layout();\n\t\tpage->wxWindow::Update();",
            "\t\tpage->wxWindowBase::Layout();\n\t\tif (auto* scrolled = dynamic_cast<wxScrolledWindow*>(page))\n\t\t\tscrolled->FitInside();\n\t\tpage->wxWindow::Update();",
            "refit controller page after panel changes",
        ),
    ]
    for old, new, label in replacements:
        text = replace_exact(text, old, new, label)
    text = replace_exact(
        text,
        "panel_sizer->Add(panel, 0, wxEXPAND);",
        "panel_sizer->Add(panel, 1, wxEXPAND);",
        "let V26 controller panels expand",
        expected=2,
    )
    write_text(path, text)
    print("Adapted V26 resizable/scrolled input settings layout to PRE GUI")


def adapt_wiimote_settings_gui(snapshot: Path, cemu: Path) -> None:
    """Move V26 Joy-Con controls/dialogs while retaining PRE's pairing UI."""
    final_cpp = (snapshot / "gui/wxgui/input/panels/WiimoteInputPanel.cpp").read_text(encoding="utf-8")
    final_header = (snapshot / "gui/wxgui/input/panels/WiimoteInputPanel.h").read_text(encoding="utf-8")

    cpp_path = cemu / "src/gui/input/panels/WiimoteInputPanel.cpp"
    cpp = cpp_path.read_text(encoding="utf-8")
    cpp = replace_exact(
        cpp,
        "#include <wx/checkbox.h>\n",
        "#include <wx/checkbox.h>\n#include <wx/choice.h>\n#include <wx/spinctrl.h>\n#include <wx/dcbuffer.h>\n#include <wx/dialog.h>\n#include <wx/statbox.h>\n#include <wx/settings.h>\n#include <wx/timer.h>\n#include <cmath>\n#include <utility>\n",
        "add V26 Joy-Con GUI dependencies",
    )
    cpp = replace_exact(
        cpp,
        '#include "input/emulated/WiimoteController.h"\n',
        '#include "input/emulated/WiimoteController.h"\n#include "input/api/SDL/SDLController.h"\n',
        "connect Wiimote panel to SDL Joy-Con runtime",
    )

    constructor_start = "\tmain_sizer->Add(horiz_main_sizer, 0, wxEXPAND | wxALL, 5);\n"
    constructor_end = "\tmain_sizer->Add(new wxStaticLine(this), 0, wxLEFT | wxRIGHT | wxTOP | wxEXPAND, 5);"
    constructor_block = text_between(final_cpp, constructor_start, constructor_end, "extract V26 Joy-Con settings panel")
    cpp = replace_exact(cpp, constructor_start, constructor_block, "insert V26 Joy-Con settings panel")

    timer_start = "\tInputPanel::on_timer(emulated_controller, controller);\n\n"
    timer_end = "\tif (emulated_controller)\n"
    timer_block = text_between(final_cpp, timer_start, timer_end, "extract V26 live Joy-Con UI refresh")
    cpp = replace_exact(cpp, timer_start, timer_block, "insert V26 live Joy-Con UI refresh")

    methods_start = "wxString WiimoteInputPanel::joycon_hotkey_label"
    methods_end = "void WiimoteInputPanel::load_controller"
    methods = text_between(final_cpp, methods_start, methods_end, "extract V26 Joy-Con settings methods")
    cpp = replace_exact(cpp, methods_end, methods + methods_end, "insert V26 Joy-Con settings methods")
    write_text(cpp_path, cpp)

    header_path = cemu / "src/gui/input/panels/WiimoteInputPanel.h"
    header = header_path.read_text(encoding="utf-8")
    forward_start = "class wxChoice;"
    forward_end = "\n\nclass WiimoteInputPanel"
    forward_declarations = text_between(final_header, forward_start, forward_end, "extract V26 GUI forward declarations")
    header = replace_exact(
        header,
        "class wxInputDraw;\n",
        "class wxInputDraw;\n" + forward_declarations + "\n\n",
        "add V26 GUI forward declarations",
    )
    fields_start = "\tenum class JoyConHotkeyCapture"
    fields_end = "\tvoid add_button_row"
    fields = text_between(final_header, fields_start, fields_end, "extract V26 Joy-Con GUI state")
    header = replace_exact(header, fields_end, fields + fields_end, "add V26 Joy-Con GUI state")
    write_text(header_path, header)
    print("Adapted exact V26 Joy-Con settings UI/dialogs to PRE paths while retaining PRE pairing")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cemu", nargs="?", default="cemu")
    ap.add_argument("--wrapper", default=None)
    ap.add_argument("--with-gui", action="store_true")
    args = ap.parse_args()

    cemu = Path(args.cemu).resolve()
    wrapper = Path(args.wrapper).resolve() if args.wrapper else Path(__file__).resolve().parents[1]
    snapshot = wrapper / "generated" / "v26-final" / "src"

    if not (cemu / ".git").exists():
        raise RuntimeError(f"Cemu checkout not found: {cemu}")
    if not snapshot.is_dir():
        raise RuntimeError(f"V26 snapshot not found: {snapshot}")

    # Exact V26 runtime logic that is API-compatible with PRE.
    for rel in [
        "input/motion/Mahony.h",
        "input/motion/MotionHandler.h",
        "input/emulated/WPADController.h",
        "input/emulated/WPADController.cpp",
    ]:
        copy_runtime_file(snapshot, cemu, rel)

    # The only large compatibility boundary is SDL3 (V26) -> SDL2 (PRE-1257).
    adapt_sdl_provider_header(snapshot, cemu)
    adapt_sdl_provider_cpp(snapshot, cemu)
    adapt_sdl_controller_header(snapshot, cemu)
    adapt_sdl_controller_cpp(snapshot, cemu)

    if args.with_gui:
        adapt_input_settings_gui(cemu)
        adapt_wiimote_settings_gui(snapshot, cemu)

    runtime_files = [
        "src/input/api/SDL/SDLController.cpp",
        "src/input/api/SDL/SDLController.h",
        "src/input/api/SDL/SDLControllerProvider.cpp",
        "src/input/api/SDL/SDLControllerProvider.h",
        "src/input/emulated/WPADController.cpp",
        "src/input/emulated/WPADController.h",
        "src/input/motion/Mahony.h",
        "src/input/motion/MotionHandler.h",
    ]
    for rel in runtime_files:
        if not (cemu / rel).is_file():
            raise RuntimeError(f"Backport output missing: {rel}")

    print("V33 PRE-1257 + V26 runtime-core backport generated successfully.")
    if args.with_gui:
        print("V26 Joy-Con settings GUI was semantically adapted to PRE while preserving PRE-only pairing behavior.")
    else:
        print("GUI/LatteTiming are intentionally excluded from this diagnostic build so Wii Party U core and Joy-Con runtime are isolated first.")


if __name__ == "__main__":
    main()
