#include "wxgui/input/panels/WiimoteInputPanel.h"

#include <wx/button.h>
#include <wx/gbsizer.h>
#include <wx/stattext.h>
#include <wx/statline.h>
#include <wx/textctrl.h>
#include <wx/slider.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/spinctrl.h>
#include <wx/dcbuffer.h>
#include <wx/dialog.h>
#include <wx/statbox.h>
#include <wx/settings.h>
#include <wx/timer.h>
#include <cmath>
#include <utility>

#include "wxgui/helpers/wxControlObject.h"
#include "input/emulated/WiimoteController.h"
#include "input/api/SDL/SDLController.h"
#include "wxgui/helpers/wxHelpers.h"
#include "wxgui/components/wxInputDraw.h"

constexpr WiimoteController::ButtonId g_kFirstColumnItems[] =
{
	WiimoteController::kButtonId_A, WiimoteController::kButtonId_B, WiimoteController::kButtonId_1, WiimoteController::kButtonId_2, WiimoteController::kButtonId_Plus, WiimoteController::kButtonId_Minus, WiimoteController::kButtonId_Home
};

constexpr WiimoteController::ButtonId g_kSecondColumnItems[] =
{
	WiimoteController::kButtonId_Up, WiimoteController::kButtonId_Down, WiimoteController::kButtonId_Left, WiimoteController::kButtonId_Right
};

constexpr WiimoteController::ButtonId g_kThirdColumnItems[] =
{
	WiimoteController::kButtonId_Nunchuck_C, WiimoteController::kButtonId_Nunchuck_Z,
	WiimoteController::kButtonId_None,
	WiimoteController::kButtonId_Nunchuck_Up,WiimoteController::kButtonId_Nunchuck_Down,WiimoteController::kButtonId_Nunchuck_Left,WiimoteController::kButtonId_Nunchuck_Right
};

