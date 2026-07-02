#include "binfhecontext-ser.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
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

struct Options {
    std::filesystem::path contextPath = "keys/binfhe_outliers/binfhe_context.bin";
    std::filesystem::path secretKeyPath = "keys/binfhe_outliers/binfhe_secret_key.bin";
    std::filesystem::path manifestPath = "server_returns/binfhe_outliers/outlier_flag_manifest.csv";
    std::filesystem::path inputDir = "server_returns/binfhe_outliers/flags";
    std::filesystem::path outputCsv = "server_returns/binfhe_outliers/decrypted_outlier_flags.csv";
};

struct FlagRow {
    std::string rowId;
    std::string column;
    std::filesystem::path ciphertextPath;
    uint64_t plaintextModulus = 0;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr << "Usage:\n"
              << "  client_binfhe_decrypt_outliers \\\n"
              << "    --context keys/binfhe_outliers/binfhe_context.bin \\\n"
              << "    --secret-key keys/binfhe_outliers/binfhe_secret_key.bin \\\n"
              << "    --manifest server_returns/binfhe_outliers/outlier_flag_manifest.csv \\\n"
              << "    --input-dir server_returns/binfhe_outliers/flags \\\n"
              << "    --output server_returns/binfhe_outliers/decrypted_outlier_flags.csv\n";
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
        if (arg == "--context") {
            options.contextPath = needValue(arg);
        }
        else if (arg == "--secret-key") {
            options.secretKeyPath = needValue(arg);
        }
        else if (arg == "--manifest") {
            options.manifestPath = needValue(arg);
        }
        else if (arg == "--input-dir") {
            options.inputDir = needValue(arg);
        }
        else if (arg == "--output") {
            options.outputCsv = needValue(arg);
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
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
    for (char ch : line) {
        if (ch == '"') {
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

std::map<std::string, size_t> headerIndex(const std::vector<std::string>& header) {
    std::map<std::string, size_t> index;
    for (size_t i = 0; i < header.size(); ++i) {
        index[header[i]] = i;
    }
    return index;
}

std::vector<FlagRow> readManifest(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open manifest: " + path.string());
    }
    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("manifest is empty: " + path.string());
    }
    const auto index = headerIndex(splitCsvLine(line));
    for (const auto& required : {"row_id", "column", "encrypted_flag_ciphertext", "plaintext_modulus"}) {
        if (!index.count(required)) {
            throw std::runtime_error("manifest missing column: " + std::string(required));
        }
    }

    std::vector<FlagRow> rows;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        FlagRow row;
        row.rowId = fields.at(index.at("row_id"));
        row.column = fields.at(index.at("column"));
        row.ciphertextPath = fields.at(index.at("encrypted_flag_ciphertext"));
        row.plaintextModulus = std::stoull(fields.at(index.at("plaintext_modulus")));
        rows.push_back(row);
    }
    return rows;
}

template <typename T>
void deserializeFile(const std::filesystem::path& path, T& value) {
    if (!Serial::DeserializeFromFile(path.string(), value, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize: " + path.string());
    }
}

void createParentDirectory(const std::filesystem::path& path) {
    const auto parent = path.parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto rows = readManifest(options.manifestPath);
        createParentDirectory(options.outputCsv);

        BinFHEContext cc;
        LWEPrivateKey sk;
        deserializeFile(options.contextPath, cc);
        deserializeFile(options.secretKeyPath, sk);

        std::set<std::string> columns;
        std::map<std::string, std::map<std::string, uint64_t>> byRow;
        for (const auto& row : rows) {
            LWECiphertext ciphertext;
            deserializeFile(options.inputDir / row.ciphertextPath, ciphertext);
            LWEPlaintext result = 0;
            cc.Decrypt(sk, ciphertext, &result, row.plaintextModulus);
            const uint64_t flag = result == 0 ? 0 : 1;
            byRow[row.rowId][row.column] = flag;
            columns.insert(row.column);
        }

        std::ofstream output(options.outputCsv);
        output << "row_id,any_outlier";
        for (const auto& column : columns) {
            output << ',' << column;
        }
        output << '\n';

        for (const auto& [rowId, flags] : byRow) {
            uint64_t anyOutlier = 0;
            for (const auto& [_, flag] : flags) {
                anyOutlier = anyOutlier || flag;
            }
            output << rowId << ',' << anyOutlier;
            for (const auto& column : columns) {
                const auto it = flags.find(column);
                output << ',' << (it == flags.end() ? 0 : it->second);
            }
            output << '\n';
        }

        std::cout << "client_binfhe_decrypt_outliers complete\n";
        std::cout << "rows: " << byRow.size() << "\n";
        std::cout << "output: " << options.outputCsv << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "client_binfhe_decrypt_outliers failed: " << ex.what() << "\n";
        return 1;
    }
}
