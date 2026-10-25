// SPDX-License-Identifier: MIT
// Host test for the independently written cache loader. No GPU or client data.
#include <cstdint>
#include <iridium/iridium.hpp>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <vector>
#include <unistd.h>

// Hashing is supplied by CommonCrypto in the Mach build. Use a fixed cache key
// here so packet-validation tests don't require another crypto dependency.
extern "C" unsigned char *CC_SHA256(const void *, unsigned int, unsigned char *output) {
    std::memset(output, 0, 32);
    return output;
}
static void integer(std::vector<unsigned char>& packet, uint32_t value) {
    for (unsigned int shift = 0; shift < 32; shift += 8)
        packet.push_back(static_cast<unsigned char>(value >> shift));
}
static std::vector<unsigned char> packet(uint32_t count = 1) {
    std::vector<unsigned char> result {'M', 'V', 'K', '1'};
    for (uint32_t value: {1u, 1u, 5u, count, 68u}) integer(result, value);
    for (char value: std::string("main0")) result.push_back(value);
    for (uint32_t i = 0; i < count; ++i)
        for (uint32_t value: {4u, i, i, 0u}) integer(result, value);
    for (uint32_t value: {0x07230203u, 0x00010500u, 0u, 4u, 0u,
                         5u << 16 | 15u, 0u, 1u, 0x6e69616du, 0x30u,
                         5u << 16 | 54u, 2u, 1u, 0u, 3u,
                         1u << 16 | 253u, 1u << 16 | 56u}) integer(result, value);
    return result;
}
int main() {
    char temporary[] = "/tmp/quadra-metal-adapter-XXXXXX";
    const char *directory = mkdtemp(temporary);
    assert(directory);
    setenv("MACOBLOX_METAL_SHADER_CACHE", directory, 1);
    std::string path = std::string(directory) + "/" + std::string(64, '0') + ".mvk";
    auto save = [&](const std::vector<unsigned char>& data) {
        std::ofstream file(path, std::ios::binary);
        file.write(reinterpret_cast<const char *>(data.data()), data.size());
    };
    auto rejected = [&](const std::vector<unsigned char>& data) {
        save(data);
        size_t size = 99;
        Iridium::OutputInfo output;
        try {
            auto result = Iridium::translate("fixture", 7, size, output);
            std::free(result);
            assert(false && "malformed packet accepted");
        } catch (const std::runtime_error&) {
            assert(size == 0 && output.functionInfos.empty());
        }
    };
    save(packet());
    size_t size = 0;
    Iridium::OutputInfo output;
    auto result = Iridium::translate("fixture", 7, size, output);
    assert(result && size == 68);
    auto& info = output.functionInfos.at("main0");
    assert(info.type == Iridium::FunctionType::Vertex && info.bindings.size() == 1);
    assert(static_cast<int>(info.bindings[0].type) == 4);
    std::free(result);
    rejected({});
    auto invalid = packet(); invalid[0] = 'X'; rejected(invalid);
    invalid = packet(); invalid.pop_back(); rejected(invalid);
    invalid = packet(); invalid.push_back(0); rejected(invalid);
    invalid = packet(); invalid[8] = 3; rejected(invalid); // compute ABI unsupported
    invalid = packet(); invalid[24] = 0; rejected(invalid); // embedded NUL in name
    invalid = packet(); invalid[29] = 0; rejected(invalid); // legacy address Buffer ABI
    invalid = packet(); invalid[33] = 128; rejected(invalid); // unbounded index
    invalid = packet(); invalid[45] = 0; rejected(invalid); // bad SPIR-V magic
    invalid = packet(); invalid[69] = 4; rejected(invalid); // wrong execution model
    invalid = packet(); invalid[77] = 'X'; rejected(invalid); // wrong entry name
    invalid = packet(); invalid[93] = 3; rejected(invalid); // no matching function
    invalid = packet(2); invalid[53] = 0; rejected(invalid); // duplicate binding
    unlink(path.c_str());
    rmdir(directory);
    return 0;
}