WiimoteInputPanel::WiimoteInputPanel(wxWindow* parent)
	: InputPanel(parent)
{
	auto bold_font = GetFont();
	bold_font.MakeBold();

	auto* main_sizer = new wxBoxSizer(wxVERTICAL);
    auto* horiz_main_sizer = new wxBoxSizer(wxHORIZONTAL);

    auto* extensions_sizer = new wxBoxSizer(wxHORIZONTAL);
    horiz_main_sizer->Add(extensions_sizer, wxSizerFlags(0).Align(wxALIGN_CENTER_VERTICAL));

    extensions_sizer->Add(new wxStaticText(this, wxID_ANY, _("Extensions:")));
    extensions_sizer->AddSpacer(10);

	m_motion_plus = new wxCheckBox(this, wxID_ANY, _("MotionPlus"));
	m_motion_plus->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_extension_change, this);
	extensions_sizer->Add(m_motion_plus);

	m_nunchuck = new wxCheckBox(this, wxID_ANY, _("Nunchuck"));
	m_nunchuck->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_extension_change, this);
	extensions_sizer->Add(m_nunchuck);

	m_classic = new wxCheckBox(this, wxID_ANY, _("Classic"));
	m_classic->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_extension_change, this);
	m_classic->Hide();
	extensions_sizer->Add(m_classic);

	main_sizer->Add(horiz_main_sizer, 0, wxEXPAND | wxALL, 5);

	m_joycon_panel = new wxPanel(this, wxID_ANY);
	auto* joycon_sizer = new wxBoxSizer(wxHORIZONTAL);
	m_joycon_name = new wxStaticText(m_joycon_panel, wxID_ANY, _("Joy-Con"));
	m_joycon_name->SetFont(bold_font);
	joycon_sizer->Add(m_joycon_name, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);
	joycon_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Orientation:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);
	m_joycon_orientation = new wxChoice(m_joycon_panel, wxID_ANY);
	m_joycon_orientation->Append(_("Sideways"));
	m_joycon_orientation->Append(_("Vertical"));
	m_joycon_orientation->SetSelection(0);
	m_joycon_orientation->Bind(wxEVT_CHOICE, &WiimoteInputPanel::on_joycon_orientation_change, this);
	joycon_sizer->Add(m_joycon_orientation, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 12);
	m_joycon_sideways_hotkey = new wxButton(m_joycon_panel, wxID_ANY, _("Sideways hotkey: Not set"));
	m_joycon_vertical_hotkey = new wxButton(m_joycon_panel, wxID_ANY, _("Vertical hotkey: Not set"));
	m_joycon_sideways_hotkey->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_hotkey_click, this);
	m_joycon_vertical_hotkey->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_hotkey_click, this);
	m_joycon_sideways_hotkey->Bind(wxEVT_RIGHT_UP, &WiimoteInputPanel::on_joycon_hotkey_clear, this);
	m_joycon_vertical_hotkey->Bind(wxEVT_RIGHT_UP, &WiimoteInputPanel::on_joycon_hotkey_clear, this);
	m_joycon_sideways_hotkey->SetToolTip(_("Click, release all controller buttons, then press and release a 2+ button combo. Right-click to clear."));
	m_joycon_vertical_hotkey->SetToolTip(_("Click, release all controller buttons, then press and release a 2+ button combo. Right-click to clear."));
	joycon_sizer->Add(m_joycon_sideways_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);
	joycon_sizer->Add(m_joycon_vertical_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);
	m_joycon_pointer_enabled = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Pointer enabled"));
	m_joycon_pointer_enabled->SetValue(true);
	m_joycon_pointer_enabled->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_pointer_enable, this);
	joycon_sizer->Add(m_joycon_pointer_enabled, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);
	m_joycon_pointer_hotkey = new wxButton(m_joycon_panel, wxID_ANY, _("Pointer hotkey: Not set"));
	m_joycon_pointer_hotkey->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_hotkey_click, this);
	m_joycon_pointer_hotkey->Bind(wxEVT_RIGHT_UP, &WiimoteInputPanel::on_joycon_hotkey_clear, this);
	m_joycon_pointer_hotkey->SetToolTip(_("Click, release all controller buttons, then press and release a 2+ button combo to toggle pointer ON/OFF. Right-click to clear."));
	joycon_sizer->Add(m_joycon_pointer_hotkey, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 10);
	m_joycon_status = new wxStaticText(m_joycon_panel, wxID_ANY, _("Hotkeys are independent for each Joy-Con."));
	joycon_sizer->Add(m_joycon_status, 1, wxALIGN_CENTER_VERTICAL);
	auto* joycon_outer = new wxBoxSizer(wxVERTICAL);
	joycon_outer->Add(joycon_sizer, 0, wxEXPAND | wxBOTTOM, 5);

	auto* pointer_sizer = new wxBoxSizer(wxHORIZONTAL);
	m_joycon_pointer_preview = new wxPanel(m_joycon_panel, wxID_ANY, wxDefaultPosition, wxSize(180, 95), wxBORDER_SIMPLE);
	m_joycon_pointer_preview->SetMinSize(wxSize(180, 95));
	m_joycon_pointer_preview->SetBackgroundStyle(wxBG_STYLE_PAINT);
	m_joycon_pointer_preview->Bind(wxEVT_PAINT, &WiimoteInputPanel::on_joycon_pointer_paint, this);
	pointer_sizer->Add(m_joycon_pointer_preview, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);
	m_joycon_pointer_recenter = new wxButton(m_joycon_panel, wxID_ANY, _("Recenter pointer"));
	m_joycon_pointer_recenter->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_pointer_recenter, this);
	pointer_sizer->Add(m_joycon_pointer_recenter, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);

	auto make_spin = [this, pointer_sizer](const wxString& label, double value, double min_value, double max_value, double increment, int digits) {
		pointer_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, label), 0, wxLEFT | wxRIGHT | wxALIGN_CENTER_VERTICAL, 3);
		auto* spin = new wxSpinCtrlDouble(m_joycon_panel, wxID_ANY);
		spin->SetRange(min_value, max_value);
		spin->SetIncrement(increment);
		spin->SetDigits(digits);
		spin->SetValue(value);
		spin->SetMinSize(wxSize(72, -1));
		spin->Bind(wxEVT_TEXT, &WiimoteInputPanel::on_joycon_pointer_settings, this);
		pointer_sizer->Add(spin, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);
		return spin;
	};
	m_joycon_pointer_yaw = make_spin(_("Yaw °"), 25.0, 5.0, 120.0, 1.0, 1);
	m_joycon_pointer_pitch = make_spin(_("Pitch °"), 20.0, 5.0, 120.0, 1.0, 1);
	m_joycon_pointer_deadzone = make_spin(_("Deadzone °"), 0.15, 0.0, 5.0, 0.05, 2);
	m_joycon_pointer_smoothing = make_spin(_("Smooth"), 0.08, 0.0, 0.95, 0.01, 2);
	m_joycon_pointer_invert_x = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert X"));
	m_joycon_pointer_invert_y = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert Y"));
	m_joycon_pointer_invert_x->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_pointer_settings, this);
	m_joycon_pointer_invert_y->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_pointer_settings, this);
	pointer_sizer->Add(m_joycon_pointer_invert_x, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);
	pointer_sizer->Add(m_joycon_pointer_invert_y, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);
	joycon_outer->Add(pointer_sizer, 0, wxEXPAND | wxBOTTOM, 5);

	auto* motion_sizer = new wxBoxSizer(wxHORIZONTAL);
	motion_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Motion calibration:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 6);
	auto make_motion_spin = [this, motion_sizer](const wxString& label) {
		motion_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, label), 0, wxLEFT | wxRIGHT | wxALIGN_CENTER_VERTICAL, 3);
		auto* spin = new wxSpinCtrlDouble(m_joycon_panel, wxID_ANY);
		spin->SetRange(0.25, 2.0);
		spin->SetIncrement(0.05);
		spin->SetDigits(2);
		spin->SetValue(1.0);
		spin->SetMinSize(wxSize(70, -1));
		spin->Bind(wxEVT_TEXT, &WiimoteInputPanel::on_joycon_motion_settings, this);
		motion_sizer->Add(spin, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 4);
		return spin;
	};
	m_joycon_motion_x = make_motion_spin(_("X"));
	m_joycon_motion_y = make_motion_spin(_("Y"));
	m_joycon_motion_z = make_motion_spin(_("Z"));
	m_joycon_motion_invert_x = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert X"));
	m_joycon_motion_invert_y = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert Y"));
	m_joycon_motion_invert_z = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert Z"));
	for (auto* checkbox : { m_joycon_motion_invert_x, m_joycon_motion_invert_y, m_joycon_motion_invert_z })
		checkbox->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_motion_settings, this);
	motion_sizer->Add(m_joycon_motion_invert_x, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 4);
	motion_sizer->Add(m_joycon_motion_invert_y, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 4);
	motion_sizer->Add(m_joycon_motion_invert_z, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);
	m_joycon_motion_reset = new wxButton(m_joycon_panel, wxID_ANY, _("Reset motion"));
	m_joycon_motion_reset->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_motion_reset, this);
	motion_sizer->Add(m_joycon_motion_reset, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);
	m_joycon_motion_live = new wxStaticText(m_joycon_panel, wxID_ANY, _("Gyro 0 0 0 | Acc 0 0 0 | Pointer 50% 50%"));
	motion_sizer->Add(m_joycon_motion_live, 1, wxALIGN_CENTER_VERTICAL);
	joycon_outer->Add(motion_sizer, 0, wxEXPAND);

	// V11: the dense V8 rows remain alive for profile compatibility and live
	// refresh, but settings are presented through focused Dolphin-style dialogs.
	pointer_sizer->ShowItems(false);
	motion_sizer->ShowItems(false);
	auto* dolphin_settings = new wxBoxSizer(wxHORIZONTAL);
	dolphin_settings->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Dolphin-style input:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);
	m_joycon_motion_dialog = new wxButton(m_joycon_panel, wxID_ANY, _("Motion Input..."));
	m_joycon_motion_dialog->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_motion_dialog, this);
	dolphin_settings->Add(m_joycon_motion_dialog, 0, wxRIGHT, 8);
	dolphin_settings->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Point and motion settings are combined in one Dolphin-style window.")), 1, wxALIGN_CENTER_VERTICAL);
	joycon_outer->Add(dolphin_settings, 0, wxEXPAND | wxTOP, 3);

	m_joycon_panel->SetSizer(joycon_outer);
	m_joycon_panel->Hide();
	main_sizer->Add(m_joycon_panel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 5);

	main_sizer->Add(new wxStaticLine(this), 0, wxLEFT | wxRIGHT | wxTOP | wxEXPAND, 5);

	m_item_sizer = new wxGridBagSizer();

	sint32 row = 0;
	sint32 column = 0;
	for (const auto& id : g_kFirstColumnItems)
	{
		row++;
		add_button_row(row, column, id);
	}

	m_item_sizer->Add(new wxStaticLine(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVERTICAL), wxGBPosition(0, column + 2), wxGBSpan(11, 1), wxLEFT | wxRIGHT | wxBOTTOM | wxEXPAND, 5);

	//////////////////////////////////////////////////////////////////

	row = 0;
	column += 3;

	auto text = new wxStaticText(this, wxID_ANY, _("D-pad"));
	text->SetFont(bold_font);
	m_item_sizer->Add(text, wxGBPosition(row, column), wxGBSpan(1, 3), wxALL | wxEXPAND, 5);

	for (const auto& id : g_kSecondColumnItems)
	{
		row++;
		add_button_row(row, column, id);
	}

	row = 8;
	// Volume
	text = new wxStaticText(this, wxID_ANY, _("Volume"));
	text->Disable();
	m_item_sizer->Add(text, wxGBPosition(row, column), wxDefaultSpan, wxALL, 5);

	m_volume = new wxSlider(this, wxID_ANY, 0, 0, 100);
	m_volume->Disable();
	m_item_sizer->Add(m_volume, wxGBPosition(row, column + 1), wxDefaultSpan, wxTOP | wxBOTTOM | wxEXPAND, 5);

	const auto volume_text = new wxStaticText(this, wxID_ANY, wxString::Format("%d%%", 0));
	volume_text->Disable();
	m_item_sizer->Add(volume_text, wxGBPosition(row, column + 2), wxDefaultSpan, wxALL, 5);
	m_volume->Bind(wxEVT_SLIDER, &WiimoteInputPanel::on_volume_change, this, wxID_ANY, wxID_ANY, new wxControlObject(volume_text));
	row++;

	m_item_sizer->Add(new wxStaticLine(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVERTICAL), wxGBPosition(0, column + 3), wxGBSpan(11, 1), wxLEFT | wxRIGHT | wxBOTTOM | wxEXPAND, 5);

	//////////////////////////////////////////////////////////////////

	row = 0;
	column += 4;

	text = new wxStaticText(this, wxID_ANY, _("Nunchuck"));
	text->SetFont(bold_font);
	m_item_sizer->Add(text, wxGBPosition(row, column), wxGBSpan(1, 3), wxALL | wxEXPAND, 5);

	for (const auto& id : g_kThirdColumnItems)
	{
		row++;
		if (id == WiimoteController::kButtonId_None)
			continue;

		m_item_sizer->Add(
			new wxStaticText(this, wxID_ANY, wxGetTranslation(wxString::FromUTF8(WiimoteController::get_button_name(id)))),
			wxGBPosition(row, column),
			wxDefaultSpan,
			wxALL | wxALIGN_CENTER_VERTICAL, 5);

		auto* text_ctrl = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTAB_TRAVERSAL | wxTE_PROCESS_ENTER | wxTE_PROCESS_TAB);
		text_ctrl->SetClientData((void*)id);
		text_ctrl->SetMinSize(wxSize(150, -1));
		text_ctrl->SetEditable(false);
		text_ctrl->SetBackgroundColour(kKeyColourNormalMode);
		bind_hotkey_events(text_ctrl);
		text_ctrl->Enable(m_nunchuck->GetValue());
		m_item_sizer->Add(text_ctrl, wxGBPosition(row, column + 1), wxDefaultSpan, wxALL | wxEXPAND, 5);

		m_nunchuck_items.push_back(text_ctrl);
	}


	// input drawer
	m_draw = new wxInputDraw(this, wxID_ANY, wxDefaultPosition, { 60, 60 });
	m_draw->Enable(m_nunchuck->GetValue());
	m_item_sizer->Add(5, 0, wxGBPosition(3, column + 3), wxDefaultSpan, wxTOP | wxBOTTOM | wxEXPAND | wxALIGN_CENTER, 5);
	m_item_sizer->Add(m_draw, wxGBPosition(3, column + 4), wxGBSpan(4, 1), wxTOP | wxBOTTOM | wxEXPAND | wxALIGN_CENTER, 5);

	m_nunchuck_items.push_back(m_draw);

	//////////////////////////////////////////////////////////////////

	main_sizer->Add(m_item_sizer, 1, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, 5);
	
	SetSizer(main_sizer);
	Layout();
}

