from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v27_wii_party_u_h264_sync.py <cemu-source-root>")

root = Path(sys.argv[1])
internal = root / "src/Cafe/OS/libs/h264_avc/H264DecInternal.h"
backend = root / "src/Cafe/OS/libs/h264_avc/H264DecBackendAVC.cpp"
h264 = root / "src/Cafe/OS/libs/h264_avc/H264Dec.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V27 Wii Party U regression test.
# Cemu 2.0-88 waits for each H264 decode operation to finish before H264DECExecute
# returns. Starting with 2.0-89 / PR #1257, buffered H264 can queue work ahead.
# Keep the modern decoder and frame buffering, but restore per-execute decode
# completion ordering for Wii Party U USA only.

replace_once(
    internal,
    '#include "util/helpers/Semaphore.h"\n',
    '#include "util/helpers/Semaphore.h"\n#include <condition_variable>\n',
    "add condition_variable for strict H264 execute synchronization",
)

replace_once(
    internal,
    '''\t\tstruct DecodedSlice\n\t\t{\n\t\t\tbool isUsed{false};\n\t\t\tDecodeResult result;\n\t\t\tDataToDecode dataToDecode;\n\t\t};\n''',
    '''\t\tstruct DecodedSlice\n\t\t{\n\t\t\tbool isUsed{false};\n\t\t\t// V27: tracks completion of the CPU decode operation independently\n\t\t\t// from whether the codec produced a displayable frame.\n\t\t\tbool decodeFinished{false};\n\t\t\tDecodeResult result;\n\t\t\tDataToDecode dataToDecode;\n\t\t};\n''',
    "track H264 decode completion per queued slice",
)

replace_once(
    internal,
    '''\t\tvoid QueueForDecode(uint8* data, uint32 length, double timestamp, void* imagePtr)\n\t\t{\n\t\t\tstd::unique_lock _l(m_decodeQueueMtx);\n\n\t\t\tDecodedSlice& ds = GetFreeDecodedSliceEntry();\n\n\t\t\tds.dataToDecode.m_buffer.assign(data, data + length);\n\t\t\tds.dataToDecode.m_data = ds.dataToDecode.m_buffer.data();\n\t\t\tds.dataToDecode.m_length = length;\n\n\t\t\tds.result.isDecoded = false;\n\t\t\tds.result.imageOutput = imagePtr;\n\t\t\tds.result.timestamp = timestamp;\n\n\t\t\tm_decodeQueue.push_back(std::distance(m_decodedSliceArray.data(), &ds));\n\t\t\tm_decodeSem.increment();\n\t\t}\n''',
    '''\t\tuint32 QueueForDecode(uint8* data, uint32 length, double timestamp, void* imagePtr)\n\t\t{\n\t\t\tstd::unique_lock _l(m_decodeQueueMtx);\n\n\t\t\tDecodedSlice& ds = GetFreeDecodedSliceEntry();\n\n\t\t\tds.dataToDecode.m_buffer.assign(data, data + length);\n\t\t\tds.dataToDecode.m_data = ds.dataToDecode.m_buffer.data();\n\t\t\tds.dataToDecode.m_length = length;\n\n\t\t\tds.result.isDecoded = false;\n\t\t\tds.result.imageOutput = imagePtr;\n\t\t\tds.result.timestamp = timestamp;\n\t\t\tds.decodeFinished = false;\n\n\t\t\tconst uint32 sliceIndex = (uint32)std::distance(m_decodedSliceArray.data(), &ds);\n\t\t\tm_decodeQueue.push_back(sliceIndex);\n\t\t\tm_decodeSem.increment();\n\t\t\treturn sliceIndex;\n\t\t}\n\n\t\tvoid WaitForDecodeCompletion(uint32 sliceIndex)\n\t\t{\n\t\t\tstd::unique_lock _l(m_decodeQueueMtx);\n\t\t\tm_decodeFinishedCv.wait(_l, [&]\n\t\t\t{\n\t\t\t\treturn m_decodedSliceArray[sliceIndex].decodeFinished;\n\t\t\t});\n\t\t}\n''',
    "return queued slice index and expose decode-completion wait",
)

