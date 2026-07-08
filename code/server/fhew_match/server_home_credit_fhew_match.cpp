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
#include <unordered_map>
#include <vector>

using namespace lbcrypto;

namespace {

struct Options {
    std::filesystem::path contextPath;
    std::filesystem::path refreshKeyPath;
    std::filesystem::path switchKeyPath;
    std::filesystem::path manifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputDir;
};

using BitMap = std::map<uint32_t, LWECiphertext>;
using RowBits = std::map<uint32_t, BitMap>;

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  server_home_credit_fhew_match \\\n"
        << "    --context join/fhew/cryptoContext.bin \\\n"
        << "    --refresh-key join/fhew/refreshKey.bin \\\n"
        << "    --switch-key join/fhew/ksKey.bin \\\n"
        << "    --manifest join/fhew/fhew_match_manifest.csv \\\n"
        << "    --input-dir join/fhew \\\n"
        << "    --output-dir output/join_fhew_prev_contract_status\n";
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
        else if (arg == "--manifest") {
            options.manifestPath = needValue(arg);
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
        options.manifestPath.empty() || options.inputDir.empty() || options.outputDir.empty()) {
        usage("context, refresh-key, switch-key, manifest, input-dir, and output-dir are required");
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

void loadBitRows(const Options& options, RowBits& leftRows, RowBits& rightRows) {
    for (const auto& row : readCsv(options.manifestPath)) {
        const auto side = row.at("side");
        const auto rowIndex = static_cast<uint32_t>(std::stoul(row.at("row_index")));
        const auto bit = static_cast<uint32_t>(std::stoul(row.at("bit")));
        const auto path = options.inputDir / row.at("ciphertext");
        LWECiphertext ciphertext;
        if (!Serial::DeserializeFromFile(path.string(), ciphertext, SerType::BINARY)) {
            throw std::runtime_error("cannot deserialize FHEW ciphertext: " + path.string());
        }
        if (side == "left") {
            leftRows[rowIndex][bit] = ciphertext;
        }
        else if (side == "right") {
            rightRows[rowIndex][bit] = ciphertext;
        }
        else {
            throw std::runtime_error("unknown FHEW match side: " + side);
        }
    }
}

void validateRows(const RowBits& rows, const std::string& side, uint32_t& idBits) {
    for (const auto& [rowIndex, bits] : rows) {
        if (bits.empty()) {
            throw std::runtime_error(side + " row has no bits: " + std::to_string(rowIndex));
        }
        if (idBits == 0) {
            idBits = static_cast<uint32_t>(bits.size());
        }
        if (bits.size() != idBits) {
            throw std::runtime_error(side + " row bit-count mismatch at row " + std::to_string(rowIndex));
        }
        for (uint32_t bit = 0; bit < idBits; ++bit) {
            if (!bits.count(bit)) {
                throw std::runtime_error(side + " row missing bit " + std::to_string(bit));
            }
        }
    }
}

LWECiphertext evalEqual(BinFHEContext& cc, const BitMap& left, const BitMap& right, uint64_t& gateCount) {
    auto equality = cc.EvalBinGate(XNOR, left.at(0), right.at(0));
    ++gateCount;
    for (uint32_t bit = 1; bit < left.size(); ++bit) {
        auto sameBit = cc.EvalBinGate(XNOR, left.at(bit), right.at(bit));
        equality = cc.EvalBinGate(AND, equality, sameBit);
        gateCount += 2;
    }
    return equality;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        auto started = std::chrono::steady_clock::now();

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

        RowBits leftRows;
        RowBits rightRows;
        loadBitRows(options, leftRows, rightRows);
        if (leftRows.empty() || rightRows.empty()) {
            throw std::runtime_error("FHEW match requires at least one left row and one right row");
        }
        uint32_t idBits = 0;
        validateRows(leftRows, "left", idBits);
        validateRows(rightRows, "right", idBits);

        const auto matchesDir = options.outputDir / "matches";
        std::filesystem::create_directories(matchesDir);
        std::ofstream manifest(options.outputDir / "fhew_match_summary_manifest.csv");
        if (!manifest.is_open()) {
            throw std::runtime_error("cannot write FHEW output manifest");
        }
        manifest << "right_index,ciphertext,compared_left_rows,id_bits,pair_count,gate_count\n";

        uint64_t totalGateCount = 0;
        uint64_t totalPairCount = 0;
        for (const auto& [rightIndex, rightBits] : rightRows) {
            LWECiphertext matched;
            bool first = true;
            uint64_t rowGateCount = 0;
            for (const auto& [leftIndex, leftBits] : leftRows) {
                (void)leftIndex;
                auto equal = evalEqual(cc, leftBits, rightBits, rowGateCount);
                if (first) {
                    matched = equal;
                    first = false;
                }
                else {
                    matched = cc.EvalBinGate(OR, matched, equal);
                    ++rowGateCount;
                }
                ++totalPairCount;
            }
            const auto filename = "right_" + std::to_string(rightIndex) + "_matched.bin";
            if (!Serial::SerializeToFile((matchesDir / filename).string(), matched, SerType::BINARY)) {
                throw std::runtime_error("cannot serialize FHEW match result");
            }
            totalGateCount += rowGateCount;
            manifest << rightIndex << ",matches/" << filename << ',' << leftRows.size() << ',' << idBits << ','
                     << leftRows.size() << ',' << rowGateCount << '\n';
        }

        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started);
        std::ofstream metadata(options.outputDir / "fhew_match_run_metadata.json");
        metadata << "{\n";
        metadata << "  \"scheme\": \"BinFHE/FHEW\",\n";
        metadata << "  \"left_rows\": " << leftRows.size() << ",\n";
        metadata << "  \"right_rows\": " << rightRows.size() << ",\n";
        metadata << "  \"id_bits\": " << idBits << ",\n";
        metadata << "  \"pair_count\": " << totalPairCount << ",\n";
        metadata << "  \"gate_count\": " << totalGateCount << ",\n";
        metadata << "  \"elapsed_ms\": " << elapsed.count() << ",\n";
        metadata << "  \"note\": \"Encrypted equality benchmark only; this is not a scalable Home Credit join implementation.\"\n";
        metadata << "}\n";

        std::cout << "server_home_credit_fhew_match complete\n";
        std::cout << "output: " << options.outputDir << "\n";
        std::cout << "pairs: " << totalPairCount << "\n";
        std::cout << "gates: " << totalGateCount << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "server_home_credit_fhew_match failed: " << ex.what() << '\n';
        return 1;
    }
}