void WiimoteInputPanel::add_button_row(sint32 row, sint32 column, const WiimoteController::ButtonId &button_id) {
	m_item_sizer->Add(
		new wxStaticText(this, wxID_ANY, wxGetTranslation(wxString::FromUTF8(WiimoteController::get_button_name(button_id)))),
		wxGBPosition(row, column),
		wxDefaultSpan,
		wxALL | wxALIGN_CENTER_VERTICAL, 5);

	auto* text_ctrl = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTAB_TRAVERSAL | wxTE_PROCESS_ENTER | wxTE_PROCESS_TAB);
	text_ctrl->SetClientData((void*)button_id);
	text_ctrl->SetMinSize(wxSize(150, -1));
	text_ctrl->SetEditable(false);
	text_ctrl->SetBackgroundColour(kKeyColourNormalMode);
	bind_hotkey_events(text_ctrl);
	m_item_sizer->Add(text_ctrl, wxGBPosition(row, column + 1), wxDefaultSpan, wxALL | wxEXPAND, 5);
}

void WiimoteInputPanel::set_active_device_type(WPADDeviceType type)
{
	m_device_type = type;

	m_motion_plus->SetValue(type == kWAPDevMPLS || type == kWAPDevMPLSFreeStyle || type == kWAPDevMPLSClassic);
	switch(type)
	{
	case kWAPDevFreestyle: 
	case kWAPDevMPLSFreeStyle:
		m_nunchuck->SetValue(true);
		m_classic->SetValue(false);
		for (const auto& item : m_nunchuck_items)
		{
			item->Enable(true);
		}
		break;

	case kWAPDevClassic: 
	case kWAPDevMPLSClassic:
		m_nunchuck->SetValue(false);
		m_classic->SetValue(true);
		for (const auto& item : m_nunchuck_items)
		{
			item->Enable(false);
		}
		break;

	default:
		m_nunchuck->SetValue(false);
		m_classic->SetValue(false);
		for (const auto& item : m_nunchuck_items)
		{
			item->Enable(false);
		}
	}
}

void WiimoteInputPanel::on_volume_change(wxCommandEvent& event)
{
}

void WiimoteInputPanel::on_extension_change(wxCommandEvent& event)
{
	if(m_motion_plus->GetValue() && m_nunchuck->GetValue())
		set_active_device_type(kWAPDevMPLSFreeStyle);
	else if(m_motion_plus->GetValue() && m_classic->GetValue())
		set_active_device_type(kWAPDevMPLSClassic);
	else if (m_motion_plus->GetValue())
		set_active_device_type(kWAPDevMPLS);
	else if (m_nunchuck->GetValue())
		set_active_device_type(kWAPDevFreestyle);
	else if (m_classic->GetValue())
		set_active_device_type(kWAPDevClassic);
	else 
		set_active_device_type(kWAPDevCore);
}

void WiimoteInputPanel::on_timer(const EmulatedControllerPtr& emulated_controller, const ControllerPtr& controller)
{
	if (emulated_controller)
	{
		const auto wiimote = std::dynamic_pointer_cast<WiimoteController>(emulated_controller);
		wxASSERT(wiimote);
		wiimote->set_device_type(m_device_type);
	}

	InputPanel::on_timer(emulated_controller, controller);

	const auto joycon = std::dynamic_pointer_cast<SDLController>(controller);
	if (joycon && joycon->is_joycon())
	{
		m_active_joycon = joycon;
		if (!m_joycon_panel->IsShown())
		{
			m_joycon_panel->Show();
			Layout();
			if (GetParent()) GetParent()->Layout();
		}
		update_joycon_hotkey_capture(joycon);
		update_joycon_controls(joycon);
	}
	else
	{
		m_active_joycon.reset();
		m_joycon_capture = JoyConHotkeyCapture::None;
		m_joycon_capture_buttons.clear();
		if (m_joycon_panel->IsShown())
		{
			m_joycon_panel->Hide();
			Layout();
			if (GetParent()) GetParent()->Layout();
		}
	}

	if (emulated_controller)
	{
		const auto axis = emulated_controller->get_axis();
		m_draw->SetAxisValue(axis);
	}
}

wxString WiimoteInputPanel::joycon_hotkey_label(const std::shared_ptr<SDLController>& joycon, const std::vector<uint32>& buttons) const
{
	if (!joycon || buttons.empty()) return _("Not set");
	wxString result;
	for (size_t i = 0; i < buttons.size(); ++i)
	{
		if (i) result += " + ";
		result += wxString::FromUTF8(joycon->get_button_name(buttons[i]));
	}
	return result;
}

