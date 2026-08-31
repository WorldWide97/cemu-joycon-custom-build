from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v28_legacy_h264_cmake.py <cemu-source-root>")

root = Path(sys.argv[1])
cmake = root / "src/Cafe/CMakeLists.txt"
h264 = root / "src/Cafe/OS/libs/h264_avc/H264Dec.cpp"

# The workflow first checks out H264Dec.cpp + parser from tag v2.0-88.
# Keep the modern h264dec.h so current Cemu can discover the module via GetModule().
text = cmake.read_text(encoding="utf-8")
for line in (
    "  OS/libs/h264_avc/H264DecBackendAVC.cpp\n",
    "  OS/libs/h264_avc/H264DecInternal.h\n",
):
    count = text.count(line)
    if count != 1:
        raise RuntimeError(f"expected exactly one CMake entry for {line.strip()}, found {count}")
    text = text.replace(line, "", 1)
cmake.write_text(text, encoding="utf-8")

legacy = h264.read_text(encoding="utf-8")
if "void Initialize()" not in legacy:
    raise RuntimeError("v2.0-88 Initialize() marker missing")
if "_async_H264DECExecute" not in legacy or "std::async" not in legacy:
    raise RuntimeError("v2.0-88 synchronous-per-call decode markers missing")
if "QueueForDecode" in legacy or "H264DecoderBackend" in legacy:
    raise RuntimeError("modern async backend code leaked into legacy H264Dec.cpp")
if "COSModule* GetModule()" in legacy:
    raise RuntimeError("legacy file unexpectedly already contains modern module wrapper")

# Current Cemu expects H264::GetModule(). Add only the modern registration wrapper;
# decoding/session/flush/execute behavior stays from v2.0-88.
wrapper = r'''

	// V28 compatibility bridge: keep the v2.0-88 decoder implementation but
	// expose it through the COSModule interface expected by current Cemu.
	class : public COSModule
	{
	public:
		std::string_view GetName() override
		{
			return "h264";
		}

		void RPLMapped() override
		{
			Initialize();
		}
	}s_COSh264LegacyModule;

	COSModule* GetModule()
	{
		return &s_COSh264LegacyModule;
	}
'''

last_namespace_close = legacy.rfind("\n}")
if last_namespace_close == -1:
    raise RuntimeError("could not locate H264 namespace closing brace")
legacy = legacy[:last_namespace_close] + wrapper + legacy[last_namespace_close:]
h264.write_text(legacy, encoding="utf-8")

cmake_check = cmake.read_text(encoding="utf-8")
h264_check = h264.read_text(encoding="utf-8")
if "OS/libs/h264_avc/H264DecBackendAVC.cpp" in cmake_check or "OS/libs/h264_avc/H264DecInternal.h" in cmake_check:
    raise RuntimeError("modern async H264 backend still present in CMake")
for marker in (
    "_async_H264DECExecute",
    "coreinit::OSWaitEvent(&executeDoneEvent);",
    "void Initialize()",
    "V28 compatibility bridge",
    "COSModule* GetModule()",
):
    if marker not in h264_check:
        raise RuntimeError(f"V28 H264 marker missing: {marker}")

print("V28: exact v2.0-88 H264 decode path bridged into current Cemu module system")
