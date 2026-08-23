from pathlib import Path
import sys

ROOT = Path('.')


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected exactly one match in {path}, found {count}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8', newline='\n')
    print(f'APPLIED: {label}')


# V1: data-driven NVN SSBO descriptor size detection.
replace_once(
    'src/video_core/buffer_cache/buffer_cache.h',
    '''    const auto size = [&]() {
        const bool is_nvn_cbuf = cbuf_index == 0;
        // The NVN driver buffer (index 0) is known to pack the SSBO address followed by its size.
        if (is_nvn_cbuf) {
            const u32 ssbo_size = gpu_memory->Read<u32>(ssbo_addr + 8);
            if (ssbo_size != 0) {
                return ssbo_size;
            }
        }
        // Other titles (notably Doom Eternal) may use STG/LDG on buffer addresses in custom defined
        // cbufs, which do not store the sizes adjacent to the addresses, so use the fully
        // mapped buffer size for now.
        const u32 memory_layout_size = static_cast<u32>(gpu_memory->GetMemoryLayoutSize(gpu_addr));
        return (std::min)(memory_layout_size, static_cast<u32>(8_MiB));
    }();''',
    '''    const auto size = [&]() {
        // NVN commonly packs an SSBO descriptor as { u64 gpu_addr, u32 size, u32 reserved }.
        // Detect the layout from descriptor data instead of assuming it only lives in cbuf 0.
        const u32 memory_layout_size =
            static_cast<u32>(gpu_memory->GetMemoryLayoutSize(gpu_addr));
        const u64 next_qword = gpu_memory->Read<u64>(ssbo_addr + 8);
        const u32 packed_size = static_cast<u32>(next_qword);
        const bool next_qword_is_size = static_cast<u32>(next_qword >> 32) == 0 &&
                                        packed_size != 0 &&
                                        packed_size <= memory_layout_size;
        if (next_qword_is_size) {
            return packed_size;
        }
        return (std::min)(memory_layout_size, static_cast<u32>(8_MiB));
    }();''',
    'V1 SSBO descriptor sizing',
)

# V2: remove process-global stale bindless fallback and keep fallback local to one TexturePass.
replace_once(
    'src/shader_recompiler/ir_opt/texture_pass.cpp',
    '''// TODO:xbzk: shall be dropped when Track method cover all bindless stuff
static ConstBufferAddr last_valid_addr = ConstBufferAddr{
    .index = 0,
    .offset = 0,
    .shift_left = 0,
    .secondary_index = 0,
    .secondary_offset = 0,
    .secondary_shift_left = 0,
    .dynamic_offset = {},
    .count = 1,
    .has_secondary = false,
};

TextureInst MakeInst(Environment& env, IR::Block* block, IR::Inst& inst) {''',
    '''TextureInst MakeInst(Environment& env, IR::Block* block, IR::Inst& inst,
                     std::optional<ConstBufferAddr>& last_valid_addr) {''',
    'V2 MakeInst local fallback signature',
)
replace_once(
    'src/shader_recompiler/ir_opt/texture_pass.cpp',
    '''        if (!track_addr) {
            //throw NotImplementedException("Failed to track bindless texture constant buffer");
            addr = last_valid_addr; // TODO:xbzk: shall be dropped when Track method cover all bindless stuff
        } else {
            addr = *track_addr;
            last_valid_addr = addr; // TODO:xbzk: shall be dropped when Track method cover all bindless stuff
        }''',
    '''        if (!track_addr) {
            if (!last_valid_addr) {
                throw NotImplementedException(
                    "Failed to track bindless texture constant buffer (no local fallback)");
            }
            addr = *last_valid_addr;
        } else {
            addr = *track_addr;
            last_valid_addr = addr;
        }''',
    'V2 bindless fallback isolation',
)
replace_once(
    'src/shader_recompiler/ir_opt/texture_pass.cpp',
    '''void TexturePass(Environment& env, IR::Program& program, const HostTranslateInfo& host_info) {
    TextureInstVector to_replace;''',
    '''void TexturePass(Environment& env, IR::Program& program, const HostTranslateInfo& host_info) {
    std::optional<ConstBufferAddr> last_valid_addr;
    TextureInstVector to_replace;''',
    'V2 per-pass fallback state',
)
replace_once(
    'src/shader_recompiler/ir_opt/texture_pass.cpp',
    '            to_replace.push_back(MakeInst(env, block, inst));',
    '            to_replace.push_back(MakeInst(env, block, inst, last_valid_addr));',
    'V2 MakeInst call',
)

# V3 stability backport: stable vector storage and batched scratch-buffer growth.
replace_once(
    'src/core/device_memory_manager.inc',
    '''#include <limits>
#include <memory>
#include <type_traits>

#include "common/address_space.h"''',
    '''#include <limits>
#include <memory>
#include <type_traits>
#include <vector>

#include <boost/container/deque.hpp>

#include "common/address_space.h"''',
    'V3 includes',
)
replace_once(
    'src/core/device_memory_manager.inc',
    '''    void GatherValues(u32 start_entry, Common::ScratchBuffer<u32>& buffer) {
        buffer.resize(8);
        buffer.resize(0);
        size_t index = 0;
        const auto add_value = [&](u32 value) {
            buffer.resize(index + 1);
            buffer[index++] = value;
        };

        u32 iter_entry = start_entry;
        Entry* current = &storage[iter_entry - 1];
        add_value(current->value);
        while (current->next_entry != 0) {
            iter_entry = current->next_entry;
            current = &storage[iter_entry - 1];
            add_value(current->value);
        }
    }''',
    '''    void GatherValues(u32 start_entry, Common::ScratchBuffer<u32>& buffer) {
        buffer.resize(8);
        const auto add_value = [&buffer](u32 value, size_t index) {
            if (buffer.size() < index + 1) {
                buffer.resize(index + 8);
            }
            buffer[index++] = value;
            return index;
        };

        size_t index = 0;
        u32 iter_entry = start_entry;
        Entry* current = &storage[iter_entry - 1];
        index = add_value(current->value, index);
        while (current->next_entry != 0) {
            iter_entry = current->next_entry;
            current = &storage[iter_entry - 1];
            index = add_value(current->value, index);
        }
        buffer.resize(index);
    }''',
    'V3 GatherValues stability',
)
replace_once(
    'src/core/device_memory_manager.inc',
    '''    std::deque<Entry> storage;
    std::deque<u32> free_entries;''',
    '''    std::vector<Entry> storage;
    boost::container::deque<u32> free_entries;''',
    'V3 stable storage containers',
)