void WiimoteInputPanel::update_joycon_controls(const std::shared_ptr<SDLController>& joycon)
{
	if (!joycon) return;
	m_joycon_name->SetLabel(joycon->is_left_joycon() ? _("Joy-Con L") : _("Joy-Con R"));
	// Internal Vertical == physical Sideways; internal Sideways == physical Vertical.
	const int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 0 : 1;
	if (m_joycon_orientation->GetSelection() != selection) m_joycon_orientation->SetSelection(selection);
	if (m_joycon_capture != JoyConHotkeyCapture::Sideways)
		m_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: ") + joycon_hotkey_label(joycon, joycon->get_sideways_hotkey()));
	if (m_joycon_capture != JoyConHotkeyCapture::Vertical)
		m_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + joycon_hotkey_label(joycon, joycon->get_vertical_hotkey()));
	m_joycon_pointer_enabled->SetValue(joycon->is_pointer_enabled());
	if (m_joycon_capture != JoyConHotkeyCapture::Pointer)
		m_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: ") + joycon_hotkey_label(joycon, joycon->get_pointer_hotkey()));
	m_joycon_pointer_yaw->SetValue(joycon->get_pointer_yaw_degrees());
	m_joycon_pointer_pitch->SetValue(joycon->get_pointer_pitch_degrees());
	m_joycon_pointer_deadzone->SetValue(joycon->get_pointer_deadzone_degrees());
	m_joycon_pointer_smoothing->SetValue(joycon->get_pointer_smoothing());
	m_joycon_pointer_invert_x->SetValue(joycon->get_pointer_invert_x());
	m_joycon_pointer_invert_y->SetValue(joycon->get_pointer_invert_y());
	float motion_x, motion_y, motion_z;
	joycon->get_motion_scale(motion_x, motion_y, motion_z);
	m_joycon_motion_x->SetValue(std::abs(motion_x));
	m_joycon_motion_y->SetValue(std::abs(motion_y));
	m_joycon_motion_z->SetValue(std::abs(motion_z));
	m_joycon_motion_invert_x->SetValue(motion_x < 0.0f);
	m_joycon_motion_invert_y->SetValue(motion_y < 0.0f);
	m_joycon_motion_invert_z->SetValue(motion_z < 0.0f);

	glm::vec2 pointer{}, previous{};
	m_joycon_preview_valid = joycon->update_joycon_pointer(pointer, previous);
	if (m_joycon_preview_valid)
	{
		m_joycon_preview_x = pointer.x;
		m_joycon_preview_y = pointer.y;
	}
	if (m_joycon_pointer_preview) m_joycon_pointer_preview->Refresh(false);
	auto motion = joycon->get_motion_sample();
	float gyro[3]{}, acc[3]{};
	motion.getGyrometer(gyro);
	motion.getAccelerometer(acc);
	m_joycon_motion_live->SetLabel(wxString::Format(_("Gyro %.2f %.2f %.2f | Acc %.2f %.2f %.2f | Pointer %.0f%% %.0f%%"),
		gyro[0], gyro[1], gyro[2], acc[0], acc[1], acc[2], m_joycon_preview_x * 100.0f, m_joycon_preview_y * 100.0f));
}

void WiimoteInputPanel::on_joycon_orientation_change(wxCommandEvent&)
{
	if (const auto joycon = m_active_joycon.lock())
	{
		joycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Sideways : SDLController::JoyConOrientation::Vertical);
		update_joycon_controls(joycon);
	}
}

