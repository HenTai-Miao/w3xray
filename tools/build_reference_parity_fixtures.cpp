#include <StormLib.h>

#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

struct StringField {
    std::string id;
    std::string value;
};

static bool add_file(HANDLE archive, const fs::path &source, const char *name) {
    return SFileAddFileEx(
        archive, source.string().c_str(), name,
        MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING,
        MPQ_COMPRESSION_ZLIB, MPQ_COMPRESSION_ZLIB);
}

static std::string bytes(std::initializer_list<unsigned int> values) {
    std::string result;
    result.reserve(values.size());
    for (const unsigned int value : values) {
        result.push_back(static_cast<char>(value));
    }
    return result;
}

static bool write_bytes(const fs::path &path, const std::string &data) {
    fs::create_directories(path.parent_path());
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream.write(data.data(), static_cast<std::streamsize>(data.size()));
    return static_cast<bool>(stream);
}

static bool append_bytes(const fs::path &path, const std::string &data) {
    std::ofstream stream(path, std::ios::binary | std::ios::app);
    stream.write(data.data(), static_cast<std::streamsize>(data.size()));
    return static_cast<bool>(stream);
}

static void put_u32(std::ofstream &stream, std::uint32_t value) {
    const char raw[4] = {
        static_cast<char>(value & 0xFFU),
        static_cast<char>((value >> 8U) & 0xFFU),
        static_cast<char>((value >> 16U) & 0xFFU),
        static_cast<char>((value >> 24U) & 0xFFU),
    };
    stream.write(raw, 4);
}

static void put_i32(std::ofstream &stream, std::int32_t value) {
    put_u32(stream, static_cast<std::uint32_t>(value));
}

static void put_f32(std::ofstream &stream, float value) {
    static_assert(sizeof(float) == sizeof(std::uint32_t));
    std::uint32_t raw = 0;
    std::memcpy(&raw, &value, sizeof(raw));
    put_u32(stream, raw);
}

static void put_tag(std::ofstream &stream, const std::string &value) {
    stream.write(value.data(), 4);
}

static void put_cstr(std::ofstream &stream, const std::string &value) {
    stream.write(value.data(), static_cast<std::streamsize>(value.size()));
    stream.put('\0');
}

static bool write_object_file(
    const fs::path &path,
    const std::string &old_id,
    const std::string &new_id,
    const std::vector<StringField> &fields,
    bool levelled) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    put_i32(stream, 2);
    put_i32(stream, 0);
    put_i32(stream, 1);
    put_tag(stream, old_id);
    put_tag(stream, new_id);
    put_i32(stream, static_cast<std::int32_t>(fields.size()));
    for (const StringField &field : fields) {
        put_tag(stream, field.id);
        put_i32(stream, 3);
        if (levelled) {
            put_i32(stream, 1);
            put_i32(stream, 0);
        }
        put_cstr(stream, field.value);
        put_u32(stream, 0);
    }
    return static_cast<bool>(stream);
}

static bool write_text_sources(const fs::path &stage) {
    const std::string unit_name = bytes({0xCA, 0xA5, 0xC6, 0xEF, 0xCA, 0xBF});
    const std::string proper_name = bytes({0xB9, 0xE2, 0xC3, 0xF7, 0xCA, 0xB9, 0xD5, 0xDF});
    const std::string item_name = bytes({0xB2, 0xE2, 0xCA, 0xD4, 0xCE, 0xEF, 0xC6, 0xB7});
    const std::string ability_name = bytes({0xB2, 0xE2, 0xCA, 0xD4, 0xBC, 0xBC, 0xC4, 0xDC});
    const std::string upgrade_name = bytes({0xB2, 0xE2, 0xCA, 0xD4, 0xBF, 0xC6, 0xBC, 0xBC});
    bool ok = true;
    ok = write_bytes(stage / "HumanUnitStrings.txt", "[H001]\nName=" + unit_name +
        "\nPropernames=" + proper_name + "\nUbertip=TRIGSTR_904\n") && ok;
    ok = write_bytes(stage / "HumanUnitFunc.txt", "[H001]\nName=Internal Unit\nHP=1800\n") && ok;
    ok = write_bytes(stage / "ItemStrings.txt", "[I001]\nName=" + item_name + "\n") && ok;
    ok = write_bytes(stage / "ItemFunc.txt", "[I001]\ngoldcost=777\n") && ok;
    ok = write_bytes(stage / "HumanAbilityStrings.txt", "[A001]\nName=" + ability_name + "\n") && ok;
    ok = write_bytes(stage / "HumanAbilityFunc.txt", "[A001]\nlevels=3\n") && ok;
    ok = write_bytes(stage / "HumanUpgradeStrings.txt", "[R001]\nName=" + upgrade_name + "\n") && ok;
    ok = write_bytes(stage / "HumanUpgradeFunc.txt", "[R001]\nmaxlevel=3\n") && ok;
    return ok;
}

