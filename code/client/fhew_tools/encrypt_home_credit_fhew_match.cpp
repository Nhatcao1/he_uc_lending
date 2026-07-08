#include "binfhecontext-ser.h"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

using namespace lbcrypto;

namespace {

struct Options {
    std::filesystem::path preparedDir;
    std::filesystem::path serverOutputDir;
    std::filesystem::path clientKeyDir;
    uint32_t idBits = 12;
    size_t maxLeft = 8;
    size_t maxRight = 8;
    std::string security = "TOY";
};

struct MatchRow {
    std::string side;
    uint32_t rowIndex = 0;
    uint32_t value = 0;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  encrypt_home_credit_fhew_match \\\n"
        << "    --prepared-dir <prepared_payload_dir> \\\n"
        << "    --server-output-dir <encrypted_payload_dir> \\\n"
        << "    --client-key-dir <keys_dir> \\\n"
        << "    [--id-bits 12] [--max-left 8] [--max-right 8] [--security TOY|STD128]\n";
    std::exit(error.empty() ? 0 : 2);
}

Options parseArgs(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto needValue = [&](const std::string& name) -> std::string {
            if (i + 1 >= argc) {
                usage("missing value for " + name);
            }
            return argv[++i];
        };

        if (arg == "--prepared-dir") {
            options.preparedDir = needValue(arg);
        }
        else if (arg == "--server-output-dir") {
            options.serverOutputDir = needValue(arg);
        }
        else if (arg == "--client-key-dir") {
            options.clientKeyDir = needValue(arg);
        }
        else if (arg == "--id-bits") {
            options.idBits = static_cast<uint32_t>(std::stoul(needValue(arg)));
        }
        else if (arg == "--max-left") {
            options.maxLeft = static_cast<size_t>(std::stoull(needValue(arg)));
        }
        else if (arg == "--max-right") {
            options.maxRight = static_cast<size_t>(std::stoull(needValue(arg)));
        }
        else if (arg == "--security") {
            options.security = needValue(arg);
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }

    if (options.preparedDir.empty() || options.serverOutputDir.empty() || options.clientKeyDir.empty()) {
        usage("prepared-dir, server-output-dir, and client-key-dir are required");
    }
    if (options.idBits == 0 || options.idBits > 32) {
        usage("id-bits must be in 1..32");
    }
    if (options.maxLeft == 0 || options.maxRight == 0) {
        usage("max-left and max-right must be positive");
    }
    if (options.security != "TOY" && options.security != "STD128") {
        usage("security must be TOY or STD128");
    }
    return options;
}

std::string trim(std::string value) {
    auto notSpace = [](unsigned char ch) { return !std::isspace(ch); };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), notSpace));
    value.erase(std::find_if(value.rbegin(), value.rend(), notSpace).base(), value.end());
    return value;
}

std::vector<std::string> splitCsvLine(const std::string& line) {
    std::vector<std::string> fields;
    std::string current;
    bool quoted = false;
    for (size_t i = 0; i < line.size(); ++i) {
        const char ch = line[i];
        if (ch == '"' && quoted && i + 1 < line.size() && line[i + 1] == '"') {
            current.push_back('"');
            ++i;
        }
        else if (ch == '"') {
            quoted = !quoted;
        }
        else if (ch == ',' && !quoted) {
            fields.push_back(trim(current));
            current.clear();
        }
        else {
            current.push_back(ch);
        }
    }
    fields.push_back(trim(current));
    return fields;
}

std::vector<std::map<std::string, std::string>> readCsv(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open CSV: " + path.string());
    }
    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("CSV is empty: " + path.string());
    }
    const auto header = splitCsvLine(line);
    std::vector<std::map<std::string, std::string>> rows;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != header.size()) {
            throw std::runtime_error("CSV row has wrong field count in " + path.string());
        }
        std::map<std::string, std::string> row;
        for (size_t i = 0; i < header.size(); ++i) {
            row[header[i]] = fields[i];
        }
        rows.push_back(row);
    }
    return rows;
}

std::vector<MatchRow> readSideRows(const std::filesystem::path& path, const std::string& side, size_t limit) {
    std::vector<MatchRow> rows;
    for (const auto& row : readCsv(path)) {
        if (row.at("side") != side) {
            continue;
        }
        MatchRow item;
        item.side = side;
        item.rowIndex = static_cast<uint32_t>(std::stoul(row.at("row_index")));
        item.value = static_cast<uint32_t>(std::stoul(row.at("token_prefix_u32")));
        rows.push_back(item);
        if (rows.size() >= limit) {
            break;
        }
    }
    return rows;
}

BINFHE_PARAMSET parseSecurity(const std::string& value) {
    if (value == "STD128") {
        return STD128;
    }
    return TOY;
}

std::string bitPath(const std::string& side, uint32_t rowIndex, uint32_t bit) {
    return side + "_bits/" + side.substr(0, 1) + std::to_string(rowIndex) + "_b" + std::to_string(bit) + ".bin";
}