void WiimoteInputPanel::on_joycon_pointer_dialog(wxCommandEvent&)
{
	const auto joycon = m_active_joycon.lock();
	if (!joycon)
		return;

	wxDialog dialog(this, wxID_ANY, _("Pointer - Dolphin Motion"), wxDefaultPosition, wxDefaultSize,
		wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
	const float original_yaw = joycon->get_pointer_yaw_degrees();
	const float original_pitch = joycon->get_pointer_pitch_degrees();
	const float original_deadzone = joycon->get_pointer_deadzone_degrees();
	const float original_smoothing = joycon->get_pointer_smoothing();
	const bool original_invert_x = joycon->get_pointer_invert_x();
	const bool original_invert_y = joycon->get_pointer_invert_y();
	auto* outer = new wxBoxSizer(wxVERTICAL);
	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Live pointer view: yellow = sensor, blue = deadzone target, green = smoothed game output.")),
		0, wxEXPAND | wxALL, 10);

	glm::vec2 sensor{0.5f}, accepted{0.5f}, output{0.5f};
	bool preview_valid = joycon->get_joycon_pointer_debug(sensor, accepted, output);
	auto* preview = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(520, 230), wxBORDER_SIMPLE);
	preview->SetMinSize(wxSize(440, 190));
	preview->SetBackgroundStyle(wxBG_STYLE_PAINT);
	preview->Bind(wxEVT_PAINT, [&](wxPaintEvent&) {
		wxAutoBufferedPaintDC dc(preview);
		const wxSize size = preview->GetClientSize();
		dc.SetBackground(wxBrush(wxColour(24, 27, 32)));
		dc.Clear();
		dc.SetPen(wxPen(wxColour(70, 76, 86), 1));
		dc.DrawLine(size.x / 2, 0, size.x / 2, size.y);
		dc.DrawLine(0, size.y / 2, size.x, size.y / 2);
		auto point = [&](const glm::vec2& value) {
			return wxPoint((int)std::lround(std::clamp(value.x, 0.0f, 1.0f) * (size.x - 1)),
				(int)std::lround(std::clamp(value.y, 0.0f, 1.0f) * (size.y - 1)));
		};
		if (!preview_valid)
		{
			dc.SetTextForeground(wxColour(210, 210, 210));
			dc.DrawText(_("Waiting for Joy-Con motion data..."), 12, 12);
			return;
		}
		const wxPoint raw = point(sensor);
		const wxPoint target = point(accepted);
		const wxPoint game = point(output);
		dc.SetPen(wxPen(wxColour(80, 155, 255), 2));
		dc.DrawLine(target, game);
		dc.SetPen(*wxTRANSPARENT_PEN);
		dc.SetBrush(wxBrush(wxColour(255, 205, 65)));
		dc.DrawCircle(raw, 5);
		dc.SetBrush(wxBrush(wxColour(75, 150, 255)));
		dc.DrawCircle(target, 6);
		dc.SetBrush(wxBrush(wxColour(70, 220, 120)));
		dc.DrawCircle(game, 7);
	});
	outer->Add(preview, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

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
	auto* yaw = make_spin(_("Horizontal FOV (degrees)"), joycon->get_pointer_yaw_degrees(), 0.01, 180.0, 0.5, 2);
	auto* pitch = make_spin(_("Vertical FOV (degrees)"), joycon->get_pointer_pitch_degrees(), 0.01, 180.0, 0.5, 2);
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
	flags->Add(recenter, 0, wxRIGHT, 10);
	box->Add(flags, 0, wxLEFT | wxRIGHT | wxBOTTOM, 8);

	std::vector<uint32> recenter_hotkey = joycon->get_pointer_recenter_hotkey();
	bool capture_active = false;
	bool capture_wait_idle = false;
	bool capture_pressed = false;
	auto hotkey_text = [&]() {
		return _("Recenter shortcut: ") + joycon_hotkey_label(joycon, recenter_hotkey);
	};
	auto* hotkey = new wxButton(&dialog, wxID_ANY, hotkey_text());
	hotkey->SetToolTip(_("Click, release all buttons, then press and release one button or a combo. Right-click to clear."));
	box->Add(hotkey, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 8);
	outer->Add(box, 0, wxEXPAND | wxLEFT | wxRIGHT, 10);

	auto apply_preview_settings = [=](wxCommandEvent&) {
		joycon->set_pointer_calibration((float)yaw->GetValue(), (float)pitch->GetValue(),
			(float)deadzone->GetValue(), (float)smoothing->GetValue(), invert_x->GetValue(), invert_y->GetValue());
	};
	for (auto* spin : {yaw, pitch, deadzone, smoothing}) spin->Bind(wxEVT_SPINCTRLDOUBLE, apply_preview_settings);
	invert_x->Bind(wxEVT_CHECKBOX, apply_preview_settings);
	invert_y->Bind(wxEVT_CHECKBOX, apply_preview_settings);

	wxTimer refresh_timer(&dialog);
	dialog.Bind(wxEVT_TIMER, [&](wxTimerEvent&) {
		glm::vec2 live_position{}, live_previous{};
		joycon->update_joycon_pointer(live_position, live_previous);
		preview_valid = joycon->get_joycon_pointer_debug(sensor, accepted, output);
		preview->Refresh(false);
		if (!capture_active) return;
		const auto pressed = joycon->get_pressed_buttons_for_hotkey();
		if (capture_wait_idle)
		{
			if (pressed.empty())
			{
				capture_wait_idle = false;
				hotkey->SetLabel(_("Press recenter button(s), then release..."));
			}
			return;
		}
		if (!pressed.empty())
		{
			recenter_hotkey = pressed;
			capture_pressed = true;
			hotkey->SetLabel(_("Release to save recenter shortcut..."));
		}
		else if (capture_pressed)
		{
			capture_active = false;
			capture_pressed = false;
			hotkey->SetLabel(hotkey_text());
		}
	}, refresh_timer.GetId());
	hotkey->Bind(wxEVT_BUTTON, [&](wxCommandEvent&) {
		capture_active = true;
		capture_wait_idle = true;
		capture_pressed = false;
		recenter_hotkey.clear();
		hotkey->SetLabel(_("Release all controller buttons..."));
	});
	hotkey->Bind(wxEVT_RIGHT_UP, [&](wxMouseEvent&) {
		capture_active = false;
		capture_wait_idle = false;
		capture_pressed = false;
		recenter_hotkey.clear();
		hotkey->SetLabel(hotkey_text());
	});
	refresh_timer.Start(33);

	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Recommended start: Deadzone 0.35 degrees, Smooth 0.10. Recenter is manual; stillness calibration changes gyro bias only.")),
		0, wxEXPAND | wxALL, 10);
	outer->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
	dialog.SetSizerAndFit(outer);
	dialog.SetMinSize(wxSize(600, 650));

	if (dialog.ShowModal() == wxID_OK)
	{
		joycon->set_pointer_calibration((float)yaw->GetValue(), (float)pitch->GetValue(),
			(float)deadzone->GetValue(), (float)smoothing->GetValue(), invert_x->GetValue(), invert_y->GetValue());
		joycon->set_pointer_recenter_hotkey(std::move(recenter_hotkey));
	}
	else
	{
		joycon->set_pointer_calibration(original_yaw, original_pitch, original_deadzone,
			original_smoothing, original_invert_x, original_invert_y);
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
		_("Point uses Dolphin pointer fusion. Game motion uses the proven Cemu basis plus the hardware-verified Joy-Con R Sideways fix.")),
		0, wxEXPAND | wxALL, 10);

	const float original_hfov = joycon->get_pointer_yaw_degrees();
	const float original_vfov = joycon->get_pointer_pitch_degrees();
	const float original_deadzone = joycon->get_pointer_deadzone_degrees();
	const float original_smoothing = joycon->get_pointer_smoothing();
	const bool original_invert_x = joycon->get_pointer_invert_x();
	const bool original_invert_y = joycon->get_pointer_invert_y();
	const float original_total_yaw = joycon->get_dolphin_total_yaw_degrees();
	const float original_accel_influence = joycon->get_dolphin_accel_influence();
	const float original_gyro_deadzone = joycon->get_dolphin_gyro_deadzone_degrees();
	const float original_calibration_period = joycon->get_dolphin_calibration_period_seconds();
	const float original_pointer_calibration_period = joycon->get_pointer_calibration_period_seconds();
	const auto original_orientation = joycon->get_joycon_orientation();

	SDLControllerProvider::DolphinMotionDebug debug{};
	bool debug_valid = joycon->get_dolphin_motion_debug(debug);
	glm::vec2 pointer_sensor{0.5f}, pointer_target{0.5f}, pointer_output{0.5f};
	bool pointer_valid = joycon->get_joycon_pointer_debug(pointer_sensor, pointer_target, pointer_output);

	auto* groups = new wxBoxSizer(wxHORIZONTAL);
	auto* point_box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Point"));
	auto* point_preview = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(250, 170), wxBORDER_SIMPLE);
	point_preview->SetMinSize(wxSize(230, 150));
	point_preview->SetBackgroundStyle(wxBG_STYLE_PAINT);
	point_preview->Bind(wxEVT_PAINT, [&](wxPaintEvent&) {
		wxAutoBufferedPaintDC dc(point_preview);
		const wxSize size = point_preview->GetClientSize();
		dc.SetBackground(wxBrush(wxColour(24, 27, 32)));
		dc.Clear();
		dc.SetPen(wxPen(wxColour(70, 76, 86), 1));
		dc.DrawLine(size.x / 2, 0, size.x / 2, size.y);
		dc.DrawLine(0, size.y / 2, size.x, size.y / 2);
		if (!pointer_valid)
		{
			dc.SetTextForeground(wxColour(210, 210, 210));
			dc.DrawText(_("Waiting for pointer..."), 8, 8);
			return;
		}
		auto p = [&](const glm::vec2& value) {
			return wxPoint((int)std::lround(std::clamp(value.x, 0.0f, 1.0f) * (size.x - 1)),
				(int)std::lround(std::clamp(value.y, 0.0f, 1.0f) * (size.y - 1)));
		};
		dc.SetPen(*wxTRANSPARENT_PEN);
		dc.SetBrush(wxBrush(wxColour(255, 205, 65))); dc.DrawCircle(p(pointer_sensor), 4);
		dc.SetBrush(wxBrush(wxColour(75, 150, 255))); dc.DrawCircle(p(pointer_target), 5);
		dc.SetBrush(wxBrush(wxColour(70, 220, 120))); dc.DrawCircle(p(pointer_output), 6);
	});
	point_box->Add(point_preview, 0, wxEXPAND | wxALL, 6);
	point_box->Add(new wxStaticText(&dialog, wxID_ANY, _("Yellow sensor | Blue deadzone | Green game output")), 0, wxLEFT | wxRIGHT | wxBOTTOM, 6);

	auto* point_grid = new wxFlexGridSizer(3, 5, 6);
	point_grid->AddGrowableCol(1, 1);
	auto add_point_setting = [&](const wxString& label, double value, double minv, double maxv, double step, int digits) {
		point_grid->Add(new wxStaticText(&dialog, wxID_ANY, label), 0, wxALIGN_CENTER_VERTICAL);
		auto* spin = new wxSpinCtrlDouble(&dialog, wxID_ANY);
		spin->SetRange(minv, maxv); spin->SetIncrement(step); spin->SetDigits(digits); spin->SetValue(value);
		point_grid->Add(spin, 1, wxEXPAND);
		point_grid->Add(new wxButton(&dialog, wxID_ANY, _("..."), wxDefaultPosition, wxSize(38, -1)), 0);
		return spin;
	};
	auto* total_yaw = add_point_setting(_("Total Yaw"), original_total_yaw, 0.0, 360.0, 1.0, 2);
	auto* accel_influence = add_point_setting(_("Accelerometer Influence (%)"), original_accel_influence * 100.0f, 0.0, 100.0, 0.1, 2);
	auto* horizontal_fov = add_point_setting(_("Horizontal FOV"), original_hfov, 0.01, 180.0, 0.5, 2);
	auto* vertical_fov = add_point_setting(_("Vertical FOV"), original_vfov, 0.01, 180.0, 0.5, 2);
	auto* pointer_deadzone = add_point_setting(_("Pointer Deadzone"), original_deadzone, 0.0, 5.0, 0.05, 2);
	auto* pointer_smoothing = add_point_setting(_("Smooth (0 = direct)"), original_smoothing, 0.0, 0.95, 0.01, 2);
	auto* pointer_calibration_period = add_point_setting(_("Pointer Calibration Period (s)"), original_pointer_calibration_period, 0.0, 30.0, 0.25, 2);
	point_box->Add(point_grid, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);

	auto* point_flags = new wxBoxSizer(wxHORIZONTAL);
	auto* enabled = new wxCheckBox(&dialog, wxID_ANY, _("Enabled")); enabled->SetValue(joycon->is_pointer_enabled());
	auto* invert_x = new wxCheckBox(&dialog, wxID_ANY, _("Invert X")); invert_x->SetValue(original_invert_x);
	auto* invert_y = new wxCheckBox(&dialog, wxID_ANY, _("Invert Y")); invert_y->SetValue(original_invert_y);
	point_flags->Add(enabled, 0, wxRIGHT, 8); point_flags->Add(invert_x, 0, wxRIGHT, 8); point_flags->Add(invert_y, 0);
	point_box->Add(point_flags, 0, wxLEFT | wxRIGHT | wxBOTTOM, 6);
	auto* recenter = new wxButton(&dialog, wxID_ANY, _("Recenter now"));
	recenter->Bind(wxEVT_BUTTON, [joycon](wxCommandEvent&) { joycon->recenter_joycon_pointer(); });
	point_box->Add(recenter, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);
	std::vector<uint32> recenter_hotkey = joycon->get_pointer_recenter_hotkey();
	auto* recenter_binding = new wxButton(&dialog, wxID_ANY,
		_("Recenter: ") + joycon_hotkey_label(joycon, recenter_hotkey));
	point_box->Add(recenter_binding, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);
	auto* pointer_calibration_status = new wxStaticText(&dialog, wxID_ANY, _("Pointer Calibration: waiting for sensor"));
	point_box->Add(pointer_calibration_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);
	groups->Add(point_box, 1, wxEXPAND | wxRIGHT, 6);

	auto* passthrough_box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Point (Passthrough)"));
	auto* passthrough_view = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(150, 170), wxBORDER_SIMPLE);
	passthrough_view->SetBackgroundColour(wxColour(24, 27, 32));
	passthrough_box->Add(passthrough_view, 0, wxEXPAND | wxALL, 6);
	auto* passthrough_enabled = new wxCheckBox(&dialog, wxID_ANY, _("Enabled"));
	passthrough_enabled->SetValue(false); passthrough_enabled->Enable(false);
	passthrough_box->Add(passthrough_enabled, 0, wxLEFT | wxRIGHT | wxBOTTOM, 6);
	passthrough_box->Add(new wxStaticText(&dialog, wxID_ANY, _("Native Joy-Con IMU pointer.\nCemu generates DPD objects\nautomatically.")),
		0, wxLEFT | wxRIGHT | wxBOTTOM, 6);
	groups->Add(passthrough_box, 0, wxEXPAND | wxRIGHT, 6);

	auto make_sensor_box = [&](const wxString& title, bool gyro) {
		auto* box = new wxStaticBoxSizer(wxVERTICAL, &dialog, title);
		auto* view = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(190, 170), wxBORDER_SIMPLE);
		view->SetMinSize(wxSize(175, 150)); view->SetBackgroundStyle(wxBG_STYLE_PAINT);
		view->Bind(wxEVT_PAINT, [&, view, gyro](wxPaintEvent&) {
			wxAutoBufferedPaintDC dc(view);
			const wxSize size = view->GetClientSize();
			dc.SetBackground(wxBrush(wxColour(24, 27, 32))); dc.Clear();
			const int radius = std::max(25, std::min(size.x, size.y) / 2 - 24);
			const wxPoint center(size.x / 2, size.y / 2);
			dc.SetPen(wxPen(wxColour(95, 100, 110))); dc.SetBrush(*wxTRANSPARENT_BRUSH);
			dc.DrawCircle(center, radius); dc.DrawLine(center.x - radius, center.y, center.x + radius, center.y);
			dc.DrawLine(center.x, center.y - radius, center.x, center.y + radius);
			if (!debug_valid) return;
			const glm::vec3 value = gyro ? debug.gyro : debug.accel;
			const float scale = gyro ? 3.14159265f : 1.0f;
			const wxPoint tip(center.x + (int)std::lround(std::clamp(value.x / scale, -1.0f, 1.0f) * radius),
				center.y - (int)std::lround(std::clamp(value.z / scale, -1.0f, 1.0f) * radius));
			dc.SetPen(wxPen(gyro ? wxColour(80, 135, 255) : wxColour(70, 220, 120), 2)); dc.DrawLine(center, tip);
			dc.SetBrush(wxBrush(gyro ? wxColour(80, 135, 255) : wxColour(70, 220, 120))); dc.DrawCircle(tip, 5);
		});
		box->Add(view, 0, wxEXPAND | wxALL, 6);
		return std::pair<wxStaticBoxSizer*, wxPanel*>(box, view);
	};
	auto [accel_box, accel_view] = make_sensor_box(_("Accelerometer"), false);
	for (const auto& row : {std::pair<const wchar_t*, const wchar_t*>(L"Up", L"Accel Up"), {L"Down", L"Accel Down"},
		{L"Left", L"Accel Left"}, {L"Right", L"Accel Right"}, {L"Forward", L"Accel Forward"}, {L"Backward", L"Accel Backward"}})
	{
		auto* line = new wxBoxSizer(wxHORIZONTAL); line->Add(new wxStaticText(&dialog, wxID_ANY, wxString(row.first)), 1, wxALIGN_CENTER_VERTICAL);
		auto* binding = new wxButton(&dialog, wxID_ANY, wxString(row.second)); binding->Enable(false); line->Add(binding, 0);
		accel_box->Add(line, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4);
	}
	groups->Add(accel_box, 0, wxEXPAND | wxRIGHT, 6);

	auto [gyro_box, gyro_view] = make_sensor_box(_("Gyroscope"), true);
	for (const auto& row : {std::pair<const wchar_t*, const wchar_t*>(L"Pitch Up", L"Gyro Pitch Up"), {L"Pitch Down", L"Gyro Pitch Down"},
		{L"Roll Left", L"Gyro Roll Left"}, {L"Roll Right", L"Gyro Roll Right"}, {L"Yaw Left", L"Gyro Yaw Left"}, {L"Yaw Right", L"Gyro Yaw Right"}})
	{
		auto* line = new wxBoxSizer(wxHORIZONTAL); line->Add(new wxStaticText(&dialog, wxID_ANY, wxString(row.first)), 1, wxALIGN_CENTER_VERTICAL);
		auto* binding = new wxButton(&dialog, wxID_ANY, wxString(row.second)); binding->Enable(false); line->Add(binding, 0);
		gyro_box->Add(line, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4);
	}
	auto add_gyro_setting = [&](const wxString& label, double value, double minv, double maxv, double step) {
		auto* line = new wxBoxSizer(wxHORIZONTAL); line->Add(new wxStaticText(&dialog, wxID_ANY, label), 1, wxALIGN_CENTER_VERTICAL);
		auto* spin = new wxSpinCtrlDouble(&dialog, wxID_ANY); spin->SetRange(minv, maxv); spin->SetIncrement(step); spin->SetDigits(2); spin->SetValue(value);
		line->Add(spin, 0); gyro_box->Add(line, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4); return spin;
	};
	auto* gyro_deadzone = add_gyro_setting(_("Dead Zone (degrees/s)"), original_gyro_deadzone, 0.0, 180.0, 0.1);
	auto* calibration_period = add_gyro_setting(_("Calibration Period (s)"), original_calibration_period, 0.0, 30.0, 0.25);
	groups->Add(gyro_box, 0, wxEXPAND);
	outer->Add(groups, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* orientation_box = new wxStaticBoxSizer(wxHORIZONTAL, &dialog, _("Physical orientation"));
	auto* orientation = new wxChoice(&dialog, wxID_ANY); orientation->Append(_("Sideways")); orientation->Append(_("Vertical"));
	// V21: labels and enum now match 1:1. Sideways=0, Vertical=1.
	orientation->SetSelection(original_orientation == SDLController::JoyConOrientation::Vertical ? 1 : 0);
	orientation_box->Add(orientation, 0, wxALL, 6);
	orientation_box->Add(new wxStaticText(&dialog, wxID_ANY,
		_("V22: Sideways/Vertical motion basis is physical; Joy-Con R accelerometer receives final 180 degree correction; pointer remains independent")),
		1, wxALL | wxALIGN_CENTER_VERTICAL, 6);
	outer->Add(orientation_box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* status = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
	auto* values = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
	outer->Add(status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);
	outer->Add(values, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);

	bool capture_active = false, capture_wait_idle = false, capture_pressed = false;
	recenter_binding->Bind(wxEVT_BUTTON, [&](wxCommandEvent&) {
		capture_active = true; capture_wait_idle = true; capture_pressed = false; recenter_hotkey.clear();
		recenter_binding->SetLabel(_("Release all controller buttons..."));
	});
	auto apply_live = [=](wxCommandEvent&) {
		joycon->set_pointer_calibration((float)horizontal_fov->GetValue(), (float)vertical_fov->GetValue(),
			(float)pointer_deadzone->GetValue(), (float)pointer_smoothing->GetValue(), invert_x->GetValue(), invert_y->GetValue());
		joycon->set_dolphin_motion_settings((float)total_yaw->GetValue(), (float)accel_influence->GetValue() / 100.0f,
			(float)gyro_deadzone->GetValue(), (float)calibration_period->GetValue());
		joycon->set_pointer_calibration_period_seconds((float)pointer_calibration_period->GetValue());
	};
	for (auto* spin : {total_yaw, accel_influence, horizontal_fov, vertical_fov, pointer_deadzone, pointer_smoothing, pointer_calibration_period, gyro_deadzone, calibration_period})
		spin->Bind(wxEVT_SPINCTRLDOUBLE, apply_live);
	invert_x->Bind(wxEVT_CHECKBOX, apply_live); invert_y->Bind(wxEVT_CHECKBOX, apply_live);

	wxTimer refresh_timer(&dialog);
	dialog.Bind(wxEVT_TIMER, [&](wxTimerEvent&) {
		glm::vec2 live{}, previous{}; joycon->update_joycon_pointer(live, previous);
		pointer_valid = joycon->get_joycon_pointer_debug(pointer_sensor, pointer_target, pointer_output);
		debug_valid = joycon->get_dolphin_motion_debug(debug);
		point_preview->Refresh(false); accel_view->Refresh(false); gyro_view->Refresh(false);
		if (debug_valid)
		{
			const int pointer_percent = (int)std::lround(debug.calibration_progress * 100.0f);
			if (debug.calibrated && debug.stable) pointer_calibration_status->SetLabel(wxString::Format(_("Pointer Calibration: READY / STILL | %.0f Hz"), debug.sample_rate_hz));
			else if (debug.stable) pointer_calibration_status->SetLabel(wxString::Format(_("Pointer Calibration: KEEP STILL %d%% | %.0f Hz"), pointer_percent, debug.sample_rate_hz));
			else pointer_calibration_status->SetLabel(wxString::Format(_("Pointer Calibration: MOVING - timer restarted | %.0f Hz"), debug.sample_rate_hz));

			const int game_percent = (int)std::lround(debug.game_calibration_progress * 100.0f);
			if (debug.game_calibrated && debug.game_stable) status->SetLabel(wxString::Format(_("Game Gyro Calibration: READY / STILL | %.0f Hz"), debug.game_sample_rate_hz));
			else if (debug.game_stable) status->SetLabel(wxString::Format(_("Game Gyro Calibration: KEEP STILL %d%% | %.0f Hz"), game_percent, debug.game_sample_rate_hz));
			else status->SetLabel(wxString::Format(_("Game Gyro Calibration: MOVING - timer restarted | %.0f Hz"), debug.game_sample_rate_hz));

			values->SetLabel(wxString::Format(_("Gyro: %+.3f %+.3f %+.3f rad/s | Acc: %+.3f %+.3f %+.3f g | Game Bias: %+.4f %+.4f %+.4f | Pointer Bias: %+.4f %+.4f %+.4f"),
				debug.gyro.x, debug.gyro.y, debug.gyro.z, debug.accel.x, debug.accel.y, debug.accel.z,
				debug.game_bias.x, debug.game_bias.y, debug.game_bias.z, debug.bias.x, debug.bias.y, debug.bias.z));
		}
		if (!capture_active) return;
		const auto pressed = joycon->get_pressed_buttons_for_hotkey();
		if (capture_wait_idle) { if (pressed.empty()) { capture_wait_idle = false; recenter_binding->SetLabel(_("Press Recenter button(s), then release...")); } return; }
		if (!pressed.empty()) { recenter_hotkey = pressed; capture_pressed = true; recenter_binding->SetLabel(_("Release to save Recenter...")); }
		else if (capture_pressed) { capture_active = false; capture_pressed = false; recenter_binding->SetLabel(_("Recenter: ") + joycon_hotkey_label(joycon, recenter_hotkey)); }
	}, refresh_timer.GetId());
	refresh_timer.Start(33);

	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("V21 defaults: Total Yaw 25 degrees | Accelerometer Influence 1% | FOV 42 / 31.5 degrees | Gyro Dead Zone 2 degrees/s | Game Gyro Calibration 3 s | Pointer Calibration 3 s | minimum 25 Hz.")),
		0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 8);
	outer->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
	dialog.SetSizerAndFit(outer);
	dialog.SetMinSize(wxSize(1120, 760));

	if (dialog.ShowModal() == wxID_OK)
	{
		joycon->set_pointer_enabled(enabled->GetValue(), false);
		joycon->set_pointer_recenter_hotkey(std::move(recenter_hotkey));
		// V21: selecting Sideways stores Sideways; selecting Vertical stores Vertical.
		joycon->set_joycon_orientation(orientation->GetSelection() == 0 ?
			SDLController::JoyConOrientation::Sideways : SDLController::JoyConOrientation::Vertical);
		joycon->set_motion_scale(1.0f, 1.0f, 1.0f);
	}
	else
	{
		joycon->set_pointer_calibration(original_hfov, original_vfov, original_deadzone, original_smoothing, original_invert_x, original_invert_y);
		joycon->set_dolphin_motion_settings(original_total_yaw, original_accel_influence, original_gyro_deadzone, original_calibration_period);
		joycon->set_pointer_calibration_period_seconds(original_pointer_calibration_period);
		joycon->set_joycon_orientation(original_orientation, false);
	}
}