# V4: source-location trace for the recurring 0x8A400000 / 4 MiB read.
replace_once(
    'src/core/device_memory_manager.h',
    '#include <mutex>\n',
    '#include <mutex>\n#include <source_location>\n',
    'V4 source_location include',
)
replace_once(
    'src/core/device_memory_manager.h',
    '''    void ReadBlock(DAddr address, void* dest_pointer, size_t size);
    void ReadBlockUnsafe(DAddr address, void* dest_pointer, size_t size);''',
    '''    void ReadBlock(DAddr address, void* dest_pointer, size_t size,
                   std::source_location caller = std::source_location::current());
    void ReadBlockUnsafe(DAddr address, void* dest_pointer, size_t size,
                         std::source_location caller = std::source_location::current());''',
    'V4 ReadBlock declarations',
)
replace_once(
    'src/core/device_memory_manager.inc',
    '''void DeviceMemoryManager<Traits>::Map(DAddr address, VAddr virtual_address, size_t size, Asid asid,
                                      bool track) {
    Core::Memory::Memory* process_memory = registered_processes[asid.id];''',
    '''void DeviceMemoryManager<Traits>::Map(DAddr address, VAddr virtual_address, size_t size, Asid asid,
                                      bool track) {
    const DAddr trace_end = address + static_cast<DAddr>(size);
    if (size >= (1ULL << 20) ||
        (address < 0x000000008B000000ULL && trace_end > 0x000000008A000000ULL)) {
        LOG_INFO(HW_Memory,
                 "SWITCH_SPORTS_TRACE_V4_20260823 MAP daddr={:#016x} vaddr={:#016x} size={} asid={} track={}",
                 address, virtual_address, size, asid.id, track);
    }
    Core::Memory::Memory* process_memory = registered_processes[asid.id];''',
    'V4 Map trace',
)
replace_once(
    'src/core/device_memory_manager.inc',
    '''void DeviceMemoryManager<Traits>::Unmap(DAddr address, size_t size) {
    size_t start_page_d = address >> Memory::YUZU_PAGEBITS;''',
    '''void DeviceMemoryManager<Traits>::Unmap(DAddr address, size_t size) {
    const DAddr trace_end = address + static_cast<DAddr>(size);
    if (size >= (1ULL << 20) ||
        (address < 0x000000008B000000ULL && trace_end > 0x000000008A000000ULL)) {
        LOG_INFO(HW_Memory,
                 "SWITCH_SPORTS_TRACE_V4_20260823 UNMAP daddr={:#016x} size={}", address, size);
    }
    size_t start_page_d = address >> Memory::YUZU_PAGEBITS;''',
    'V4 Unmap trace',
)
replace_once(
    'src/core/device_memory_manager.inc',
    '''void DeviceMemoryManager<Traits>::ReadBlock(DAddr address, void* dest_pointer, size_t size) {
    device_inter->FlushRegion(address, size);''',
    '''void DeviceMemoryManager<Traits>::ReadBlock(DAddr address, void* dest_pointer, size_t size,
                                            std::source_location caller) {
    const DAddr trace_end = address + static_cast<DAddr>(size);
    if (size >= (1ULL << 20) ||
        (address < 0x000000008B000000ULL && trace_end > 0x000000008A000000ULL)) {
        LOG_INFO(HW_Memory,
                 "SWITCH_SPORTS_TRACE_V4_20260823 READ_SAFE daddr={:#016x} size={} caller={}:{} function={}",
                 address, size, caller.file_name(), caller.line(), caller.function_name());
    }
    device_inter->FlushRegion(address, size);''',
    'V4 safe read caller trace',
)
replace_once(
    'src/core/device_memory_manager.inc',
    '''void DeviceMemoryManager<Traits>::ReadBlockUnsafe(DAddr address, void* dest_pointer, size_t size) {
    WalkBlock(''',
    '''void DeviceMemoryManager<Traits>::ReadBlockUnsafe(DAddr address, void* dest_pointer, size_t size,
                                                  std::source_location caller) {
    const DAddr trace_end = address + static_cast<DAddr>(size);
    if (size >= (1ULL << 20) ||
        (address < 0x000000008B000000ULL && trace_end > 0x000000008A000000ULL)) {
        LOG_INFO(HW_Memory,
                 "SWITCH_SPORTS_TRACE_V4_20260823 READ_UNSAFE daddr={:#016x} size={} caller={}:{} function={}",
                 address, size, caller.file_name(), caller.line(), caller.function_name());
    }
    WalkBlock(''',
    'V4 unsafe read caller trace',
)

marker = 'SWITCH_SPORTS_TRACE_V4_20260823'
combined = (ROOT / 'src/core/device_memory_manager.inc').read_text(encoding='utf-8')
if marker not in combined:
    raise RuntimeError('V4 marker missing after deterministic transforms')

print(f'ALL TRANSFORMS APPLIED; marker={marker}')