replace_once(
    internal,
    '''\t\tstd::mutex m_decodeQueueMtx;\n\t\tstd::vector<uint32> m_decodeQueue; // indices into m_decodedSliceArray, in order of decode input\n''',
    '''\t\tstd::mutex m_decodeQueueMtx;\n\t\tstd::condition_variable m_decodeFinishedCv;\n\t\tstd::vector<uint32> m_decodeQueue; // indices into m_decodedSliceArray, in order of decode input\n''',
    "add decode-completion condition variable",
)

replace_once(
    backend,
    '''\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\tauto& decodedSlice = m_decodedSliceArray[decodeIndex];\n\t\t\t\t\tDecode(decodedSlice);\n\t\t\t\t}\n''',
    '''\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\tauto& decodedSlice = m_decodedSliceArray[decodeIndex];\n\t\t\t\t\tDecode(decodedSlice);\n\n\t\t\t\t\t// V27: signal CPU decode completion even when no frame was output.\n\t\t\t\t\t// This lets Wii Party U restore the 2.0-88 H264DECExecute ordering\n\t\t\t\t\t// without disabling the modern backend or its frame buffering.\n\t\t\t\t\t_l.lock();\n\t\t\t\t\tdecodedSlice.decodeFinished = true;\n\t\t\t\t\t_l.unlock();\n\t\t\t\t\tm_decodeFinishedCv.notify_all();\n\t\t\t\t}\n''',
    "signal completion after each backend decode",
)

replace_once(
    h264,
    '''\t\t// feed data to backend\n\t\tsession->QueueForDecode((uint8*)ctx->BitStream.ptr.GetPtr(), ctx->BitStream.length, ctx->BitStream.timestamp, imageOutput);\n\t\tctx->decoderState.numFramesInFlight++;\n''',
    '''\t\t// feed data to backend\n\t\tconst uint32 queuedSliceIndex = session->QueueForDecode((uint8*)ctx->BitStream.ptr.GetPtr(), ctx->BitStream.length, ctx->BitStream.timestamp, imageOutput);\n\t\tctx->decoderState.numFramesInFlight++;\n\n\t\t// V27 Wii Party U compatibility: 2.0-88 completed each CPU decode before\n\t\t// returning from H264DECExecute. 2.0-89 introduced queued asynchronous\n\t\t// decode-ahead and Wii Party U regressed exactly at that version boundary.\n\t\t// Restore only the decode-completion ordering for the verified USA title.\n\t\tif (CafeSystem::GetForegroundTitleId() == 0x0005000010137D00ULL)\n\t\t\tsession->WaitForDecodeCompletion(queuedSliceIndex);\n''',
    "restore strict H264 execute decode ordering for Wii Party U USA",
)

# Verify the patch is scoped exactly where intended.
internal_text = internal.read_text(encoding="utf-8")
backend_text = backend.read_text(encoding="utf-8")
h264_text = h264.read_text(encoding="utf-8")

required_internal = [
    "bool decodeFinished{false};",
    "uint32 QueueForDecode",
    "WaitForDecodeCompletion",
    "m_decodeFinishedCv",
]
for marker in required_internal:
    if marker not in internal_text:
        raise RuntimeError(f"V27 internal verification marker missing: {marker}")

for marker in ["decodedSlice.decodeFinished = true;", "m_decodeFinishedCv.notify_all();"]:
    if marker not in backend_text:
        raise RuntimeError(f"V27 backend verification marker missing: {marker}")

for marker in [
    "queuedSliceIndex",
    "0x0005000010137D00ULL",
    "session->WaitForDecodeCompletion(queuedSliceIndex);",
]:
    if marker not in h264_text:
        raise RuntimeError(f"V27 H264 verification marker missing: {marker}")

print("Applied V27 Wii Party U USA strict H264 execute synchronization test")
