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
    std::filesystem::path contextPath;
    std::filesystem::path secretKeyPath;
    std::filesystem::path manifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputCsv;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  decrypt_home_credit_fhew_category_count \\\n"
        << "    --context <fhew_crypto_context.bin> \\\n"
        << "    --secret-key <fhew_secret_key.bin> \\\n"
        << "    --manifest <fhew_category_count_manifest.csv> \\\n"
        << "    --input-dir <result_dir> \\\n"
        << "    --output-csv <decrypted_category_counts.csv>\n";
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
        else if (arg == "--output-csv") {
            options.outputCsv = needValue(arg);
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }
    if (options.contextPath.empty() || options.secretKeyPath.empty() || options.manifestPath.empty() ||
        options.inputDir.empty() || options.outputCsv.empty()) {
        usage("context, secret-key, manifest, input-dir, and output-csv are required");
    }
    return options;
}

std::string trim(std::string value) {
    auto notSpace = [](unsigned char ch) { return !std::isspace(ch); };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), notSpace));
    value.erase(std::find_if(value.rbegin(), value.rend(), notSpace).base(), value.end());
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

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        BinFHEContext cc;
        if (!Serial::DeserializeFromFile(options.contextPath.string(), cc, SerType::BINARY)) {
            throw std::runtime_error("cannot deserialize FHEW crypto context");
        }
        LWEPrivateKey sk;
        if (!Serial::DeserializeFromFile(options.secretKeyPath.string(), sk, SerType::BINARY)) {
            throw std::runtime_error("cannot deserialize FHEW secret key");
        }

        struct CountAccumulator {
            uint32_t code = 0;
            std::string label;
            uint64_t rowCount = 0;
            uint32_t codeBitWidth = 0;
            uint32_t countBitWidth = 0;
            uint64_t gateCount = 0;
            uint64_t count = 0;
        };
        std::map<uint32_t, CountAccumulator> counts;

        for (const auto& row : readCsv(options.manifestPath)) {
            LWECiphertext ciphertext;
            const auto path = options.inputDir / row.at("ciphertext");
            if (!Serial::DeserializeFromFile(path.string(), ciphertext, SerType::BINARY)) {
                throw std::runtime_error("cannot deserialize FHEW category count bit: " + path.string());
            }
            LWEPlaintext plaintext;
            cc.Decrypt(sk, ciphertext, &plaintext);
            const auto code = static_cast<uint32_t>(std::stoul(row.at("code")));
            const auto bit = static_cast<uint32_t>(std::stoul(row.at("bit")));
            auto& item = counts[code];
            item.code = code;
            item.label = row.at("label");
            item.rowCount = static_cast<uint64_t>(std::stoull(row.at("row_count")));
            item.codeBitWidth = static_cast<uint32_t>(std::stoul(row.at("code_bit_width")));
            item.countBitWidth = static_cast<uint32_t>(std::stoul(row.at("count_bit_width")));
            item.gateCount = static_cast<uint64_t>(std::stoull(row.at("gate_count")));
            if (plaintext != 0) {
                item.count |= (uint64_t{1} << bit);
            }
        }

        if (!options.outputCsv.parent_path().empty()) {
            std::filesystem::create_directories(options.outputCsv.parent_path());
        }
        std::ofstream output(options.outputCsv);
        if (!output.is_open()) {
            throw std::runtime_error("cannot write output CSV: " + options.outputCsv.string());
        }
        output << "code,label,count,row_count,percent,code_bit_width,count_bit_width,gate_count\n";
        for (const auto& [code, item] : counts) {
            (void)code;
            const double percent = item.rowCount ? static_cast<double>(item.count) / static_cast<double>(item.rowCount) : 0.0;
            output << item.code << ',' << csvEscape(item.label) << ',' << item.count << ',' << item.rowCount << ','
                   << percent << ',' << item.codeBitWidth << ',' << item.countBitWidth << ',' << item.gateCount << '\n';
        }

        std::cout << "decrypt_home_credit_fhew_category_count complete\n";
        std::cout << "rows: " << counts.size() << "\n";
        std::cout << "output: " << options.outputCsv << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "decrypt_home_credit_fhew_category_count failed: " << ex.what() << '\n';
        return 1;
    }
}
