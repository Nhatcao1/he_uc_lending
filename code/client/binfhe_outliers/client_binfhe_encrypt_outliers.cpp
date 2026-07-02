#include "binfhecontext-ser.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
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
    std::filesystem::path contextPath = "keys/binfhe_outliers/binfhe_context.bin";
    std::filesystem::path secretKeyPath = "keys/binfhe_outliers/binfhe_secret_key.bin";
    std::filesystem::path valuesPath = "encrypted_payloads/binfhe_outliers/outlier_values.csv";
    std::filesystem::path rulesPath = "encrypted_payloads/binfhe_outliers/outlier_rules.csv";
    std::filesystem::path outputDir = "encrypted_payloads/binfhe_outliers/columns";
    std::filesystem::path manifestPath = "encrypted_payloads/binfhe_outliers/outlier_ciphertexts.csv";
};

struct Rule {
    std::string column;
    uint64_t plaintextModulus = 0;
    uint64_t threshold = 0;
    std::string comparison;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr << "Usage:\n"
              << "  client_binfhe_encrypt_outliers \\\n"
              << "    --context keys/binfhe_outliers/binfhe_context.bin \\\n"
              << "    --secret-key keys/binfhe_outliers/binfhe_secret_key.bin \\\n"
              << "    --values encrypted_payloads/binfhe_outliers/outlier_values.csv \\\n"
              << "    --rules encrypted_payloads/binfhe_outliers/outlier_rules.csv \\\n"
              << "    --output-dir encrypted_payloads/binfhe_outliers/columns \\\n"
              << "    --manifest encrypted_payloads/binfhe_outliers/outlier_ciphertexts.csv\n";
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
        else if (arg == "--values") {
            options.valuesPath = needValue(arg);
        }
        else if (arg == "--rules") {
            options.rulesPath = needValue(arg);
        }
        else if (arg == "--output-dir") {
            options.outputDir = needValue(arg);
        }
        else if (arg == "--manifest") {
            options.manifestPath = needValue(arg);
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

std::vector<Rule> readRules(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open rules: " + path.string());
    }
    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("rules CSV is empty: " + path.string());
    }
    const auto index = headerIndex(splitCsvLine(line));
    for (const auto& required : {"column", "plaintext_modulus", "threshold", "comparison"}) {
        if (!index.count(required)) {
            throw std::runtime_error("rules CSV missing column: " + std::string(required));
        }
    }

    std::vector<Rule> rules;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        Rule rule;
        rule.column = fields.at(index.at("column"));
        rule.plaintextModulus = std::stoull(fields.at(index.at("plaintext_modulus")));
        rule.threshold = std::stoull(fields.at(index.at("threshold")));
        rule.comparison = fields.at(index.at("comparison"));
        if (rule.comparison != "gt") {
            throw std::runtime_error("only comparison=gt is supported for now: " + rule.column);
        }
        rules.push_back(rule);
    }
    return rules;
}

std::string safeFileName(std::string value) {
    for (char& ch : value) {
        const bool ok = std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == '-';
        if (!ok) {
            ch = '_';
        }
    }
    return value;
}

template <typename T>
void deserializeFile(const std::filesystem::path& path, T& value) {
    if (!Serial::DeserializeFromFile(path.string(), value, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize: " + path.string());
    }
}

template <typename T>
void serializeFile(const std::filesystem::path& path, const T& value) {
    if (!Serial::SerializeToFile(path.string(), value, SerType::BINARY)) {
        throw std::runtime_error("cannot serialize: " + path.string());
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
        const auto rules = readRules(options.rulesPath);
        std::filesystem::create_directories(options.outputDir);
        createParentDirectory(options.manifestPath);

        BinFHEContext cc;
        LWEPrivateKey sk;
        deserializeFile(options.contextPath, cc);
        deserializeFile(options.secretKeyPath, sk);

        std::ifstream values(options.valuesPath);
        if (!values.is_open()) {
            throw std::runtime_error("cannot open values CSV: " + options.valuesPath.string());
        }

        std::string line;
        if (!std::getline(values, line)) {
            throw std::runtime_error("values CSV is empty: " + options.valuesPath.string());
        }
        const auto index = headerIndex(splitCsvLine(line));
        if (!index.count("row_id")) {
            throw std::runtime_error("values CSV missing row_id");
        }
        for (const auto& rule : rules) {
            if (!index.count(rule.column)) {
                throw std::runtime_error("values CSV missing rule column: " + rule.column);
            }
        }

        std::ofstream manifest(options.manifestPath);
        manifest << "row_id,column,ciphertext,plaintext_modulus,threshold,comparison\n";

        uint64_t encryptedCount = 0;
        while (std::getline(values, line)) {
            if (trim(line).empty()) {
                continue;
            }
            const auto fields = splitCsvLine(line);
            const auto rowId = fields.at(index.at("row_id"));
            for (const auto& rule : rules) {
                const auto encoded = std::stoull(fields.at(index.at(rule.column)));
                if (encoded >= rule.plaintextModulus) {
                    throw std::runtime_error("encoded value exceeds plaintext modulus for row " + rowId + ", column " +
                                             rule.column);
                }
                auto ciphertext = cc.Encrypt(sk, encoded, LARGE_DIM, rule.plaintextModulus);
                const std::string fileName = "row_" + safeFileName(rowId) + "_" + safeFileName(rule.column) + ".bin";
                serializeFile(options.outputDir / fileName, ciphertext);
                manifest << rowId << ',' << rule.column << ',' << fileName << ',' << rule.plaintextModulus << ','
                         << rule.threshold << ',' << rule.comparison << '\n';
                ++encryptedCount;
            }
        }

        std::cout << "client_binfhe_encrypt_outliers complete\n";
        std::cout << "ciphertexts: " << encryptedCount << "\n";
        std::cout << "manifest: " << options.manifestPath << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "client_binfhe_encrypt_outliers failed: " << ex.what() << "\n";
        return 1;
    }
}