void serializeCipherBit(
    const std::filesystem::path& root,
    const std::string& side,
    uint32_t rowIndex,
    uint32_t bit,
    const LWECiphertext& ciphertext) {
    const auto relative = bitPath(side, rowIndex, bit);
    const auto path = root / relative;
    std::filesystem::create_directories(path.parent_path());
    if (!Serial::SerializeToFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot serialize FHEW ciphertext: " + path.string());
    }
}

void encryptRows(
    BinFHEContext& cc,
    const LWEPrivateKey& sk,
    const std::filesystem::path& root,
    std::ofstream& manifest,
    const std::vector<MatchRow>& rows,
    uint32_t idBits) {
    for (const auto& row : rows) {
        for (uint32_t bit = 0; bit < idBits; ++bit) {
            const auto bitValue = static_cast<int>((row.value >> bit) & 1U);
            const auto ciphertext = cc.Encrypt(sk, bitValue);
            serializeCipherBit(root, row.side, row.rowIndex, bit, ciphertext);
            manifest << row.side << ',' << row.rowIndex << ',' << bit << ',' << bitPath(row.side, row.rowIndex, bit)
                     << '\n';
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto inputPath = options.preparedDir / "fhew_match_inputs.csv";
        const auto leftRows = readSideRows(inputPath, "left", options.maxLeft);
        const auto rightRows = readSideRows(inputPath, "right", options.maxRight);
        if (leftRows.empty() || rightRows.empty()) {
            throw std::runtime_error("fhew_match_inputs.csv must contain at least one left and one right row");
        }

        auto cc = BinFHEContext();
        cc.GenerateBinFHEContext(parseSecurity(options.security));
        const auto sk = cc.KeyGen();
        cc.BTKeyGen(sk);

        const auto fhewDir = options.serverOutputDir / "join" / "fhew";
        std::filesystem::create_directories(fhewDir);
        std::filesystem::create_directories(options.clientKeyDir);

        if (!Serial::SerializeToFile((fhewDir / "cryptoContext.bin").string(), cc, SerType::BINARY)) {
            throw std::runtime_error("cannot serialize FHEW crypto context");
        }
        if (!Serial::SerializeToFile((fhewDir / "refreshKey.bin").string(), cc.GetRefreshKey(), SerType::BINARY)) {
            throw std::runtime_error("cannot serialize FHEW refresh key");
        }
        if (!Serial::SerializeToFile((fhewDir / "ksKey.bin").string(), cc.GetSwitchKey(), SerType::BINARY)) {
            throw std::runtime_error("cannot serialize FHEW switching key");
        }
        if (!Serial::SerializeToFile((options.clientKeyDir / "fhew_secret_key.bin").string(), sk, SerType::BINARY)) {
            throw std::runtime_error("cannot serialize FHEW secret key");
        }
        if (!Serial::SerializeToFile((options.clientKeyDir / "fhew_crypto_context.bin").string(), cc, SerType::BINARY)) {
            throw std::runtime_error("cannot serialize client FHEW crypto context");
        }

        std::ofstream manifest(fhewDir / "fhew_match_manifest.csv");
        if (!manifest.is_open()) {
            throw std::runtime_error("cannot write FHEW match manifest");
        }
        manifest << "side,row_index,bit,ciphertext\n";
        encryptRows(cc, sk, fhewDir, manifest, leftRows, options.idBits);
        encryptRows(cc, sk, fhewDir, manifest, rightRows, options.idBits);

        std::ofstream metadata(fhewDir / "fhew_match_metadata.json");
        metadata << "{\n";
        metadata << "  \"scheme\": \"BinFHE/FHEW\",\n";
        metadata << "  \"security\": \"" << options.security << "\",\n";
        metadata << "  \"id_bits\": " << options.idBits << ",\n";
        metadata << "  \"left_rows\": " << leftRows.size() << ",\n";
        metadata << "  \"right_rows\": " << rightRows.size() << ",\n";
        metadata << "  \"pair_count\": " << (leftRows.size() * rightRows.size()) << ",\n";
        metadata << "  \"raw_ids_included\": false,\n";
        metadata << "  \"note\": \"Tiny encrypted equality benchmark. Pairwise gates scale as left_rows * right_rows * id_bits.\"\n";
        metadata << "}\n";

        std::cout << "encrypt_home_credit_fhew_match complete\n";
        std::cout << "server FHEW bundle: " << fhewDir << "\n";
        std::cout << "client FHEW key: " << (options.clientKeyDir / "fhew_secret_key.bin") << "\n";
        std::cout << "left rows: " << leftRows.size() << "\n";
        std::cout << "right rows: " << rightRows.size() << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "encrypt_home_credit_fhew_match failed: " << ex.what() << '\n';
        return 1;
    }
}
