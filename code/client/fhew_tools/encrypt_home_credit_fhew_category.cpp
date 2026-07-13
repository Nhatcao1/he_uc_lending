#include "binfhecontext-ser.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

using namespace lbcrypto;

namespace {

constexpr const char* MISSING_BUCKET = "__MISSING__";

struct Options {
    std::filesystem::path inputCsv;
    std::filesystem::path serverOutputDir;
    std::filesystem::path clientKeyDir;
    std::string column = "NAME_TYPE_SUITE";
    uint32_t bitWidth = 8;
    size_t rowLimit = 1000;
    std::string security = "TOY";
};

struct CategoryRow {
    uint32_t rowIndex = 0;
    uint32_t code = 0;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  encrypt_home_credit_fhew_category \\\n"
        << "    --input data/home_credit/application_train.csv \\\n"
        << "    --column NAME_TYPE_SUITE \\\n"
        << "    --server-output-dir encrypted_payloads/fhew_suite_type \\\n"
        << "    --client-key-dir keys/fhew_suite_type \\\n"
        << "    [--row-limit 1000] [--bit-width 8] [--security TOY|STD128]\n";
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
    if (options.rowLimit == 0) {
        usage("row-limit must be positive for the FHEW category benchmark");
    }
    if (options.bitWidth == 0 || options.bitWidth > 32) {
        usage("bit-width must be in 1..32");
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

std::string normalizeCategory(const std::string& raw) {
    auto value = trim(raw);
    auto lowered = value;
    std::transform(lowered.begin(), lowered.end(), lowered.begin(), [](unsigned char c) { return std::tolower(c); });
    if (value.empty() || lowered == "nan" || lowered == "null" || lowered == "none") {
        return MISSING_BUCKET;
    }
    return value;
}

std::string csvEscape(const std::string& value) {
    if (value.find_first_of(",\"\n\r") == std::string::npos) {
        return value;
    }
    std::string escaped = "\"";
    for (char ch : value) {
        if (ch == '"') {
            escaped += "\"\"";
        }
        else {
            escaped.push_back(ch);
        }
    }
    escaped.push_back('"');
    return escaped;
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

std::vector<std::string> readLabels(const Options& options) {
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
    std::vector<std::string> labels;
    size_t rows = 0;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != header.size()) {
            throw std::runtime_error("CSV row has wrong field count in " + options.inputCsv.string());
        }
        labels.push_back(normalizeCategory(fields[columnIndex]));
        ++rows;
        if (rows >= options.rowLimit) {
            break;
        }
    }
    return labels;
}

BINFHE_PARAMSET parseSecurity(const std::string& value) {
    if (value == "STD128") {
        return STD128;
    }
    return TOY;
}

std::string codeBitPath(uint32_t rowIndex, uint32_t bit) {
    return "category_bits/r" + std::to_string(rowIndex) + "_b" + std::to_string(bit) + ".bin";
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
        const auto labelsByRow = readLabels(options);
        if (labelsByRow.empty()) {
            throw std::runtime_error("no rows selected");
        }

        std::set<std::string> uniqueLabels(labelsByRow.begin(), labelsByRow.end());
        std::map<std::string, uint32_t> labelToCode;
        std::vector<std::string> codeToLabel;
        uint32_t nextCode = 0;
        for (const auto& label : uniqueLabels) {
            labelToCode[label] = nextCode++;
            codeToLabel.push_back(label);
        }
        if (options.bitWidth < 32 && nextCode > (uint32_t{1} << options.bitWidth)) {
            throw std::runtime_error("bit-width is too small for category codes");
        }

        auto cc = BinFHEContext();
        cc.GenerateBinFHEContext(parseSecurity(options.security));
        const auto sk = cc.KeyGen();
        cc.BTKeyGen(sk);

        const auto fhewDir = options.serverOutputDir / "category" / "fhew";
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

        std::ofstream codeManifest(fhewDir / "fhew_category_code_manifest.csv");
        std::ofstream labelMetadata(fhewDir / "fhew_category_label_metadata.csv");
        if (!codeManifest.is_open() || !labelMetadata.is_open()) {
            throw std::runtime_error("cannot write FHEW category manifests");
        }
        codeManifest << "row_index,bit,ciphertext\n";
        labelMetadata << "code,label\n";
        for (uint32_t code = 0; code < codeToLabel.size(); ++code) {
            labelMetadata << code << ',' << csvEscape(codeToLabel[code]) << '\n';
        }

        for (uint32_t rowIndex = 0; rowIndex < labelsByRow.size(); ++rowIndex) {
            const auto code = labelToCode.at(labelsByRow[rowIndex]);
            for (uint32_t bit = 0; bit < options.bitWidth; ++bit) {
                const auto bitValue = static_cast<int>((code >> bit) & 1U);
                const auto ciphertext = cc.Encrypt(sk, bitValue);
                const auto relative = codeBitPath(rowIndex, bit);
                serializeCiphertext(fhewDir, relative, ciphertext);
                codeManifest << rowIndex << ',' << bit << ',' << relative << '\n';
            }
        }

        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started);
        std::ofstream metadata(fhewDir / "fhew_category_metadata.json");
        metadata << "{\n";
        metadata << "  \"scheme\": \"BinFHE/FHEW\",\n";
        metadata << "  \"security\": \"" << options.security << "\",\n";
        metadata << "  \"column\": \"" << options.column << "\",\n";
        metadata << "  \"bit_width\": " << options.bitWidth << ",\n";
        metadata << "  \"rows\": " << labelsByRow.size() << ",\n";
        metadata << "  \"labels\": " << codeToLabel.size() << ",\n";
        metadata << "  \"one_hot_masks_included\": false,\n";
        metadata << "  \"elapsed_ms\": " << elapsed.count() << ",\n";
        metadata << "  \"note\": \"Source encrypts category code bits only. Label counts are computed by HE server equality against plaintext label codes.\"\n";
        metadata << "}\n";

        std::cout << "encrypt_home_credit_fhew_category complete\n";
        std::cout << "server FHEW category bundle: " << fhewDir << "\n";
        std::cout << "rows: " << labelsByRow.size() << "\n";
        std::cout << "labels: " << codeToLabel.size() << "\n";
        std::cout << "bit_width: " << options.bitWidth << "\n";
        std::cout << "TIMING total_seconds " << (elapsed.count() / 1000.0) << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "encrypt_home_credit_fhew_category failed: " << ex.what() << '\n';
        return 1;
    }
}