void WiimoteInputPanel::on_joycon_pointer_recenter(wxCommandEvent&)
{
	if (const auto joycon = m_active_joycon.lock())
		joycon->recenter_joycon_pointer();
}

void WiimoteInputPanel::on_joycon_pointer_settings(wxCommandEvent&)
{
	if (const auto joycon = m_active_joycon.lock())
	{
		joycon->set_pointer_calibration(
			(float)m_joycon_pointer_yaw->GetValue(),
			(float)m_joycon_pointer_pitch->GetValue(),
			(float)m_joycon_pointer_deadzone->GetValue(),
			(float)m_joycon_pointer_smoothing->GetValue(),
			m_joycon_pointer_invert_x->GetValue(),
			m_joycon_pointer_invert_y->GetValue());
	}
}

void WiimoteInputPanel::on_joycon_motion_settings(wxCommandEvent&)
{
	if (const auto joycon = m_active_joycon.lock())
	{
		const float x = (float)m_joycon_motion_x->GetValue() * (m_joycon_motion_invert_x->GetValue() ? -1.0f : 1.0f);
		const float y = (float)m_joycon_motion_y->GetValue() * (m_joycon_motion_invert_y->GetValue() ? -1.0f : 1.0f);
		const float z = (float)m_joycon_motion_z->GetValue() * (m_joycon_motion_invert_z->GetValue() ? -1.0f : 1.0f);
		joycon->set_motion_scale(x, y, z);
	}
}

