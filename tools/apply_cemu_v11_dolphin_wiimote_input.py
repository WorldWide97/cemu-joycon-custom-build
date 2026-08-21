from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v11_dolphin_wiimote_input.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


controller_h = root / "src/input/api/SDL/SDLController.h"
controller_cpp = root / "src/input/api/SDL/SDLController.cpp"
wpad_cpp = root / "src/input/emulated/WPADController.cpp"
panel_h = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.h"
panel_cpp = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"

# =============================================================================
# 1) POINTER: preserve the proven V10 Dolphin quaternion core, but make the
#    presentation smooth and resistant to natural hand tremor.
#
#    V10 jumped directly to every sensor target and did not use the UI deadzone.
#    V11 applies a radial ANGULAR deadzone around the current pointer location,
#    subtracts the deadzone from motion above the threshold (no edge jump), and
#    uses time-based exponential interpolation. Smoothing=0 remains direct.
# =============================================================================
replace_once(
    controller_h,
    '''\tuint64 m_dolphin_pointer_last_sensor_timestamp = 0;\n\tbool m_dolphin_recenter_requested = true;\n\tglm::vec2 m_joycon_pointer_position{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_previous{ 0.5f, 0.5f };\n''',
    '''\tuint64 m_dolphin_pointer_last_sensor_timestamp = 0;\n\tuint64 m_dolphin_pointer_last_output_timestamp = 0;\n\tbool m_dolphin_recenter_requested = true;\n\tglm::vec2 m_dolphin_pointer_target{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_position{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_previous{ 0.5f, 0.5f };\n''',
    "add V11 pointer presentation state",
)

replace_once(
    controller_h,
    '''\tstd::atomic<float> m_pointer_deadzone_degrees{ 2.0f };\n\tstd::atomic<float> m_pointer_smoothing{ 0.01f };\n''',
    '''\t// V11 defaults: small angular tremor rejection + light temporal interpolation.\n\tstd::atomic<float> m_pointer_deadzone_degrees{ 0.35f };\n\tstd::atomic<float> m_pointer_smoothing{ 0.10f };\n''',
    "use V11 anti-tremor pointer defaults",
)

replace_once(
    controller_cpp,
    '''\t\tm_dolphin_recenter_requested = true;\n\t\tm_joycon_pointer_previous = m_joycon_pointer_position;\n''',
    '''\t\tm_dolphin_recenter_requested = true;\n\t\tm_dolphin_pointer_target = m_joycon_pointer_position;\n\t\tm_dolphin_pointer_last_output_timestamp = 0;\n\t\tm_joycon_pointer_previous = m_joycon_pointer_position;\n''',
    "reset V11 pointer presentation filter on recenter",
)

replace_once(
    controller_cpp,
    '''\t\tm_joycon_pointer_position = {0.5f,0.5f};\n\t\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\t\tm_joycon_pointer_initialized = true;\n''',
    '''\t\tm_dolphin_pointer_target = {0.5f,0.5f};\n\t\tm_joycon_pointer_position = {0.5f,0.5f};\n\t\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\t\tm_dolphin_pointer_last_output_timestamp = 0;\n\t\tm_joycon_pointer_initialized = true;\n''',
    "initialize V11 pointer presentation state",
)

