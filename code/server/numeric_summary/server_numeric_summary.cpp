#include "openfhe.h"

#include "ciphertext-ser.h"
#include "cryptocontext-ser.h"
#include "key/key-ser.h"
#include "scheme/ckksrns/ckksrns-ser.h"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

using namespace lbcrypto;

namespace {

struct Options {
    std::filesystem::path contextPath;
    std::filesystem::path evalSumKeysPath;
    std::filesystem::path manifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputDir;
};

struct ChunkSpec {
    std::string column;
    std::filesystem::path ciphertextPath;
    uint32_t rows = 0;
    uint32_t slots = 0;
};

struct ColumnResult {
    std::string column;
    std::filesystem::path outputCiphertext;
    uint64_t totalRows = 0;
    uint64_t totalSlots = 0;
    uint64_t chunkCount = 0;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  server_numeric_summary \\\n"
        << "    --context <crypto_context.bin> \\\n"
        << "    --eval-sum-keys <eval_sum_keys.bin> \\\n"
        << "    --manifest <column_manifest.csv> \\\n"
        << "    --input-dir <encrypted_columns_dir> \\\n"
        << "    --output-dir <server_returns_dir>\n";
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

    if (options.contextPath.empty() || options.evalSumKeysPath.empty() || options.manifestPath.empty() ||
        options.inputDir.empty() || options.outputDir.empty()) {
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

uint32_t parsePositiveU32(const std::string& text, const std::string& fieldName, size_t lineNumber) {
    try {
        const auto value = std::stoull(text);
        if (value == 0 || value > std::numeric_limits<uint32_t>::max()) {
            throw std::out_of_range(fieldName);
        }
        return static_cast<uint32_t>(value);
    }
    catch (const std::exception&) {
        throw std::runtime_error("invalid " + fieldName + " at manifest line " + std::to_string(lineNumber) + ": " +
                                 text);
    }
}

std::vector<ChunkSpec> readManifest(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open manifest: " + path.string());
    }

    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("manifest is empty: " + path.string());
    }

    const auto header = splitCsvLine(line);
    const std::vector<std::string> expected = {"column", "ciphertext", "rows", "slots"};
    if (header != expected) {
        throw std::runtime_error("manifest header must be: column,ciphertext,rows,slots");
    }

    std::vector<ChunkSpec> chunks;
    size_t lineNumber = 1;
    while (std::getline(input, line)) {
        ++lineNumber;
        if (trim(line).empty()) {
            continue;
        }

        const auto fields = splitCsvLine(line);
        if (fields.size() != 4) {
            throw std::runtime_error("manifest line " + std::to_string(lineNumber) + " must have 4 fields");
        }

        ChunkSpec spec;
        spec.column = fields[0];
        spec.ciphertextPath = fields[1];
        spec.rows = parsePositiveU32(fields[2], "rows", lineNumber);
        spec.slots = parsePositiveU32(fields[3], "slots", lineNumber);

        if (spec.column.empty() || spec.ciphertextPath.empty()) {
            throw std::runtime_error("empty column or ciphertext at manifest line " + std::to_string(lineNumber));
        }
        if (spec.slots < spec.rows) {
            throw std::runtime_error("slots must be >= rows at manifest line " + std::to_string(lineNumber));
        }

        chunks.push_back(spec);
    }

    if (chunks.empty()) {
        throw std::runtime_error("manifest contains no chunks: " + path.string());
    }
    return chunks;
}

void deserializeContext(const std::filesystem::path& path, CryptoContext<DCRTPoly>& cc) {
    if (!Serial::DeserializeFromFile(path.string(), cc, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize crypto context: " + path.string());
    }
}

void deserializeEvalSumKeys(const CryptoContext<DCRTPoly>& cc, const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::in | std::ios::binary);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open eval sum keys: " + path.string());
    }
    if (!cc->DeserializeEvalSumKey(input, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize eval sum keys: " + path.string());
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

std::string safeFileStem(std::string value) {
    for (char& ch : value) {
        const bool ok = std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == '-';
        if (!ok) {
            ch = '_';
        }
    }
    return value;
}

std::map<std::string, std::vector<ChunkSpec>> groupByColumn(const std::vector<ChunkSpec>& chunks) {
    std::map<std::string, std::vector<ChunkSpec>> grouped;
    for (const auto& chunk : chunks) {
        grouped[chunk.column].push_back(chunk);
    }
    return grouped;
}

std::vector<ColumnResult> runSummary(const Options& options, const CryptoContext<DCRTPoly>& cc,
                                     const std::map<std::string, std::vector<ChunkSpec>>& grouped) {
    std::filesystem::create_directories(options.outputDir);

    std::vector<ColumnResult> results;
    for (const auto& [column, chunks] : grouped) {
        Ciphertext<DCRTPoly> columnSum;
        ColumnResult result;
        result.column = column;

        for (const auto& chunk : chunks) {
            const auto ciphertextPath = options.inputDir / chunk.ciphertextPath;
            auto ciphertext = deserializeCiphertext(ciphertextPath);
            auto chunkSum = cc->EvalSum(ciphertext, chunk.slots);

            if (!columnSum) {
                columnSum = chunkSum;
            }
            else {
                columnSum = cc->EvalAdd(columnSum, chunkSum);
            }

            result.totalRows += chunk.rows;
            result.totalSlots += chunk.slots;
            result.chunkCount += 1;
        }

        result.outputCiphertext = safeFileStem(column) + ".sum.bin";
        serializeCiphertext(options.outputDir / result.outputCiphertext, columnSum);
        results.push_back(result);
    }

    return results;
}

void writeOutputManifest(const std::filesystem::path& outputDir, const std::vector<ColumnResult>& results) {
    const auto manifestPath = outputDir / "summary_manifest.csv";
    std::ofstream output(manifestPath);
    if (!output.is_open()) {
        throw std::runtime_error("cannot write output manifest: " + manifestPath.string());
    }

    output << "column,encrypted_sum_ciphertext,total_rows,total_slots,chunk_count\n";
    for (const auto& result : results) {
        output << result.column << ',' << result.outputCiphertext.string() << ',' << result.totalRows << ','
               << result.totalSlots << ',' << result.chunkCount << '\n';
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto chunks = readManifest(options.manifestPath);
        const auto grouped = groupByColumn(chunks);

        CryptoContext<DCRTPoly> cc;
        deserializeContext(options.contextPath, cc);
        deserializeEvalSumKeys(cc, options.evalSumKeysPath);

        const auto results = runSummary(options, cc, grouped);
        writeOutputManifest(options.outputDir, results);

        std::cout << "server_numeric_summary complete\n";
        std::cout << "columns: " << results.size() << "\n";
        std::cout << "output: " << (options.outputDir / "summary_manifest.csv") << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "server_numeric_summary failed: " << ex.what() << '\n';
        return 1;
    }
}
