#pragma once

#include "wxgui/input/panels/InputPanel.h"
#include "input/emulated/WiimoteController.h"
#include <wx/slider.h>

class wxCheckBox;
class wxGridBagSizer;
class wxInputDraw;
class wxChoice;
class wxButton;
class wxStaticText;
class wxSpinCtrlDouble;
class SDLController;

class WiimoteInputPanel : public InputPanel
{
public:
	WiimoteInputPanel(wxWindow* parent);

	void on_timer(const EmulatedControllerPtr& emulated_controller, const ControllerPtr& controller) override;

	void load_controller(const EmulatedControllerPtr& emulated_controller) override;

private:
	wxInputDraw* m_draw;

	WPADDeviceType m_device_type = kWAPDevCore;
	void set_active_device_type(WPADDeviceType type);

	void on_volume_change(wxCommandEvent& event);
	void on_extension_change(wxCommandEvent& event);
    void on_pair_button(wxCommandEvent& event);

	wxGridBagSizer* m_item_sizer;

	wxCheckBox* m_nunchuck, * m_classic;
	wxCheckBox* m_motion_plus;

	wxSlider* m_volume;

	std::vector<wxWindow*> m_nunchuck_items;

	enum class JoyConHotkeyCapture { None, Sideways, Vertical, Pointer };
	wxPanel* m_joycon_panel = nullptr;
	wxStaticText* m_joycon_name = nullptr;
	wxChoice* m_joycon_orientation = nullptr;
	wxButton* m_joycon_sideways_hotkey = nullptr;
	wxButton* m_joycon_vertical_hotkey = nullptr;
	wxCheckBox* m_joycon_pointer_enabled = nullptr;
	wxButton* m_joycon_pointer_hotkey = nullptr;
	wxButton* m_joycon_pointer_recenter = nullptr;
	wxPanel* m_joycon_pointer_preview = nullptr;
	wxSpinCtrlDouble* m_joycon_pointer_yaw = nullptr;
	wxSpinCtrlDouble* m_joycon_pointer_pitch = nullptr;
	wxSpinCtrlDouble* m_joycon_pointer_deadzone = nullptr;
	wxSpinCtrlDouble* m_joycon_pointer_smoothing = nullptr;
	wxCheckBox* m_joycon_pointer_invert_x = nullptr;
	wxCheckBox* m_joycon_pointer_invert_y = nullptr;
	wxSpinCtrlDouble* m_joycon_motion_x = nullptr;
	wxSpinCtrlDouble* m_joycon_motion_y = nullptr;
	wxSpinCtrlDouble* m_joycon_motion_z = nullptr;
	wxCheckBox* m_joycon_motion_invert_x = nullptr;
	wxCheckBox* m_joycon_motion_invert_y = nullptr;
	wxCheckBox* m_joycon_motion_invert_z = nullptr;
	wxButton* m_joycon_motion_reset = nullptr;
	wxStaticText* m_joycon_motion_live = nullptr;
	wxButton* m_joycon_motion_dialog = nullptr;
	wxStaticText* m_joycon_status = nullptr;
	float m_joycon_preview_x = 0.5f;
	float m_joycon_preview_y = 0.5f;
	bool m_joycon_preview_valid = false;
	std::weak_ptr<SDLController> m_active_joycon;
	JoyConHotkeyCapture m_joycon_capture = JoyConHotkeyCapture::None;
	bool m_joycon_capture_wait_for_idle = false;
	bool m_joycon_capture_seen_buttons = false;
	std::vector<uint32> m_joycon_capture_buttons;

	void on_joycon_orientation_change(wxCommandEvent& event);
	void on_joycon_pointer_enable(wxCommandEvent& event);
	void on_joycon_pointer_recenter(wxCommandEvent& event);
	void on_joycon_pointer_settings(wxCommandEvent& event);
	void on_joycon_motion_settings(wxCommandEvent& event);
	void on_joycon_motion_reset(wxCommandEvent& event);
	void on_joycon_pointer_dialog(wxCommandEvent& event);
	void on_joycon_motion_dialog(wxCommandEvent& event);
	void on_joycon_pointer_paint(wxPaintEvent& event);
	void on_joycon_hotkey_click(wxCommandEvent& event);
	void on_joycon_hotkey_clear(wxMouseEvent& event);
	void update_joycon_controls(const std::shared_ptr<SDLController>& joycon);
	void update_joycon_hotkey_capture(const std::shared_ptr<SDLController>& joycon);
	wxString joycon_hotkey_label(const std::shared_ptr<SDLController>& joycon, const std::vector<uint32>& buttons) const;

	void add_button_row(sint32 row, sint32 column, const WiimoteController::ButtonId &button_id);
};




