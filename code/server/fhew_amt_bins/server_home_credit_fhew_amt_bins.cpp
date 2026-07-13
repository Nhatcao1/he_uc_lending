#include "binfhecontext-ser.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cmath>
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
    std::filesystem::path amountManifestPath;
    std::filesystem::path validManifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputDir;
    uint64_t minValue = 0;
    uint64_t maxValue = 0;
    uint32_t binCount = 5;
};

using BitMap = std::map<uint32_t, LWECiphertext>;
using RowBits = std::map<uint32_t, BitMap>;

struct BinRange {
    uint32_t binIndex = 0;
    uint64_t lowerInclusive = 0;
    uint64_t upperExclusive = 0;
    std::string label;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  server_home_credit_fhew_amt_bins \\\n"
        << "    --context amt/fhew/cryptoContext.bin \\\n"
        << "    --refresh-key amt/fhew/refreshKey.bin \\\n"
        << "    --switch-key amt/fhew/ksKey.bin \\\n"
        << "    --amount-manifest amt/fhew/fhew_amt_amount_manifest.csv \\\n"
        << "    --valid-manifest amt/fhew/fhew_amt_valid_manifest.csv \\\n"
        << "    --input-dir amt/fhew \\\n"
        << "    --output-dir output/fhew_amt_credit_bins \\\n"
        << "    --min 0 --max 2000000 --bin-count 5\n";
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
        else if (arg == "--amount-manifest") {
            options.amountManifestPath = needValue(arg);
        }
        else if (arg == "--valid-manifest") {
            options.validManifestPath = needValue(arg);
        }
        else if (arg == "--input-dir") {
            options.inputDir = needValue(arg);
        }
        else if (arg == "--output-dir") {
            options.outputDir = needValue(arg);
        }
        else if (arg == "--min") {
            options.minValue = static_cast<uint64_t>(std::stoull(needValue(arg)));
        }
        else if (arg == "--max") {
            options.maxValue = static_cast<uint64_t>(std::stoull(needValue(arg)));
        }
        else if (arg == "--bin-count") {
            options.binCount = static_cast<uint32_t>(std::stoul(needValue(arg)));
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }
    if (options.contextPath.empty() || options.refreshKeyPath.empty() || options.switchKeyPath.empty() ||
        options.amountManifestPath.empty() || options.validManifestPath.empty() || options.inputDir.empty() ||
        options.outputDir.empty()) {
        usage("context, refresh-key, switch-key, manifests, input-dir, and output-dir are required");
    }
    if (options.maxValue < options.minValue) {
        usage("max must be >= min");
    }
    if (options.binCount == 0) {
        usage("bin-count must be positive");
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

LWECiphertext deserializeCiphertext(const std::filesystem::path& path) {
    LWECiphertext ciphertext;
    if (!Serial::DeserializeFromFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize FHEW ciphertext: " + path.string());
    }
    return ciphertext;
}

void loadAmountBits(const Options& options, RowBits& rows) {
    for (const auto& row : readCsv(options.amountManifestPath)) {
        const auto rowIndex = static_cast<uint32_t>(std::stoul(row.at("row_index")));
        const auto bit = static_cast<uint32_t>(std::stoul(row.at("bit")));
        rows[rowIndex][bit] = deserializeCiphertext(options.inputDir / row.at("ciphertext"));
    }
}

std::map<uint32_t, LWECiphertext> loadValidBits(const Options& options) {
    std::map<uint32_t, LWECiphertext> valid;
    for (const auto& row : readCsv(options.validManifestPath)) {
        const auto rowIndex = static_cast<uint32_t>(std::stoul(row.at("row_index")));
        valid[rowIndex] = deserializeCiphertext(options.inputDir / row.at("ciphertext"));
    }
    return valid;
}

uint32_t validateRows(const RowBits& rows, const std::map<uint32_t, LWECiphertext>& validBits) {
    uint32_t bitWidth = 0;
    for (const auto& [rowIndex, bits] : rows) {
        if (!validBits.count(rowIndex)) {
            throw std::runtime_error("missing valid bit for row " + std::to_string(rowIndex));
        }
        if (bits.empty()) {
            throw std::runtime_error("row has no amount bits: " + std::to_string(rowIndex));
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

std::vector<BinRange> makeBins(const Options& options) {
    const uint64_t span = options.maxValue - options.minValue + 1;
    const uint64_t width = static_cast<uint64_t>(std::ceil(static_cast<double>(span) / options.binCount));
    std::vector<BinRange> bins;
    for (uint32_t i = 0; i < options.binCount; ++i) {
        BinRange bin;
        bin.binIndex = i;
        bin.lowerInclusive = options.minValue + static_cast<uint64_t>(i) * width;
        bin.upperExclusive = (i + 1 == options.binCount) ? (options.maxValue + 1) : (bin.lowerInclusive + width);
        bin.label = std::to_string(bin.lowerInclusive) + "_" + std::to_string(bin.upperExclusive);
        bins.push_back(bin);
    }
    return bins;
}

LWECiphertext evalNot(BinFHEContext& cc, const LWECiphertext& value, const LWECiphertext& one, uint64_t& gateCount) {
    ++gateCount;
    return cc.EvalBinGate(XOR, value, one);
}

LWECiphertext evalPlainEqualBit(
    BinFHEContext& cc,
    const LWECiphertext& bit,
    bool plainBit,
    const LWECiphertext& one,
    uint64_t& gateCount) {
    if (plainBit) {
        return bit;
    }
    return evalNot(cc, bit, one, gateCount);
}

LWECiphertext evalGreaterEqualPlain(
    BinFHEContext& cc,
    const BitMap& bits,
    uint64_t threshold,
    const LWECiphertext& zero,
    const LWECiphertext& one,
    uint64_t& gateCount) {
    const auto bitWidth = static_cast<uint32_t>(bits.size());
    if (bitWidth < 64 && threshold >= (uint64_t{1} << bitWidth)) {
        return zero;
    }
    auto greater = zero;
    auto equalPrefix = one;
    for (int bit = static_cast<int>(bitWidth) - 1; bit >= 0; --bit) {
        const bool thresholdBit = ((threshold >> static_cast<uint32_t>(bit)) & 1U) != 0;
        if (!thresholdBit) {
            auto greaterHere = cc.EvalBinGate(AND, equalPrefix, bits.at(static_cast<uint32_t>(bit)));
            greater = cc.EvalBinGate(OR, greater, greaterHere);
            gateCount += 2;
        }
        auto equalBit = evalPlainEqualBit(cc, bits.at(static_cast<uint32_t>(bit)), thresholdBit, one, gateCount);
        equalPrefix = cc.EvalBinGate(AND, equalPrefix, equalBit);
        ++gateCount;
    }
    auto gte = cc.EvalBinGate(OR, greater, equalPrefix);
    ++gateCount;
    return gte;
}

LWECiphertext evalInRange(
    BinFHEContext& cc,
    const BitMap& bits,
    uint64_t lowerInclusive,
    uint64_t upperExclusive,
    const LWECiphertext& valid,
    const LWECiphertext& zero,
    const LWECiphertext& one,
    uint64_t& gateCount) {
    auto lowerOk = evalGreaterEqualPlain(cc, bits, lowerInclusive, zero, one, gateCount);
    auto upperOrAbove = evalGreaterEqualPlain(cc, bits, upperExclusive, zero, one, gateCount);
    auto upperOk = evalNot(cc, upperOrAbove, one, gateCount);
    auto inRange = cc.EvalBinGate(AND, lowerOk, upperOk);
    auto validInRange = cc.EvalBinGate(AND, inRange, valid);
    gateCount += 2;
    return validInRange;
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
        loadAmountBits(options, rows);
        const auto validBits = loadValidBits(options);
        if (rows.empty()) {
            throw std::runtime_error("no amount rows loaded");
        }
        const auto bitWidth = validateRows(rows, validBits);
        const auto countBits = countBitWidth(rows.size());
        const auto bins = makeBins(options);
        const auto zero = deserializeCiphertext(options.inputDir / "constants" / "zero.bin");
        const auto one = deserializeCiphertext(options.inputDir / "constants" / "one.bin");

        const auto countsDir = options.outputDir / "counts";
        std::filesystem::create_directories(countsDir);
        std::ofstream manifest(options.outputDir / "fhew_amt_bin_count_manifest.csv");
        if (!manifest.is_open()) {
            throw std::runtime_error("cannot write FHEW AMT bin count manifest");
        }
        manifest << "result_type,bin_index,label,lower_inclusive,upper_exclusive,bit,ciphertext,row_count,amount_bit_width,count_bit_width,gate_count\n";

        uint64_t totalGateCount = 0;
        uint64_t validGateCount = 0;
        auto validCounter = encryptedZeroCounter(zero, countBits);
        for (const auto& [rowIndex, valid] : validBits) {
            (void)rowIndex;
            incrementEncryptedCounter(cc, validCounter, valid, validGateCount);
        }
        totalGateCount += validGateCount;
        for (uint32_t bit = 0; bit < countBits; ++bit) {
            const auto filename = "valid_count_b" + std::to_string(bit) + ".bin";
            if (!Serial::SerializeToFile((countsDir / filename).string(), validCounter.at(bit), SerType::BINARY)) {
                throw std::runtime_error("cannot serialize valid count bit");
            }
            manifest << "valid_count,-1,valid_count,0,0," << bit << ",counts/" << filename << ',' << rows.size()
                     << ',' << bitWidth << ',' << countBits << ',' << validGateCount << '\n';
        }

        for (const auto& bin : bins) {
            uint64_t binGateCount = 0;
            auto counter = encryptedZeroCounter(zero, countBits);
            for (const auto& [rowIndex, bits] : rows) {
                auto membership = evalInRange(
                    cc,
                    bits,
                    bin.lowerInclusive,
                    bin.upperExclusive,
                    validBits.at(rowIndex),
                    zero,
                    one,
                    binGateCount);
                incrementEncryptedCounter(cc, counter, membership, binGateCount);
            }
            totalGateCount += binGateCount;
            for (uint32_t bit = 0; bit < countBits; ++bit) {
                const auto filename = "bin_" + std::to_string(bin.binIndex) + "_count_b" + std::to_string(bit) + ".bin";
                if (!Serial::SerializeToFile((countsDir / filename).string(), counter.at(bit), SerType::BINARY)) {
                    throw std::runtime_error("cannot serialize bin count bit");
                }
                manifest << "bin_count," << bin.binIndex << ',' << bin.label << ',' << bin.lowerInclusive << ','
                         << bin.upperExclusive << ',' << bit << ",counts/" << filename << ',' << rows.size() << ','
                         << bitWidth << ',' << countBits << ',' << binGateCount << '\n';
            }
        }

        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started);
        std::ofstream metadata(options.outputDir / "fhew_amt_bin_run_metadata.json");
        metadata << "{\n";
        metadata << "  \"scheme\": \"BinFHE/FHEW\",\n";
        metadata << "  \"rows\": " << rows.size() << ",\n";
        metadata << "  \"amount_bit_width\": " << bitWidth << ",\n";
        metadata << "  \"count_bit_width\": " << countBits << ",\n";
        metadata << "  \"min\": " << options.minValue << ",\n";
        metadata << "  \"max\": " << options.maxValue << ",\n";
        metadata << "  \"bin_count\": " << options.binCount << ",\n";
        metadata << "  \"gate_count\": " << totalGateCount << ",\n";
        metadata << "  \"elapsed_ms\": " << elapsed.count() << ",\n";
        metadata << "  \"note\": \"Server computes encrypted bin membership from encrypted amount bits and plaintext ranges, then accumulates encrypted count bits. This is intentionally small-scale.\"\n";
        metadata << "}\n";

        std::cout << "server_home_credit_fhew_amt_bins complete\n";
        std::cout << "output: " << options.outputDir << "\n";
        std::cout << "rows: " << rows.size() << "\n";
        std::cout << "bins: " << bins.size() << "\n";
        std::cout << "gates: " << totalGateCount << "\n";
        std::cout << "TIMING total_seconds " << (elapsed.count() / 1000.0) << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "server_home_credit_fhew_amt_bins failed: " << ex.what() << '\n';
        return 1;
    }
}