static bool write_parity_sources(const fs::path &stage) {
    bool ok = write_text_sources(stage);
    ok = write_bytes(stage / "AbilityData.slk",
        "ID;P\nB;X4;Y2\nC;X1;Y1;K\"alias\"\nC;X2;Y1;K\"Name\"\n"
        "C;X3;Y1;K\"levels\"\nC;X4;Y1;K\"DataA1\"\n"
        "C;X1;Y2;K\"A001\"\nC;X2;Y2;K\"SLK Ability\"\n"
        "C;X3;Y2;K\"3\"\nC;X4;Y2;K\"777\"\nE\n") && ok;
    ok = write_bytes(stage / "war3map.lua",
        "function ParityLua()\n  print(\"TRIGSTR_904\")\n  return FourCC(\"A001\")\nend\n") && ok;
    ok = write_object_file(stage / "war3map.w3u", "hfoo", "H001",
        {{"unam", "TRIGSTR_900"}, {"utip", "TRIGSTR_904"}}, false) && ok;
    ok = write_object_file(stage / "war3map.w3t", "ratf", "I001",
        {{"unam", "TRIGSTR_901"}}, false) && ok;
    ok = write_object_file(stage / "war3map.w3a", "AHbz", "A001",
        {{"anam", "TRIGSTR_902"}}, true) && ok;
    ok = write_object_file(stage / "war3map.w3q", "Rhme", "R001",
        {{"gnam", "TRIGSTR_903"}}, true) && ok;
    return ok;
}

static bool append_base_sources(HANDLE archive, const fs::path &stage) {
    const fs::path wts = stage / "war3map.wts";
    const fs::path jass = stage / "war3map.j";
    if (!SFileExtractFile(archive, "war3map.wts", wts.string().c_str(), 0) ||
        !SFileExtractFile(archive, "war3map.j", jass.string().c_str(), 0)) {
        return false;
    }
    const std::string binary_unit = bytes({0xB6, 0xFE, 0xBD, 0xF8, 0xD6, 0xC6, 0xB5, 0xA5, 0xCE, 0xBB});
    const std::string item = bytes({0xB2, 0xE2, 0xCA, 0xD4, 0xCE, 0xEF, 0xC6, 0xB7});
    const std::string ability = bytes({0xB2, 0xE2, 0xCA, 0xD4, 0xBC, 0xBC, 0xC4, 0xDC});
    const std::string upgrade = bytes({0xB2, 0xE2, 0xCA, 0xD4, 0xBF, 0xC6, 0xBC, 0xBC});
    const std::string description = bytes({0xCB, 0xB5, 0xC3, 0xF7, 0xCE, 0xC4, 0xB1, 0xBE});
    const std::string blocks = "\nSTRING 900\n{\n" + binary_unit + "\n}\nSTRING 901\n{\n" +
        item + "\n}\nSTRING 902\n{\n" + ability + "\n}\nSTRING 903\n{\n" + upgrade +
        "\n}\nSTRING 904\n{\n" + description + "\n}\n";
    return append_bytes(wts, blocks) && append_bytes(jass,
        "\nfunction ParityJass takes nothing returns nothing\n"
        "    call BJDebugMsg(\"TRIGSTR_904\")\n"
        "    call UnitAddAbility(null, 'A001')\nendfunction\n");
}

