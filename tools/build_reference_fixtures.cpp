#include <StormLib.h>

#include <filesystem>
#include <fstream>
#include <iostream>

namespace fs = std::filesystem;

static bool add_file(HANDLE archive, const fs::path &source, const char *name,
                     DWORD compression) {
    return SFileAddFileEx(
        archive,
        source.string().c_str(),
        name,
        MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING,
        compression,
        compression);
}

static bool build_slk_map(const fs::path &base_map, const fs::path &slk,
                          const fs::path &output) {
    fs::copy_file(base_map, output, fs::copy_options::overwrite_existing);
    HANDLE archive = nullptr;
    if (!SFileOpenArchive(output.string().c_str(), 0, 0, &archive)) {
        return false;
    }
    const bool ok = add_file(
        archive, slk, "Units\\AbilityData.slk", MPQ_COMPRESSION_ZLIB);
    SFileCloseArchive(archive);
    return ok;
}

static bool build_campaign(const fs::path &map, const fs::path &object_map,
                           const fs::path &output) {
    const fs::path object_file = output.string() + ".w3a";
    HANDLE source = nullptr;
    if (!SFileOpenArchive(object_map.string().c_str(), 0, 0, &source)) {
        return false;
    }
    const bool extracted = SFileExtractFile(
        source, "war3map.w3a", object_file.string().c_str(), 0);
    SFileCloseArchive(source);
    if (!extracted) {
        return false;
    }
    HANDLE archive = nullptr;
    if (!SFileCreateArchive(
            output.string().c_str(), MPQ_CREATE_LISTFILE, 16, &archive)) {
        return false;
    }
    const bool map_ok = add_file(
        archive, map, "Maps\\Chapter1.w3x", MPQ_COMPRESSION_ZLIB);
    const bool object_ok = add_file(
        archive, object_file, "war3campaign.w3a", MPQ_COMPRESSION_ZLIB);
    SFileCloseArchive(archive);
    fs::remove(object_file);
    return map_ok && object_ok;
}

static bool build_huffman_map(const fs::path &output, const fs::path &script) {
    std::ofstream out(script, std::ios::binary);
    for (int index = 0; index < 500; ++index) {
        out << "function HuffFixture takes nothing returns nothing\n"
            << "    call BJDebugMsg(\"StormLib Huffman reference sector\")\n"
            << "endfunction\n";
    }
    out.close();
    HANDLE archive = nullptr;
    if (!SFileCreateArchive(
            output.string().c_str(), MPQ_CREATE_LISTFILE, 16, &archive)) {
        return false;
    }
    const bool ok = add_file(
        archive, script, "war3map.j", MPQ_COMPRESSION_HUFFMANN);
    SFileCloseArchive(archive);
    return ok;
}

int main(int argc, char **argv) {
    if (argc != 8) {
        std::cerr
            << "usage: generator base.w3x source.slk object-map.w3x slk.w3x "
               "campaign.w3n huff.w3x plain.j\n";
        return 2;
    }
    if (!build_slk_map(argv[1], argv[2], argv[4])) {
        std::cerr << "SLK map creation failed\n";
        return 3;
    }
    if (!build_campaign(argv[4], argv[3], argv[5])) {
        std::cerr << "campaign creation failed\n";
        return 4;
    }
    if (!build_huffman_map(argv[6], argv[7])) {
        std::cerr << "Huffman map creation failed\n";
        return 5;
    }
    return 0;
}
