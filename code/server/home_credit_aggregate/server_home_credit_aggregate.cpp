#include "openfhe.h"

#include "ciphertext-ser.h"
#include "cryptocontext-ser.h"
#include "key/key-ser.h"
#include "scheme/ckksrns/ckksrns-ser.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

using namespace lbcrypto;

namespace {

using Clock = std::chrono::steady_clock;

double secondsSince(const Clock::time_point& start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

void printTiming(const std::string& name, double seconds) {
    std::cout << "TIMING " << name << " " << seconds << "\n";
}

struct Options {
    std::filesystem::path contextPath;
    std::filesystem::path evalSumKeysPath;
    std::filesystem::path evalMultKeysPath;
    std::filesystem::path manifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputDir;
    std::string analysisFilter;
};

struct AggregateRow {
    std::string analysis;
    std::string group;
    std::string label;
    std::string operation;
    std::string valueName;
    std::filesystem::path maskCiphertext;
    std::filesystem::path valueCiphertext;
    uint32_t rows = 0;
    uint32_t slots = 0;
    uint32_t chunk = 0;
};

struct AggregateResult {
    std::string analysis;
    std::string group;
    std::string label;
    std::string operation;
    std::string valueName;
    std::filesystem::path outputCiphertext;
    uint64_t totalRows = 0;
    uint64_t totalSlots = 0;
    uint64_t chunkCount = 0;
};

using AggregateKey = std::tuple<std::string, std::string, std::string, std::string, std::string>;

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  server_home_credit_aggregate \\\n"
        << "    --context <crypto_context.bin> \\\n"
        << "    --eval-sum-keys <eval_sum_keys.bin> \\\n"
        << "    --eval-mult-keys <eval_mult_keys.bin> \\\n"
        << "    --manifest <aggregate_manifest.csv> \\\n"
        << "    --input-dir <encrypted_vectors_dir> \\\n"
        << "    --output-dir <server_returns_dir> \\\n"
        << "    [--analysis-filter missing_data|target_balance|application_category_counts|"
           "application_default_rates|application_numeric_histograms|previous_application_category_counts|"
           "previous_application_target_rates|selected_correlation_stats]\n";
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
        else if (arg == "--eval-sum-keys") {
            options.evalSumKeysPath = needValue(arg);
        }
        else if (arg == "--eval-mult-keys") {
            options.evalMultKeysPath = needValue(arg);
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
        else if (arg == "--analysis-filter") {
            options.analysisFilter = needValue(arg);
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }

    if (options.contextPath.empty() || options.evalSumKeysPath.empty() || options.evalMultKeysPath.empty() ||
        options.manifestPath.empty() || options.inputDir.empty() || options.outputDir.empty()) {
        usage("all arguments are required");
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

uint32_t parseU32(const std::string& value, const std::string& field, size_t lineNumber) {
    try {
        return static_cast<uint32_t>(std::stoul(value));
    }
    catch (const std::exception&) {
        throw std::runtime_error("invalid " + field + " at manifest line " + std::to_string(lineNumber));
    }
}

std::string safeFileStem(std::string value) {
    for (char& ch : value) {
        const bool ok = std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == '-' || ch == '.';
        if (!ok) {
            ch = '_';
        }
    }
    return value.empty() ? "aggregate" : value;
}

std::vector<AggregateRow> readManifest(const std::filesystem::path& path, const std::string& analysisFilter) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open manifest: " + path.string());
    }
    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("manifest is empty: " + path.string());
    }
    const auto header = splitCsvLine(line);
    const std::vector<std::string> expected = {
        "analysis", "group", "label", "operation", "value_name", "mask_ciphertext",
        "value_ciphertext", "rows", "slots", "chunk",
    };
    if (header != expected) {
        throw std::runtime_error("manifest header must be: analysis,group,label,operation,value_name,mask_ciphertext,"
                                 "value_ciphertext,rows,slots,chunk");
    }

    std::vector<AggregateRow> rows;
    size_t lineNumber = 1;
    while (std::getline(input, line)) {
        ++lineNumber;
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != 10) {
            throw std::runtime_error("manifest line " + std::to_string(lineNumber) + " must have 10 fields");
        }
        AggregateRow row;
        row.analysis = fields[0];
        row.group = fields[1];
        row.label = fields[2];
        row.operation = fields[3];
        row.valueName = fields[4];
        row.maskCiphertext = fields[5];
        row.valueCiphertext = fields[6];
        row.rows = parseU32(fields[7], "rows", lineNumber);
        row.slots = parseU32(fields[8], "slots", lineNumber);
        row.chunk = parseU32(fields[9], "chunk", lineNumber);
        if (row.maskCiphertext.empty()) {
            throw std::runtime_error("mask_ciphertext is required at line " + std::to_string(lineNumber));
        }
        if ((row.operation == "default_count" || row.operation == "masked_sum" || row.operation == "sum") &&
            row.valueCiphertext.empty()) {
            throw std::runtime_error("value_ciphertext is required for " + row.operation);
        }
        if (analysisFilter.empty() || row.analysis == analysisFilter) {
            rows.push_back(row);
        }
    }
    if (rows.empty()) {
        throw std::runtime_error("manifest contains no aggregate rows for requested analysis filter");
    }
    return rows;
}