void WiimoteInputPanel::on_joycon_motion_reset(wxCommandEvent&)
{
	m_joycon_motion_x->SetValue(1.0);
	m_joycon_motion_y->SetValue(1.0);
	m_joycon_motion_z->SetValue(1.0);
	m_joycon_motion_invert_x->SetValue(false);
	m_joycon_motion_invert_y->SetValue(false);
	m_joycon_motion_invert_z->SetValue(false);
	if (const auto joycon = m_active_joycon.lock())
		joycon->set_motion_scale(1.0f, 1.0f, 1.0f);
}

void WiimoteInputPanel::on_joycon_pointer_paint(wxPaintEvent&)
{
	wxAutoBufferedPaintDC dc(m_joycon_pointer_preview);
	dc.SetBackground(wxBrush(wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW)));
	dc.Clear();
	const wxSize size = m_joycon_pointer_preview->GetClientSize();
	dc.SetPen(wxPen(wxSystemSettings::GetColour(wxSYS_COLOUR_GRAYTEXT)));
	dc.DrawLine(size.x / 2, 0, size.x / 2, size.y);
	dc.DrawLine(0, size.y / 2, size.x, size.y / 2);
	if (m_joycon_preview_valid)
	{
		const int x = std::clamp((int)std::lround(m_joycon_preview_x * (size.x - 1)), 0, std::max(0, size.x - 1));
		const int y = std::clamp((int)std::lround(m_joycon_preview_y * (size.y - 1)), 0, std::max(0, size.y - 1));
		dc.SetPen(wxPen(wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHT), 2));
		dc.DrawCircle(x, y, 5);
	}
}

