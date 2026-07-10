#include <StormLib.h>

#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct Fixture {
    const char *name;
    unsigned mask;
    std::vector<unsigned char> input;
};

static void append_i16(std::vector<unsigned char> &bytes, int value) {
    const auto sample = static_cast<std::int16_t>(value);
    const auto bits = static_cast<std::uint16_t>(sample);
    bytes.push_back(static_cast<unsigned char>(bits));
    bytes.push_back(static_cast<unsigned char>(bits >> 8));
}

static std::vector<unsigned char> make_mono() {
    std::vector<unsigned char> bytes;
    bytes.reserve(8192);
    for (int index = 0; index < 4096; ++index) {
        const int saw = (index * 97) % 4096 - 2048;
        const int bend = ((index / 73) % 2) ? index % 257 : 256 - index % 257;
        append_i16(bytes, saw * 11 + bend * 19);
    }
    return bytes;
}

static std::vector<unsigned char> make_stereo() {
    std::vector<unsigned char> bytes;
    bytes.reserve(16384);
    for (int index = 0; index < 4096; ++index) {
        const int left = ((index * 61) % 4096 - 2048) * 12;
        const int right = ((index * 149) % 4096 - 2048) * 9;
        append_i16(bytes, left + (index % 127) * 13);
        append_i16(bytes, right - (index % 89) * 17);
    }
    return bytes;
}

static std::vector<unsigned char> make_sparse() {
    std::vector<unsigned char> bytes(16384, 0);
    const std::string phrase = "StormLib 9.25 sparse+zlib fixture ";
    for (size_t offset = 0; offset < bytes.size(); offset += 1024) {
        for (size_t index = 0; index < phrase.size(); ++index)
            bytes[offset + 128 + index] = static_cast<unsigned char>(phrase[index]);
        bytes[offset + 511] = static_cast<unsigned char>(offset / 1024);
        bytes[offset + 768] = static_cast<unsigned char>((offset * 37) >> 8);
    }
    return bytes;
}

static std::vector<unsigned char> make_lzma() {
    std::vector<unsigned char> bytes;
    const std::string phrase = "StormLib 9.25 LZMA reference sector ";
    while (bytes.size() < 16384) {
        bytes.insert(bytes.end(), phrase.begin(), phrase.end());
        bytes.push_back(static_cast<unsigned char>(bytes.size() * 29));
        bytes.push_back(static_cast<unsigned char>(bytes.size() >> 5));
    }
    bytes.resize(16384);
    return bytes;
}

static bool decompress(const std::vector<unsigned char> &compressed,
                       unsigned mask, std::vector<unsigned char> *expected) {
    int length = static_cast<int>(expected->size());
    // v9.25 SCompDecompress asserts for 0x12; its public v2 entry point owns LZMA.
    const int ok = mask == MPQ_COMPRESSION_LZMA
        ? SCompDecompress2(expected->data(), &length,
                           const_cast<unsigned char *>(compressed.data()),
                           static_cast<int>(compressed.size()))
        : SCompDecompress(expected->data(), &length,
                          const_cast<unsigned char *>(compressed.data()),
                          static_cast<int>(compressed.size()));
    if (!ok || length < 0 || static_cast<size_t>(length) > expected->size())
        return false;
    expected->resize(static_cast<size_t>(length));
    return true;
}

static bool write_fixture(const fs::path &output, const Fixture &fixture) {
    std::vector<unsigned char> compressed(fixture.input.size() + 1024);
    int compressed_length = static_cast<int>(compressed.size());
    if (!SCompCompress(compressed.data(), &compressed_length,
                       const_cast<unsigned char *>(fixture.input.data()),
                       static_cast<int>(fixture.input.size()), fixture.mask, 0, 0) ||
        compressed_length < 1 ||
        static_cast<size_t>(compressed_length) > compressed.size()) {
        return false;
    }
    compressed.resize(static_cast<size_t>(compressed_length));
    if (compressed[0] != fixture.mask)
        return false;

    std::vector<unsigned char> expected(fixture.input.size());
    if (!decompress(compressed, fixture.mask, &expected))
        return false;

    // Verify the exact payload about to be committed through StormLib again.
    std::vector<unsigned char> verified(fixture.input.size());
    if (!decompress(compressed, fixture.mask, &verified) || verified != expected)
        return false;

    std::ofstream stream(output, std::ios::binary);
    if (!stream)
        return false;
    const std::array<unsigned char, 16> header = {
        'W', '3', 'C', 'F',
        static_cast<unsigned char>(fixture.mask), 0, 0, 0,
        static_cast<unsigned char>(compressed.size()),
        static_cast<unsigned char>(compressed.size() >> 8),
        static_cast<unsigned char>(compressed.size() >> 16),
        static_cast<unsigned char>(compressed.size() >> 24),
        static_cast<unsigned char>(expected.size()),
        static_cast<unsigned char>(expected.size() >> 8),
        static_cast<unsigned char>(expected.size() >> 16),
        static_cast<unsigned char>(expected.size() >> 24),
    };
    stream.write(reinterpret_cast<const char *>(header.data()), header.size());
    stream.write(reinterpret_cast<const char *>(compressed.data()), compressed.size());
    stream.write(reinterpret_cast<const char *>(expected.data()), expected.size());
    return stream.good();
}

static bool write_input(const fs::path &output, const Fixture &fixture) {
    std::ofstream stream(output / (std::string(fixture.name) + ".input"),
                        std::ios::binary);
    stream.write(reinterpret_cast<const char *>(fixture.input.data()),
                 fixture.input.size());
    return stream.good();
}

int main(int argc, char **argv) {
    if (argc != 2 && argc != 3) {
        std::cerr << "usage: build_compression_fixtures output-directory [--inputs]\n";
        return 2;
    }
    const bool write_inputs = argc == 3 && std::string(argv[2]) == "--inputs";
    if (argc == 3 && !write_inputs)
        return 2;
    const fs::path output(argv[1]);
    std::error_code error;
    fs::create_directories(output, error);
    if (error)
        return 3;
    const std::array<Fixture, 4> fixtures = {{
        {"stormlib-compression-huffman-adpcm-mono.bin", 0x41, make_mono()},
        {"stormlib-compression-huffman-adpcm-stereo.bin", 0x81, make_stereo()},
        {"stormlib-compression-zlib-sparse.bin", 0x22, make_sparse()},
        {"stormlib-compression-lzma.bin", 0x12, make_lzma()},
    }};
    for (const Fixture &fixture : fixtures) {
        if (!write_fixture(output / fixture.name, fixture) ||
            (write_inputs && !write_input(output, fixture))) {
            std::cerr << "failed: " << fixture.name << "\n";
            return 4;
        }
    }
    return 0;
}
