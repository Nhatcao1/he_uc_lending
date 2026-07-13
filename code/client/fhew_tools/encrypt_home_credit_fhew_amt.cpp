#include "binfhecontext-ser.h"

#include <algorithm>
#include <cmath>
#include <cctype>
#include <chrono>
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
    std::filesystem::path inputCsv;
    std::filesystem::path serverOutputDir;
    std::filesystem::path clientKeyDir;
    std::string column = "AMT_CREDIT";
    uint32_t bitWidth = 24;
    size_t rowLimit = 1000;
    std::string security = "TOY";
};

struct AmountRow {
    uint32_t rowIndex = 0;
    uint64_t value = 0;
    bool valid = false;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  encrypt_home_credit_fhew_amt \\\n"
        << "    --input data/home_credit/application_train.csv \\\n"
        << "    --column AMT_CREDIT \\\n"
        << "    --server-output-dir encrypted_payloads/fhew_amt_credit \\\n"
        << "    --client-key-dir keys/fhew_amt_credit \\\n"
        << "    [--row-limit 1000] [--bit-width 24] [--security TOY|STD128]\n";
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

        if (arg == "--input") {
            options.inputCsv = needValue(arg);
        }
        else if (arg == "--column") {
            options.column = needValue(arg);
        }
        else if (arg == "--server-output-dir") {
            options.serverOutputDir = needValue(arg);
        }
        else if (arg == "--client-key-dir") {
            options.clientKeyDir = needValue(arg);
        }
        else if (arg == "--row-limit") {
            options.rowLimit = static_cast<size_t>(std::stoull(needValue(arg)));
        }
        else if (arg == "--bit-width") {
            options.bitWidth = static_cast<uint32_t>(std::stoul(needValue(arg)));
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

    if (options.inputCsv.empty() || options.serverOutputDir.empty() || options.clientKeyDir.empty()) {
        usage("input, server-output-dir, and client-key-dir are required");
    }
    if (options.bitWidth == 0 || options.bitWidth > 32) {
        usage("bit-width must be in 1..32");
    }
    if (options.rowLimit == 0) {
        usage("row-limit must be positive for the FHEW comparison benchmark");
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

bool isMissing(const std::string& raw) {
    auto value = trim(raw);
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return std::tolower(c); });
    return value.empty() || value == "nan" || value == "null" || value == "none";
}

std::vector<AmountRow> readRows(const Options& options) {
    std::ifstream input(options.inputCsv);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open CSV: " + options.inputCsv.string());
    }
    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("CSV is empty: " + options.inputCsv.string());
    }
    const auto header = splitCsvLine(line);
    auto columnIt = std::find(header.begin(), header.end(), options.column);
    if (columnIt == header.end()) {
        throw std::runtime_error("column not found: " + options.column);
    }
    const size_t columnIndex = static_cast<size_t>(std::distance(header.begin(), columnIt));
    const uint64_t maxRepresentable = options.bitWidth == 64 ? UINT64_MAX : ((uint64_t{1} << options.bitWidth) - 1);

    std::vector<AmountRow> rows;
    uint32_t rowIndex = 0;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != header.size()) {
            throw std::runtime_error("CSV row has wrong field count in " + options.inputCsv.string());
        }
        AmountRow row;
        row.rowIndex = rowIndex++;
        const auto raw = fields[columnIndex];
        if (!isMissing(raw)) {
            const double parsed = std::stod(raw);
            if (!std::isfinite(parsed) || parsed < 0.0) {
                throw std::runtime_error("FHEW amount benchmark expects non-negative finite values");
            }
            const auto rounded = static_cast<uint64_t>(std::llround(parsed));
            if (rounded > maxRepresentable) {
                throw std::runtime_error("value exceeds bit-width representation; increase --bit-width");
            }
            row.value = rounded;
            row.valid = true;
        }
        rows.push_back(row);
        if (rows.size() >= options.rowLimit) {
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

std::string amountBitPath(uint32_t rowIndex, uint32_t bit) {
    return "amount_bits/r" + std::to_string(rowIndex) + "_b" + std::to_string(bit) + ".bin";
}

std::string validPath(uint32_t rowIndex) {
    return "valid_bits/r" + std::to_string(rowIndex) + "_valid.bin";
}

void serializeCiphertext(const std::filesystem::path& root, const std::string& relative, const LWECiphertext& ciphertext) {
    const auto path = root / relative;
    std::filesystem::create_directories(path.parent_path());
    if (!Serial::SerializeToFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot serialize FHEW ciphertext: " + path.string());
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto started = std::chrono::steady_clock::now();
        const auto rows = readRows(options);
        if (rows.empty()) {
            throw std::runtime_error("no rows selected");
        }

        auto cc = BinFHEContext();
        cc.GenerateBinFHEContext(parseSecurity(options.security));
        const auto sk = cc.KeyGen();
        cc.BTKeyGen(sk);

        const auto fhewDir = options.serverOutputDir / "amt" / "fhew";
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

        const auto zero = cc.Encrypt(sk, 0);
        const auto one = cc.Encrypt(sk, 1);
        serializeCiphertext(fhewDir, "constants/zero.bin", zero);
        serializeCiphertext(fhewDir, "constants/one.bin", one);

        std::ofstream amountManifest(fhewDir / "fhew_amt_amount_manifest.csv");
        std::ofstream validManifest(fhewDir / "fhew_amt_valid_manifest.csv");
        if (!amountManifest.is_open() || !validManifest.is_open()) {
            throw std::runtime_error("cannot write FHEW AMT manifests");
        }
        amountManifest << "row_index,bit,ciphertext\n";
        validManifest << "row_index,ciphertext\n";

        for (const auto& row : rows) {
            for (uint32_t bit = 0; bit < options.bitWidth; ++bit) {
                const auto bitValue = static_cast<int>((row.value >> bit) & 1U);
                const auto ciphertext = cc.Encrypt(sk, bitValue);
                const auto relative = amountBitPath(row.rowIndex, bit);
                serializeCiphertext(fhewDir, relative, ciphertext);
                amountManifest << row.rowIndex << ',' << bit << ',' << relative << '\n';
            }
            const auto validCiphertext = cc.Encrypt(sk, row.valid ? 1 : 0);
            const auto relative = validPath(row.rowIndex);
            serializeCiphertext(fhewDir, relative, validCiphertext);
            validManifest << row.rowIndex << ',' << relative << '\n';
        }

        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started);
        std::ofstream metadata(fhewDir / "fhew_amt_metadata.json");
        metadata << "{\n";
        metadata << "  \"scheme\": \"BinFHE/FHEW\",\n";
        metadata << "  \"security\": \"" << options.security << "\",\n";
        metadata << "  \"column\": \"" << options.column << "\",\n";
        metadata << "  \"bit_width\": " << options.bitWidth << ",\n";
        metadata << "  \"rows\": " << rows.size() << ",\n";
        metadata << "  \"valid_mask_included\": true,\n";
        metadata << "  \"bin_masks_included\": false,\n";
        metadata << "  \"elapsed_ms\": " << elapsed.count() << ",\n";
        metadata << "  \"note\": \"Source encrypts amount bits and valid bits only. Bin membership is computed by the HE server from plaintext ranges.\"\n";
        metadata << "}\n";

        std::cout << "encrypt_home_credit_fhew_amt complete\n";
        std::cout << "server FHEW AMT bundle: " << fhewDir << "\n";
        std::cout << "rows: " << rows.size() << "\n";
        std::cout << "bit_width: " << options.bitWidth << "\n";
        std::cout << "TIMING total_seconds " << (elapsed.count() / 1000.0) << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "encrypt_home_credit_fhew_amt failed: " << ex.what() << '\n';
        return 1;
    }
}