replace_once(
    controller_cpp,
    '''\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\tm_joycon_pointer_position = target; // Dolphin-style direct response: no V9 smoothing.\n\tposition = m_joycon_pointer_position;\n\tprevious = m_joycon_pointer_previous;\n\treturn true;\n''',
    '''\t// V11 presentation layer. Keep Dolphin's quaternion/IMU result above untouched;\n\t// only suppress tiny hand tremor and interpolate the visible cursor between samples.\n\tconst float pointer_deadzone = get_pointer_deadzone_degrees() * kPi / 180.0f;\n\tconst glm::vec2 target_delta = target - m_joycon_pointer_position;\n\tconst glm::vec2 angular_delta{ target_delta.x * (2.0f * max_yaw), target_delta.y * (2.0f * max_pitch) };\n\tconst float angular_distance = glm::length(angular_delta);\n\n\tglm::vec2 filtered_target = target;\n\tif (pointer_deadzone > 0.0f && angular_distance <= pointer_deadzone)\n\t{\n\t\tfiltered_target = m_joycon_pointer_position;\n\t}\n\telse if (pointer_deadzone > 0.0f && angular_distance > 0.000001f)\n\t{\n\t\t// Subtract the threshold rather than jumping across it. Slow intentional\n\t\t// movement accumulates naturally until it exits the tremor radius.\n\t\tconst float active_fraction = (angular_distance - pointer_deadzone) / angular_distance;\n\t\tfiltered_target = m_joycon_pointer_position + target_delta * std::clamp(active_fraction, 0.0f, 1.0f);\n\t}\n\tm_dolphin_pointer_target = filtered_target;\n\n\tconst uint64 output_now = static_cast<uint64>(std::chrono::duration_cast<std::chrono::nanoseconds>(\n\t\tstd::chrono::steady_clock::now().time_since_epoch()).count());\n\tfloat output_dt = 1.0f / 120.0f;\n\tif (m_dolphin_pointer_last_output_timestamp != 0 && output_now > m_dolphin_pointer_last_output_timestamp)\n\t\toutput_dt = static_cast<float>(output_now - m_dolphin_pointer_last_output_timestamp) / 1000000000.0f;\n\tm_dolphin_pointer_last_output_timestamp = output_now;\n\toutput_dt = std::clamp(output_dt, 0.001f, 0.05f);\n\n\tconst float smoothing = get_pointer_smoothing();\n\tfloat follow = 1.0f;\n\tif (smoothing > 0.0001f)\n\t{\n\t\t// 0.10 ~= very light smoothing. Higher values deliberately trade latency\n\t\t// for steadiness; zero keeps the exact V10 direct response.\n\t\tconst float time_constant = 0.0025f + smoothing * 0.10f;\n\t\tfollow = 1.0f - std::exp(-output_dt / time_constant);\n\t}\n\n\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\tm_joycon_pointer_position += (m_dolphin_pointer_target - m_joycon_pointer_position) * std::clamp(follow, 0.0f, 1.0f);\n\tposition = m_joycon_pointer_position;\n\tprevious = m_joycon_pointer_previous;\n\treturn true;\n''',
    "add radial deadzone and time-based pointer interpolation",
)

replace_once(
    controller_cpp,
    '''\t\tm_dolphin_pointer_last_sensor_timestamp = 0;\n\t\tm_dolphin_recenter_requested = true;\n\t}\n''',
    '''\t\tm_dolphin_pointer_last_sensor_timestamp = 0;\n\t\tm_dolphin_pointer_last_output_timestamp = 0;\n\t\tm_dolphin_pointer_target = {0.5f, 0.5f};\n\t\tm_dolphin_recenter_requested = true;\n\t}\n''',
    "reset V11 pointer output filter on orientation change",
)

# Fresh defaults and migration of V10's exact unused UI defaults. A user-created
# custom value is preserved; only the exact V10 pair is migrated.
replace_once(
    controller_cpp,
    '''\tfloat pointer_deadzone = 2.0f;\n\tfloat pointer_smoothing = 0.01f;\n''',
    '''\tfloat pointer_deadzone = 0.35f;\n\tfloat pointer_smoothing = 0.10f;\n''',
    "V11 profile pointer defaults",
)
replace_once(
    controller_cpp,
    '''\tif (const auto value = node.child("joycon_pointer_smoothing")) pointer_smoothing = ConvertString<float>(value.child_value());\n\tif (const auto value = node.child("joycon_pointer_invert_x")) pointer_invert_x = ConvertString<int>(value.child_value()) != 0;\n''',
    '''\tif (const auto value = node.child("joycon_pointer_smoothing")) pointer_smoothing = ConvertString<float>(value.child_value());\n\t// V10 displayed 2.00 / 0.01 but did not actually use those fields. Migrate only\n\t// that exact pair to V11's practical anti-tremor defaults.\n\tif (std::abs(pointer_deadzone - 2.0f) < 0.001f && std::abs(pointer_smoothing - 0.01f) < 0.001f)\n\t{\n\t\tpointer_deadzone = 0.35f;\n\t\tpointer_smoothing = 0.10f;\n\t}\n\tif (const auto value = node.child("joycon_pointer_invert_x")) pointer_invert_x = ConvertString<int>(value.child_value()) != 0;\n''',
    "migrate V10 pointer defaults to active V11 defaults",
)

