from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v28_legacy_h264_cmake.py <cemu-source-root>")

root = Path(sys.argv[1])
cmake = root / "src/Cafe/CMakeLists.txt"
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
check = cmake.read_text(encoding="utf-8")
if "OS/libs/h264_avc/H264DecBackendAVC.cpp" in check or "OS/libs/h264_avc/H264DecInternal.h" in check:
    raise RuntimeError("modern async H264 backend still present in CMake")
if "OS/libs/h264_avc/H264Dec.cpp" not in check:
    raise RuntimeError("legacy H264Dec.cpp source entry missing")

print("V28: modern async backend removed from CMake; exact v2.0-88 H264Dec will be built")