void deserializeContext(const std::filesystem::path& path, CryptoContext<DCRTPoly>& cc) {
    if (!Serial::DeserializeFromFile(path.string(), cc, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize crypto context: " + path.string());
    }
}

void deserializeEvalSumKeys(const CryptoContext<DCRTPoly>& cc, const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input.is_open() || !cc->DeserializeEvalSumKey(input, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize eval sum keys: " + path.string());
    }
}

void deserializeEvalMultKeys(const CryptoContext<DCRTPoly>& cc, const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input.is_open() || !cc->DeserializeEvalMultKey(input, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize eval mult keys: " + path.string());
    }
}

Ciphertext<DCRTPoly> deserializeCiphertext(const std::filesystem::path& path) {
    Ciphertext<DCRTPoly> ciphertext;
    if (!Serial::DeserializeFromFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize ciphertext: " + path.string());
    }
    return ciphertext;
}

void serializeCiphertext(const std::filesystem::path& path, const Ciphertext<DCRTPoly>& ciphertext) {
    if (!Serial::SerializeToFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot serialize ciphertext: " + path.string());
    }
}

std::map<AggregateKey, std::vector<AggregateRow>> groupRows(const std::vector<AggregateRow>& rows) {
    std::map<AggregateKey, std::vector<AggregateRow>> grouped;
    for (const auto& row : rows) {
        grouped[{row.analysis, row.group, row.label, row.operation, row.valueName}].push_back(row);
    }
    return grouped;
}

Ciphertext<DCRTPoly> computeChunk(const Options& options, const CryptoContext<DCRTPoly>& cc, const AggregateRow& row) {
    auto mask = deserializeCiphertext(options.inputDir / row.maskCiphertext);
    if (row.operation == "count") {
        return cc->EvalSum(mask, row.slots);
    }
    if (row.operation == "sum") {
        auto value = deserializeCiphertext(options.inputDir / row.valueCiphertext);
        return cc->EvalSum(value, row.slots);
    }
    if (row.operation == "default_count" || row.operation == "masked_sum") {
        auto value = deserializeCiphertext(options.inputDir / row.valueCiphertext);
        auto product = cc->EvalMultAndRelinearize(mask, value);
        return cc->EvalSum(product, row.slots);
    }
    throw std::runtime_error("unknown aggregate operation: " + row.operation);
}

std::vector<AggregateResult> runAggregates(
    const Options& options,
    const CryptoContext<DCRTPoly>& cc,
    const std::map<AggregateKey, std::vector<AggregateRow>>& grouped) {
    std::filesystem::create_directories(options.outputDir / "aggregates");
    std::vector<AggregateResult> results;

    for (const auto& [key, rows] : grouped) {
        Ciphertext<DCRTPoly> total;
        AggregateResult result;
        std::tie(result.analysis, result.group, result.label, result.operation, result.valueName) = key;

        for (const auto& row : rows) {
            auto chunkValue = computeChunk(options, cc, row);
            if (!total) {
                total = chunkValue;
            }
            else {
                total = cc->EvalAdd(total, chunkValue);
            }
            result.totalRows += row.rows;
            result.totalSlots += row.slots;
            result.chunkCount += 1;
        }

        const auto stem = safeFileStem(result.analysis + "." + result.group + "." + result.label + "." +
                                       result.operation + "." + result.valueName) +
                          ".bin";
        result.outputCiphertext = std::filesystem::path("aggregates") / stem;
        serializeCiphertext(options.outputDir / result.outputCiphertext, total);
        results.push_back(result);
    }
    return results;
}

void writeOutputManifest(const std::filesystem::path& outputDir, const std::vector<AggregateResult>& results) {
    std::ofstream output(outputDir / "aggregate_summary_manifest.csv");
    if (!output.is_open()) {
        throw std::runtime_error("cannot write aggregate summary manifest");
    }
    output << "analysis,group,label,operation,value_name,encrypted_result_ciphertext,total_rows,total_slots,chunk_count\n";
    for (const auto& result : results) {
        output << csvEscape(result.analysis) << ',' << csvEscape(result.group) << ',' << csvEscape(result.label)
               << ',' << csvEscape(result.operation) << ',' << csvEscape(result.valueName) << ','
               << csvEscape(result.outputCiphertext.string()) << ',' << result.totalRows << ',' << result.totalSlots
               << ',' << result.chunkCount << '\n';
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto totalStarted = Clock::now();
        const auto options = parseArgs(argc, argv);

        const auto readStarted = Clock::now();
        const auto rows = readManifest(options.manifestPath, options.analysisFilter);
        const auto grouped = groupRows(rows);
        printTiming("read_manifest_seconds", secondsSince(readStarted));

        const auto deserializeStarted = Clock::now();
        CryptoContext<DCRTPoly> cc;
        deserializeContext(options.contextPath, cc);
        deserializeEvalSumKeys(cc, options.evalSumKeysPath);
        deserializeEvalMultKeys(cc, options.evalMultKeysPath);
        printTiming("deserialize_context_keys_seconds", secondsSince(deserializeStarted));

        const auto computeStarted = Clock::now();
        const auto results = runAggregates(options, cc, grouped);
        printTiming("aggregate_compute_seconds", secondsSince(computeStarted));

        const auto manifestStarted = Clock::now();
        writeOutputManifest(options.outputDir, results);
        printTiming("write_result_manifest_seconds", secondsSince(manifestStarted));
        printTiming("total_seconds", secondsSince(totalStarted));

        std::cout << "server_home_credit_aggregate complete\n";
        std::cout << "manifest_rows: " << rows.size() << "\n";
        std::cout << "aggregates: " << results.size() << "\n";
        std::cout << "output: " << (options.outputDir / "aggregate_summary_manifest.csv") << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "server_home_credit_aggregate failed: " << ex.what() << '\n';
        return 1;
    }
}