# =============================================================================
# 2) WIIMOTE KPAD MOTION: Cemu's accVertical member is KPAD's signed `down`
#    vector. Stock Cemu discarded the sign with abs(acc.x + acc.y), making a
#    left/right physical tilt indistinguishable. Preserve the sign.
# =============================================================================
replace_once(
    wpad_cpp,
    '''\t\tstatus.accVertical.x = std::min(1.0f, std::abs(acc.x + acc.y));\n\t\tstatus.accVertical.y = std::min(std::max(-1.0f, -acc.z), 1.0f);\n''',
    '''\t\t// KPAD calls this field `down`: it is a SIGNED 2D down vector from the\n\t\t// accelerometer. Never take abs() here; games such as Mario Kart and\n\t\t// Mario Party need the sign to distinguish left from right tilt.\n\t\tstatus.accVertical.x = std::clamp(acc.x + acc.y, -1.0f, 1.0f);\n\t\tstatus.accVertical.y = std::clamp(-acc.z, -1.0f, 1.0f);\n''',
    "preserve signed KPAD down vector for Wii Remote tilt",
)

# =============================================================================
# 3) INPUT UI: keep Cemu's physical controller page compact. The old V8 rows are
#    retained internally for compatibility/live refresh but hidden. Two buttons
#    open focused Dolphin-style dialogs: Pointer and Motion Input.
# =============================================================================
replace_once(
    panel_h,
    '''\twxButton* m_joycon_motion_reset = nullptr;\n\twxStaticText* m_joycon_motion_live = nullptr;\n\twxStaticText* m_joycon_status = nullptr;\n''',
    '''\twxButton* m_joycon_motion_reset = nullptr;\n\twxStaticText* m_joycon_motion_live = nullptr;\n\twxButton* m_joycon_pointer_dialog = nullptr;\n\twxButton* m_joycon_motion_dialog = nullptr;\n\twxStaticText* m_joycon_status = nullptr;\n''',
    "add compact V11 input dialog buttons",
)
replace_once(
    panel_h,
    '''\tvoid on_joycon_motion_reset(wxCommandEvent& event);\n\tvoid on_joycon_pointer_paint(wxPaintEvent& event);\n''',
    '''\tvoid on_joycon_motion_reset(wxCommandEvent& event);\n\tvoid on_joycon_pointer_dialog(wxCommandEvent& event);\n\tvoid on_joycon_motion_dialog(wxCommandEvent& event);\n\tvoid on_joycon_pointer_paint(wxPaintEvent& event);\n''',
    "declare V11 Dolphin-style input dialogs",
)
replace_once(
    panel_cpp,
    '''#include <wx/dcbuffer.h>\n''',
    '''#include <wx/dcbuffer.h>\n#include <wx/dialog.h>\n#include <wx/statbox.h>\n''',
    "V11 dialog includes",
)
replace_once(
    panel_cpp,
    '''\tjoycon_outer->Add(motion_sizer, 0, wxEXPAND);\n\n\tm_joycon_panel->SetSizer(joycon_outer);\n''',
    '''\tjoycon_outer->Add(motion_sizer, 0, wxEXPAND);\n\n\t// V11: the dense V8 rows remain alive for profile compatibility and live\n\t// refresh, but settings are presented through focused Dolphin-style dialogs.\n\tpointer_sizer->ShowItems(false);\n\tmotion_sizer->ShowItems(false);\n\tauto* dolphin_settings = new wxBoxSizer(wxHORIZONTAL);\n\tdolphin_settings->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Dolphin-style input:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);\n\tm_joycon_pointer_dialog = new wxButton(m_joycon_panel, wxID_ANY, _("Pointer..."));\n\tm_joycon_motion_dialog = new wxButton(m_joycon_panel, wxID_ANY, _("Motion Input..."));\n\tm_joycon_pointer_dialog->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_pointer_dialog, this);\n\tm_joycon_motion_dialog->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_motion_dialog, this);\n\tdolphin_settings->Add(m_joycon_pointer_dialog, 0, wxRIGHT, 6);\n\tdolphin_settings->Add(m_joycon_motion_dialog, 0, wxRIGHT, 8);\n\tdolphin_settings->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Each button opens all settings for that motion group.")), 1, wxALIGN_CENTER_VERTICAL);\n\tjoycon_outer->Add(dolphin_settings, 0, wxEXPAND | wxTOP, 3);\n\n\tm_joycon_panel->SetSizer(joycon_outer);\n''',
    "replace dense Joy-Con settings presentation with dialog buttons",
)