void WiimoteInputPanel::on_joycon_pointer_enable(wxCommandEvent&)
{
	if (const auto joycon = m_active_joycon.lock())
	{
		joycon->set_pointer_enabled(m_joycon_pointer_enabled->GetValue());
		m_joycon_status->SetLabel(joycon->is_pointer_enabled() ? _("Pointer ON. It recenters when enabled.") : _("Pointer OFF. No IR/DPD data will be sent."));
	}
}

void WiimoteInputPanel::on_joycon_hotkey_click(wxCommandEvent& event)
{
	if (!m_active_joycon.lock()) return;
	if (event.GetEventObject() == m_joycon_pointer_hotkey)
		m_joycon_capture = JoyConHotkeyCapture::Pointer;
	else
		m_joycon_capture = event.GetEventObject() == m_joycon_vertical_hotkey ? JoyConHotkeyCapture::Vertical : JoyConHotkeyCapture::Sideways;
	m_joycon_capture_buttons.clear();
	m_joycon_capture_wait_for_idle = true;
	m_joycon_capture_seen_buttons = false;
	if (m_joycon_capture == JoyConHotkeyCapture::Vertical)
		m_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: release all buttons..."));
	else if (m_joycon_capture == JoyConHotkeyCapture::Pointer)
		m_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: release all buttons..."));
	else
		m_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: release all buttons..."));
	m_joycon_status->SetLabel(_("Then press and release the exact 2+ button combo you want."));
}

void WiimoteInputPanel::on_joycon_hotkey_clear(wxMouseEvent& event)
{
	if (const auto joycon = m_active_joycon.lock())
	{
		if (event.GetEventObject() == m_joycon_vertical_hotkey) joycon->set_vertical_hotkey({});
		else if (event.GetEventObject() == m_joycon_pointer_hotkey) joycon->set_pointer_hotkey({});
		else joycon->set_sideways_hotkey({});
		m_joycon_capture = JoyConHotkeyCapture::None;
		m_joycon_capture_buttons.clear();
		m_joycon_status->SetLabel(_("Hotkey cleared."));
		update_joycon_controls(joycon);
	}
}

void WiimoteInputPanel::update_joycon_hotkey_capture(const std::shared_ptr<SDLController>& joycon)
{
	if (!joycon || m_joycon_capture == JoyConHotkeyCapture::None) return;
	const auto pressed = joycon->get_pressed_buttons_for_hotkey();
	if (m_joycon_capture_wait_for_idle)
	{
		if (!pressed.empty()) return;
		m_joycon_capture_wait_for_idle = false;
		m_joycon_status->SetLabel(_("Press your 2+ button combo now, then release it to save."));
		return;
	}
	if (!pressed.empty())
	{
		m_joycon_capture_seen_buttons = true;
		for (const auto id : pressed)
			if (std::find(m_joycon_capture_buttons.cbegin(), m_joycon_capture_buttons.cend(), id) == m_joycon_capture_buttons.cend()) m_joycon_capture_buttons.emplace_back(id);
		std::sort(m_joycon_capture_buttons.begin(), m_joycon_capture_buttons.end());
		const auto label = joycon_hotkey_label(joycon, m_joycon_capture_buttons);
		if (m_joycon_capture == JoyConHotkeyCapture::Vertical) m_joycon_vertical_hotkey->SetLabel(_("Vertical hotkey: ") + label);
		else if (m_joycon_capture == JoyConHotkeyCapture::Pointer) m_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: ") + label);
		else m_joycon_sideways_hotkey->SetLabel(_("Sideways hotkey: ") + label);
		return;
	}
	if (!m_joycon_capture_seen_buttons) return;
	if (m_joycon_capture_buttons.size() < 2)
		m_joycon_status->SetLabel(_("Not saved: use at least 2 controller buttons."));
	else
	{
		if (m_joycon_capture == JoyConHotkeyCapture::Vertical) joycon->set_vertical_hotkey(m_joycon_capture_buttons);
		else if (m_joycon_capture == JoyConHotkeyCapture::Pointer) joycon->set_pointer_hotkey(m_joycon_capture_buttons);
		else joycon->set_sideways_hotkey(m_joycon_capture_buttons);
		m_joycon_status->SetLabel(_("Hotkey saved. It works instantly during gameplay."));
	}
	m_joycon_capture = JoyConHotkeyCapture::None;
	m_joycon_capture_buttons.clear();
	m_joycon_capture_seen_buttons = false;
	update_joycon_controls(joycon);
}

void WiimoteInputPanel::load_controller(const EmulatedControllerPtr& emulated_controller)
{
	InputPanel::load_controller(emulated_controller);

	if (emulated_controller) {
		const auto wiimote = std::dynamic_pointer_cast<WiimoteController>(emulated_controller);
		wxASSERT(wiimote);
		set_active_device_type(wiimote->get_device_type());
	}
}
