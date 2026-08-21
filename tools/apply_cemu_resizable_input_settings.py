from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_resizable_input_settings.py <cemu-source-root>")

root = Path(sys.argv[1])
cpp = root / "src/gui/wxgui/input/InputSettings2.cpp"
text = cpp.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str):
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)
    print(f"Patched InputSettings2.cpp: {label}")


def replace_all(old: str, new: str, expected: int, label: str):
    global text
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{label}: expected {expected} matches, found {count}")
    text = text.replace(old, new)
    print(f"Patched InputSettings2.cpp: {label} ({count} matches)")


replace_once(
    '#include <wx/settings.h>\n',
    '#include <wx/settings.h>\n#include <wx/scrolwin.h>\n',
    'include scrolled-window support',
)

replace_once(
    'InputSettings2::InputSettings2(wxWindow* parent)\n\t: wxDialog(parent, wxID_ANY, _("Input settings"))\n',
    'InputSettings2::InputSettings2(wxWindow* parent)\n\t: wxDialog(parent, wxID_ANY, _("Input settings"), wxDefaultPosition, wxDefaultSize, wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER | wxMAXIMIZE_BOX)\n',
    'make Input Settings dialog resizable and maximizable',
)

replace_once(
    '\t\tauto* page = new wxPanel(m_notebook, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxTAB_TRAVERSAL);\n\t\tpage->SetClientObject(nullptr); // force internal type to client object\n',
    '\t\tauto* page = new wxScrolledWindow(m_notebook, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxTAB_TRAVERSAL | wxVSCROLL);\n\t\tpage->SetScrollRate(0, 12);\n\t\tpage->SetClientObject(nullptr); // force internal type to client object\n',
    'make every controller tab vertically scrollable',
)

# This exact statement occurs twice with different indentation levels.
replace_all(
    'panel_sizer->Add(panel, 0, wxEXPAND);',
    'panel_sizer->Add(panel, 1, wxEXPAND);',
    2,
    'allow input panels to expand with the dialog',
)

replace_once(
    '\twxWindowUpdateLocker lock(page);\n\tauto* sizer = new wxGridBagSizer();\n',
    '\twxWindowUpdateLocker lock(page);\n\tauto* sizer = new wxGridBagSizer();\n\tsizer->AddGrowableCol(1, 1);\n\tsizer->AddGrowableRow(7, 1);\n',
    'make controller/input rows expand with the dialog',
)

replace_once(
    '\tpage->SetSizer(sizer);\n\tpage->Layout();\n\n\tpage->SetClientObject(new wxCustomData(page_data));\n',
    '\tpage->SetSizer(sizer);\n\tpage->Layout();\n\tif (auto* scrolled = dynamic_cast<wxScrolledWindow*>(page))\n\t\tscrolled->FitInside();\n\n\tpage->SetClientObject(new wxCustomData(page_data));\n',
    'update scrollable virtual size after page initialization',
)

replace_once(
    '\t\tpanel->Show();\n\t\tpage->wxWindowBase::Layout();\n\t\tpage->wxWindow::Update();\n',
    '\t\tpanel->Show();\n\t\tpage->wxWindowBase::Layout();\n\t\tif (auto* scrolled = dynamic_cast<wxScrolledWindow*>(page))\n\t\t\tscrolled->FitInside();\n\t\tpage->wxWindow::Update();\n',
    'refresh scrollable virtual size when active input panel changes',
)

replace_once(
    '\tFit();\n\n    panel->Hide();\n',
    '\tFit();\n\tSetMinSize(wxSize(700, 500));\n\tSetSize(wxSize(1000, 720));\n\n    panel->Hide();\n',
    'set practical initial and minimum dialog size',
)

cpp.write_text(text, encoding="utf-8")
print("Resizable + maximizable + scrollable Input Settings patch applied successfully.")
