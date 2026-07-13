#include "binfhecontext-ser.h"

#include <algorithm>
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
    std::filesystem::path contextPath;
    std::filesystem::path refreshKeyPath;
    std::filesystem::path switchKeyPath;
    std::filesystem::path codeManifestPath;
    std::filesystem::path labelMetadataPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputDir;
};

using BitMap = std::map<uint32_t, LWECiphertext>;
using RowBits = std::map<uint32_t, BitMap>;

struct LabelCode {
    uint32_t code = 0;
    std::string label;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  server_home_credit_fhew_category_count \\\n"
        << "    --context category/fhew/cryptoContext.bin \\\n"
        << "    --refresh-key category/fhew/refreshKey.bin \\\n"
        << "    --switch-key category/fhew/ksKey.bin \\\n"
        << "    --code-manifest category/fhew/fhew_category_code_manifest.csv \\\n"
        << "    --label-metadata category/fhew/fhew_category_label_metadata.csv \\\n"
        << "    --input-dir category/fhew \\\n"
        << "    --output-dir output/fhew_category_count\n";
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
        else if (arg == "--refresh-key") {
            options.refreshKeyPath = needValue(arg);
        }
        else if (arg == "--switch-key") {
            options.switchKeyPath = needValue(arg);
        }
        else if (arg == "--code-manifest") {
            options.codeManifestPath = needValue(arg);
        }
        else if (arg == "--label-metadata") {
            options.labelMetadataPath = needValue(arg);
        }
        else if (arg == "--input-dir") {
            options.inputDir = needValue(arg);
        }
        else if (arg == "--output-dir") {
            options.outputDir = needValue(arg);
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }
    if (options.contextPath.empty() || options.refreshKeyPath.empty() || options.switchKeyPath.empty() ||
        options.codeManifestPath.empty() || options.labelMetadataPath.empty() || options.inputDir.empty() ||
        options.outputDir.empty()) {
        usage("context, refresh-key, switch-key, manifests, input-dir, and output-dir are required");
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

LWECiphertext deserializeCiphertext(const std::filesystem::path& path) {
    LWECiphertext ciphertext;
    if (!Serial::DeserializeFromFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize FHEW ciphertext: " + path.string());
    }
    return ciphertext;
}

void loadCategoryBits(const Options& options, RowBits& rows) {
    for (const auto& row : readCsv(options.codeManifestPath)) {
        const auto rowIndex = static_cast<uint32_t>(std::stoul(row.at("row_index")));
        const auto bit = static_cast<uint32_t>(std::stoul(row.at("bit")));
        rows[rowIndex][bit] = deserializeCiphertext(options.inputDir / row.at("ciphertext"));
    }
}

std::vector<LabelCode> loadLabels(const Options& options) {
    std::vector<LabelCode> labels;
    for (const auto& row : readCsv(options.labelMetadataPath)) {
        labels.push_back(LabelCode{static_cast<uint32_t>(std::stoul(row.at("code"))), row.at("label")});
    }
    return labels;
}

uint32_t validateRows(const RowBits& rows) {
    uint32_t bitWidth = 0;
    for (const auto& [rowIndex, bits] : rows) {
        if (bits.empty()) {
            throw std::runtime_error("row has no category bits: " + std::to_string(rowIndex));
        }
        if (bitWidth == 0) {
            bitWidth = static_cast<uint32_t>(bits.size());
        }
        if (bits.size() != bitWidth) {
            throw std::runtime_error("row bit-count mismatch at row " + std::to_string(rowIndex));
        }
        for (uint32_t bit = 0; bit < bitWidth; ++bit) {
            if (!bits.count(bit)) {
                throw std::runtime_error("row missing bit " + std::to_string(bit));
            }
        }
    }
    return bitWidth;
}

LWECiphertext evalNot(BinFHEContext& cc, const LWECiphertext& value, const LWECiphertext& one, uint64_t& gateCount) {
    ++gateCount;
    return cc.EvalBinGate(XOR, value, one);
}

LWECiphertext evalEqualPlain(
    BinFHEContext& cc,
    const BitMap& bits,
    uint32_t code,
    const LWECiphertext& one,
    uint64_t& gateCount) {
    auto equal = ((code & 1U) != 0) ? bits.at(0) : evalNot(cc, bits.at(0), one, gateCount);
    for (uint32_t bit = 1; bit < bits.size(); ++bit) {
        auto sameBit = ((code >> bit) & 1U) != 0 ? bits.at(bit) : evalNot(cc, bits.at(bit), one, gateCount);
        equal = cc.EvalBinGate(AND, equal, sameBit);
        ++gateCount;
    }
    return equal;
}

std::vector<LWECiphertext> encryptedZeroCounter(const LWECiphertext& zero, uint32_t countBits) {
    return std::vector<LWECiphertext>(countBits, zero);
}

void incrementEncryptedCounter(
    BinFHEContext& cc,
    std::vector<LWECiphertext>& counter,
    const LWECiphertext& incrementBit,
    uint64_t& gateCount) {
    auto carry = incrementBit;
    for (auto& bit : counter) {
        auto sum = cc.EvalBinGate(XOR, bit, carry);
        auto nextCarry = cc.EvalBinGate(AND, bit, carry);
        gateCount += 2;
        bit = sum;
        carry = nextCarry;
    }
}

uint32_t countBitWidth(uint64_t rows) {
    uint32_t bits = 1;
    uint64_t capacity = 2;
    while (capacity <= rows) {
        capacity <<= 1U;
        ++bits;
    }
    return bits;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto started = std::chrono::steady_clock::now();

        BinFHEContext cc;
        if (!Serial::DeserializeFromFile(options.contextPath.string(), cc, SerType::BINARY)) {
            throw std::runtime_error("cannot deserialize FHEW crypto context");
        }
        RingGSWACCKey refreshKey;
        if (!Serial::DeserializeFromFile(options.refreshKeyPath.string(), refreshKey, SerType::BINARY)) {
            throw std::runtime_error("cannot deserialize FHEW refresh key");
        }
        LWESwitchingKey switchKey;
        if (!Serial::DeserializeFromFile(options.switchKeyPath.string(), switchKey, SerType::BINARY)) {
            throw std::runtime_error("cannot deserialize FHEW switching key");
        }
        RingGSWBTKey bootstrappingKey;
        bootstrappingKey.BSkey = refreshKey;
        bootstrappingKey.KSkey = switchKey;
        cc.BTKeyLoad(bootstrappingKey);

        RowBits rows;
        loadCategoryBits(options, rows);
        if (rows.empty()) {
            throw std::runtime_error("no category rows loaded");
        }
        const auto labels = loadLabels(options);
        const auto codeBitWidth = validateRows(rows);
        const auto countBits = countBitWidth(rows.size());
        const auto zero = deserializeCiphertext(options.inputDir / "constants" / "zero.bin");
        const auto one = deserializeCiphertext(options.inputDir / "constants" / "one.bin");

        const auto countsDir = options.outputDir / "counts";
        std::filesystem::create_directories(countsDir);
        std::ofstream manifest(options.outputDir / "fhew_category_count_manifest.csv");
        if (!manifest.is_open()) {
            throw std::runtime_error("cannot write FHEW category count manifest");
        }
        manifest << "code,label,bit,ciphertext,row_count,code_bit_width,count_bit_width,gate_count\n";

        uint64_t totalGateCount = 0;
        for (const auto& label : labels) {
            uint64_t labelGateCount = 0;
            auto counter = encryptedZeroCounter(zero, countBits);
            for (const auto& [rowIndex, bits] : rows) {
                (void)rowIndex;
                auto membership = evalEqualPlain(cc, bits, label.code, one, labelGateCount);
                incrementEncryptedCounter(cc, counter, membership, labelGateCount);
            }
            totalGateCount += labelGateCount;
            for (uint32_t bit = 0; bit < countBits; ++bit) {
                const auto filename = "code_" + std::to_string(label.code) + "_count_b" + std::to_string(bit) + ".bin";
                if (!Serial::SerializeToFile((countsDir / filename).string(), counter.at(bit), SerType::BINARY)) {
                    throw std::runtime_error("cannot serialize category count bit");
                }
                manifest << label.code << ',' << csvEscape(label.label) << ',' << bit << ",counts/" << filename << ','
                         << rows.size() << ',' << codeBitWidth << ',' << countBits << ',' << labelGateCount << '\n';
            }
        }

        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started);
        std::ofstream metadata(options.outputDir / "fhew_category_count_run_metadata.json");
        metadata << "{\n";
        metadata << "  \"scheme\": \"BinFHE/FHEW\",\n";
        metadata << "  \"rows\": " << rows.size() << ",\n";
        metadata << "  \"labels\": " << labels.size() << ",\n";
        metadata << "  \"code_bit_width\": " << codeBitWidth << ",\n";
        metadata << "  \"count_bit_width\": " << countBits << ",\n";
        metadata << "  \"gate_count\": " << totalGateCount << ",\n";
        metadata << "  \"elapsed_ms\": " << elapsed.count() << ",\n";
        metadata << "  \"note\": \"Server computes encrypted equality against plaintext category codes and accumulates encrypted count bits.\"\n";
        metadata << "}\n";

        std::cout << "server_home_credit_fhew_category_count complete\n";
        std::cout << "output: " << options.outputDir << "\n";
        std::cout << "rows: " << rows.size() << "\n";
        std::cout << "labels: " << labels.size() << "\n";
        std::cout << "gates: " << totalGateCount << "\n";
        std::cout << "TIMING total_seconds " << (elapsed.count() / 1000.0) << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "server_home_credit_fhew_category_count failed: " << ex.what() << '\n';
        return 1;
    }
}