static bool build_map(const fs::path &base, const fs::path &output) {
    fs::copy_file(base, output, fs::copy_options::overwrite_existing);
    const fs::path stage = output.string() + ".sources";
    fs::remove_all(stage);
    fs::create_directories(stage);
    HANDLE archive = nullptr;
    if (!SFileOpenArchive(output.string().c_str(), 0, 0, &archive)) {
        fs::remove_all(stage);
        return false;
    }
    bool ok = append_base_sources(archive, stage) && write_parity_sources(stage);
    const std::vector<std::pair<std::string, std::string>> files = {
        {"war3map.wts", "war3map.wts"}, {"war3map.j", "war3map.j"},
        {"war3map.lua", "war3map.lua"}, {"AbilityData.slk", "Units\\AbilityData.slk"},
        {"HumanUnitStrings.txt", "Units\\HumanUnitStrings.txt"},
        {"HumanUnitFunc.txt", "Units\\HumanUnitFunc.txt"},
        {"ItemStrings.txt", "Units\\ItemStrings.txt"}, {"ItemFunc.txt", "Units\\ItemFunc.txt"},
        {"HumanAbilityStrings.txt", "Units\\HumanAbilityStrings.txt"},
        {"HumanAbilityFunc.txt", "Units\\HumanAbilityFunc.txt"},
        {"HumanUpgradeStrings.txt", "Units\\HumanUpgradeStrings.txt"},
        {"HumanUpgradeFunc.txt", "Units\\HumanUpgradeFunc.txt"},
        {"war3map.w3u", "war3map.w3u"}, {"war3map.w3t", "war3map.w3t"},
        {"war3map.w3a", "war3map.w3a"}, {"war3map.w3q", "war3map.w3q"},
    };
    for (const auto &[source, name] : files) {
        ok = add_file(archive, stage / source, name.c_str()) && ok;
    }
    SFileCloseArchive(archive);
    fs::remove_all(stage);
    return ok;
}

static bool write_w3f(const fs::path &path) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    put_i32(stream, 1); put_i32(stream, 1); put_i32(stream, 1);
    put_cstr(stream, "Reference parity campaign"); put_cstr(stream, "Normal");
    put_cstr(stream, "w3xray"); put_cstr(stream, "Static extraction fixture");
    put_i32(stream, 0); put_i32(stream, 0); put_cstr(stream, ""); put_cstr(stream, "");
    put_i32(stream, 0); put_cstr(stream, ""); put_i32(stream, 0);
    put_f32(stream, 0.0F); put_f32(stream, 0.0F); put_f32(stream, 0.0F);
    put_u32(stream, 0); put_i32(stream, 0);
    put_i32(stream, 1); put_i32(stream, 1); put_cstr(stream, "Chapter 1");
    put_cstr(stream, "Parity map"); put_cstr(stream, "Maps\\Parity01.w3x");
    put_i32(stream, 1); put_cstr(stream, "Chapter 1"); put_cstr(stream, "Maps\\Parity01.w3x");
    return static_cast<bool>(stream);
}

static bool build_campaign(const fs::path &map, const fs::path &output) {
    fs::remove(output);
    const fs::path w3f = output.string() + ".w3f";
    if (!write_w3f(w3f)) {
        return false;
    }
    HANDLE archive = nullptr;
    if (!SFileCreateArchive(output.string().c_str(), MPQ_CREATE_LISTFILE, 8, &archive)) {
        fs::remove(w3f);
        return false;
    }
    const bool ok = add_file(archive, map, "Maps\\Parity01.w3x") &&
        add_file(archive, w3f, "war3campaign.w3f");
    SFileCloseArchive(archive);
    fs::remove(w3f);
    return ok;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        std::cerr << "usage: generator base.w3x parity-map.w3x parity-campaign.w3n\n";
        return 2;
    }
    if (!build_map(argv[1], argv[2])) {
        std::cerr << "reference parity map creation failed\n";
        return 3;
    }
    if (!build_campaign(argv[2], argv[3])) {
        std::cerr << "reference parity campaign creation failed\n";
        return 4;
    }
    return 0;
}