# Insert the two modal dialogs immediately before the existing recenter handler.
replace_once(
    panel_cpp,
    '''void WiimoteInputPanel::on_joycon_pointer_recenter(wxCommandEvent&)\n''',
    r'''void WiimoteInputPanel::on_joycon_pointer_dialog(wxCommandEvent&)
{
	const auto joycon = m_active_joycon.lock();
	if (!joycon)
		return;

	wxDialog dialog(this, wxID_ANY, _("Pointer - Dolphin Motion"), wxDefaultPosition, wxDefaultSize,
		wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
	auto* outer = new wxBoxSizer(wxVERTICAL);
	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Dolphin IMU pointer. Deadzone rejects small hand tremor; Smooth controls only visible-cursor interpolation.")),
		0, wxEXPAND | wxALL, 10);

	auto* box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Point"));
	auto* grid = new wxFlexGridSizer(2, 6, 10);
	grid->AddGrowableCol(1, 1);
	auto make_spin = [&](const wxString& label, double value, double minv, double maxv, double step, int digits) {
		grid->Add(new wxStaticText(&dialog, wxID_ANY, label), 0, wxALIGN_CENTER_VERTICAL);
		auto* spin = new wxSpinCtrlDouble(&dialog, wxID_ANY);
		spin->SetRange(minv, maxv);
		spin->SetIncrement(step);
		spin->SetDigits(digits);
		spin->SetValue(value);
		grid->Add(spin, 1, wxEXPAND);
		return spin;
	};

	auto* yaw = make_spin(_("Horizontal range / Yaw (degrees)"), joycon->get_pointer_yaw_degrees(), 5.0, 120.0, 1.0, 1);
	auto* pitch = make_spin(_("Vertical range / Pitch (degrees)"), joycon->get_pointer_pitch_degrees(), 5.0, 120.0, 1.0, 1);
	auto* deadzone = make_spin(_("Deadzone (degrees)"), joycon->get_pointer_deadzone_degrees(), 0.0, 5.0, 0.05, 2);
	auto* smoothing = make_spin(_("Smooth (0 = direct)"), joycon->get_pointer_smoothing(), 0.0, 0.95, 0.01, 2);
	box->Add(grid, 0, wxEXPAND | wxALL, 8);

	auto* flags = new wxBoxSizer(wxHORIZONTAL);
	auto* invert_x = new wxCheckBox(&dialog, wxID_ANY, _("Invert X"));
	auto* invert_y = new wxCheckBox(&dialog, wxID_ANY, _("Invert Y"));
	invert_x->SetValue(joycon->get_pointer_invert_x());
	invert_y->SetValue(joycon->get_pointer_invert_y());
	flags->Add(invert_x, 0, wxRIGHT, 10);
	flags->Add(invert_y, 0, wxRIGHT, 10);
	auto* recenter = new wxButton(&dialog, wxID_ANY, _("Recenter now"));
	recenter->Bind(wxEVT_BUTTON, [joycon](wxCommandEvent&) { joycon->recenter_joycon_pointer(); });
	flags->Add(recenter, 0);
	box->Add(flags, 0, wxLEFT | wxRIGHT | wxBOTTOM, 8);
	outer->Add(box, 0, wxEXPAND | wxLEFT | wxRIGHT, 10);

	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Recommended start: Deadzone 0.35 degrees, Smooth 0.10. Increase Deadzone first if your hand tremor is still visible.")),
		0, wxEXPAND | wxALL, 10);
	outer->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
	dialog.SetSizerAndFit(outer);
	dialog.SetMinSize(wxSize(560, -1));

	if (dialog.ShowModal() == wxID_OK)
	{
		joycon->set_pointer_calibration((float)yaw->GetValue(), (float)pitch->GetValue(),
			(float)deadzone->GetValue(), (float)smoothing->GetValue(), invert_x->GetValue(), invert_y->GetValue());
		joycon->recenter_joycon_pointer(false);
	}
}

void WiimoteInputPanel::on_joycon_motion_dialog(wxCommandEvent&)
{
	const auto joycon = m_active_joycon.lock();
	if (!joycon)
		return;

	wxDialog dialog(this, wxID_ANY, _("Motion Input - Dolphin Wii Remote"), wxDefaultPosition, wxDefaultSize,
		wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
	auto* outer = new wxBoxSizer(wxVERTICAL);
	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Joy-Con sensors are converted to Dolphin Wii Remote axes before Cemu KPAD/WPAD output.")),
		0, wxEXPAND | wxALL, 10);

	auto* orientation_box = new wxStaticBoxSizer(wxHORIZONTAL, &dialog, _("Joy-Con / Wii Remote orientation"));
	orientation_box->Add(new wxStaticText(&dialog, wxID_ANY, _("Physical orientation:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);
	auto* orientation = new wxChoice(&dialog, wxID_ANY);
	orientation->Append(_("Sideways"));
	orientation->Append(_("Vertical"));
	orientation->SetSelection(joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 1 : 0);
	orientation_box->Add(orientation, 0, wxRIGHT, 12);
	orientation_box->Add(new wxStaticText(&dialog, wxID_ANY,
		joycon->is_left_joycon() ? _("Joy-Con L Sideways: Dolphin -90 degree orientation") : _("Joy-Con R Sideways: proven Dolphin 180 degree fix")),
		1, wxALIGN_CENTER_VERTICAL);
	outer->Add(orientation_box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	float sx, sy, sz;
	joycon->get_motion_scale(sx, sy, sz);
	auto* accel_box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Accelerometer / motion calibration"));
	auto* grid = new wxFlexGridSizer(4, 6, 10);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Axis")), 0);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Scale")), 0);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Invert")), 0);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Dolphin semantic direction")), 0);
	auto add_axis = [&](const wxString& name, float value, const wxString& direction, wxSpinCtrlDouble*& spin, wxCheckBox*& invert) {
		grid->Add(new wxStaticText(&dialog, wxID_ANY, name), 0, wxALIGN_CENTER_VERTICAL);
		spin = new wxSpinCtrlDouble(&dialog, wxID_ANY);
		spin->SetRange(0.25, 2.0);
		spin->SetIncrement(0.05);
		spin->SetDigits(2);
		spin->SetValue(std::abs(value));
		grid->Add(spin, 0, wxEXPAND);
		invert = new wxCheckBox(&dialog, wxID_ANY, wxEmptyString);
		invert->SetValue(value < 0.0f);
		grid->Add(invert, 0, wxALIGN_CENTER);
		grid->Add(new wxStaticText(&dialog, wxID_ANY, direction), 0, wxALIGN_CENTER_VERTICAL);
	};
	wxSpinCtrlDouble *spin_x{}, *spin_y{}, *spin_z{};
	wxCheckBox *inv_x{}, *inv_y{}, *inv_z{};
	add_axis(_("X"), sx, _("Left / Right"), spin_x, inv_x);
	add_axis(_("Y"), sy, _("Forward / Backward"), spin_y, inv_y);
	add_axis(_("Z"), sz, _("Up / Down"), spin_z, inv_z);
	accel_box->Add(grid, 0, wxEXPAND | wxALL, 8);
	outer->Add(accel_box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto motion = joycon->get_motion_sample();
	float gyro[3]{}, acc[3]{};
	motion.getGyrometer(gyro);
	motion.getAccelerometer(acc);
	auto* gyro_box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Gyroscope"));
	gyro_box->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Dolphin auto calibration: 3.0 s stable mean | Dead zone: 2 degrees/s | minimum stable sampling: 25 Hz")),
		0, wxEXPAND | wxALL, 8);
	gyro_box->Add(new wxStaticText(&dialog, wxID_ANY,
		wxString::Format(_("Live snapshot - Gyro: %.3f  %.3f  %.3f | Acc: %.3f  %.3f  %.3f"),
			gyro[0], gyro[1], gyro[2], acc[0], acc[1], acc[2])), 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 8);
	outer->Add(gyro_box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* reset = new wxButton(&dialog, wxID_ANY, _("Reset motion scale"));
	reset->Bind(wxEVT_BUTTON, [=](wxCommandEvent&) {
		spin_x->SetValue(1.0); spin_y->SetValue(1.0); spin_z->SetValue(1.0);
		inv_x->SetValue(false); inv_y->SetValue(false); inv_z->SetValue(false);
	});
	outer->Add(reset, 0, wxLEFT | wxRIGHT | wxBOTTOM, 10);
	outer->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
	dialog.SetSizerAndFit(outer);
	dialog.SetMinSize(wxSize(650, -1));

	if (dialog.ShowModal() == wxID_OK)
	{
		joycon->set_joycon_orientation(orientation->GetSelection() == 1 ?
			SDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);
		auto signed_scale = [](wxSpinCtrlDouble* spin, wxCheckBox* invert) {
			const float value = (float)spin->GetValue();
			return invert->GetValue() ? -value : value;
		};
		joycon->set_motion_scale(signed_scale(spin_x, inv_x), signed_scale(spin_y, inv_y), signed_scale(spin_z, inv_z));
	}
}

void WiimoteInputPanel::on_joycon_pointer_recenter(wxCommandEvent&)
''',
    "add V11 Pointer and Motion Input dialogs",
)

print("Cemu Joy-Con V11 Dolphin Wii Remote input patch applied successfully.")
