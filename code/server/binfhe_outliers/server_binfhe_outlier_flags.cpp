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
    std::filesystem::path contextPath;
    std::filesystem::path refreshKeyPath;
    std::filesystem::path switchKeyPath;
    std::filesystem::path manifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputDir;
};

struct InputRow {
    std::string rowId;
    std::string column;
    std::string packId;
    std::filesystem::path ciphertextPath;
    uint64_t plaintextModulus = 0;
    uint64_t threshold = 0;
    uint64_t bitsPerFeature = 0;
    std::string comparison;
    std::vector<uint64_t> thresholdBuckets;
    bool packed = false;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr << "Usage:\n"
              << "  server_binfhe_outlier_flags \\\n"
              << "    --context <binfhe_context.bin> \\\n"
              << "    --refresh-key <binfhe_refresh_key.bin> \\\n"
              << "    --switch-key <binfhe_switch_key.bin> \\\n"
              << "    --manifest <outlier_ciphertexts.csv> \\\n"
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

std::map<std::string, size_t> headerIndex(const std::vector<std::string>& header) {
    std::map<std::string, size_t> index;
    for (size_t i = 0; i < header.size(); ++i) {
        index[header[i]] = i;
    }
    return index;
}

std::vector<uint64_t> splitUIntList(const std::string& value) {
    std::vector<uint64_t> out;
    std::string current;
    for (char ch : value) {
        if (ch == ';') {
            if (!current.empty()) {
                out.push_back(std::stoull(current));
                current.clear();
            }
        }
        else {
            current.push_back(ch);
        }
    }
    if (!current.empty()) {
        out.push_back(std::stoull(current));
    }
    return out;
}

std::vector<InputRow> readManifest(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open manifest: " + path.string());
    }
    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("manifest is empty: " + path.string());
    }
    const auto index = headerIndex(splitCsvLine(line));
    const bool packedMode = index.count("pack_id") && index.count("bits_per_feature") &&
                            index.count("threshold_buckets");
    const std::vector<std::string> requiredColumns =
        packedMode ? std::vector<std::string>{"row_id", "pack_id", "ciphertext", "plaintext_modulus",
                                              "bits_per_feature", "threshold_buckets", "comparison"}
                   : std::vector<std::string>{"row_id", "column", "ciphertext", "plaintext_modulus", "threshold",
                                              "comparison"};
    for (const auto& required : requiredColumns) {
        if (!index.count(required)) {
            throw std::runtime_error("manifest missing column: " + required);
        }
    }

    std::vector<InputRow> rows;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        InputRow row;
        row.rowId = fields.at(index.at("row_id"));
        row.ciphertextPath = fields.at(index.at("ciphertext"));
        row.plaintextModulus = std::stoull(fields.at(index.at("plaintext_modulus")));
        row.comparison = fields.at(index.at("comparison"));
        row.packed = packedMode;
        if (packedMode) {
            row.packId = fields.at(index.at("pack_id"));
            row.column = row.packId;
            row.bitsPerFeature = std::stoull(fields.at(index.at("bits_per_feature")));
            row.thresholdBuckets = splitUIntList(fields.at(index.at("threshold_buckets")));
            if (row.comparison != "any_gt_bucket") {
                throw std::runtime_error("only comparison=any_gt_bucket is supported for packed mode: " + row.packId);
            }
        }
        else {
            row.column = fields.at(index.at("column"));
            row.threshold = std::stoull(fields.at(index.at("threshold")));
            if (row.comparison != "gt") {
                throw std::runtime_error("only comparison=gt is supported for scalar mode: " + row.column);
            }
        }
        rows.push_back(row);
    }
    return rows;
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

std::vector<NativeInteger> buildGreaterThanLut(const BinFHEContext& cc, uint64_t plaintextModulus, uint64_t threshold) {
    if ((plaintextModulus == 0) || ((plaintextModulus & (plaintextModulus - 1)) != 0)) {
        throw std::runtime_error("plaintext_modulus must be a power of two");
    }
    if (threshold >= plaintextModulus) {
        throw std::runtime_error("threshold must be less than plaintext_modulus");
    }

    NativeInteger qNative{cc.GetParams()->GetLWEParams()->Getq()};
    const uint64_t q = qNative.ConvertToInt();
    const NativeInteger scale = qNative / NativeInteger(plaintextModulus);
    std::vector<NativeInteger> lut(q, scale);
    for (uint64_t i = 0; i < q; ++i) {
        const uint64_t message = (i * plaintextModulus) / q;
        const uint64_t flag = message > threshold ? 1 : 0;
        lut[i] *= flag;
    }
    return lut;
}

std::vector<NativeInteger> buildPackedAnyGreaterThanBucketLut(const BinFHEContext& cc,
                                                              uint64_t plaintextModulus,
                                                              uint64_t bitsPerFeature,
                                                              const std::vector<uint64_t>& thresholdBuckets) {
    if ((plaintextModulus == 0) || ((plaintextModulus & (plaintextModulus - 1)) != 0)) {
        throw std::runtime_error("plaintext_modulus must be a power of two");
    }
    if (bitsPerFeature == 0 || bitsPerFeature >= 64) {
        throw std::runtime_error("bits_per_feature must be between 1 and 63");
    }
    if (thresholdBuckets.empty()) {
        throw std::runtime_error("threshold_buckets cannot be empty");
    }

    const uint64_t bucketLimit = 1ULL << bitsPerFeature;
    for (const auto threshold : thresholdBuckets) {
        if (threshold >= bucketLimit) {
            throw std::runtime_error("threshold bucket must fit inside bits_per_feature");
        }
    }

    NativeInteger qNative{cc.GetParams()->GetLWEParams()->Getq()};
    const uint64_t q = qNative.ConvertToInt();
    const NativeInteger scale = qNative / NativeInteger(plaintextModulus);
    const uint64_t mask = bucketLimit - 1;
    std::vector<NativeInteger> lut(q, scale);
    for (uint64_t i = 0; i < q; ++i) {
        uint64_t message = (i * plaintextModulus) / q;
        uint64_t flag = 0;
        for (const auto threshold : thresholdBuckets) {
            const uint64_t bucket = message & mask;
            if (bucket > threshold) {
                flag = 1;
            }
            message >>= bitsPerFeature;
        }
        lut[i] *= flag;
    }
    return lut;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto rows = readManifest(options.manifestPath);
        std::filesystem::create_directories(options.outputDir / "flags");

        BinFHEContext cc;
        RingGSWACCKey refreshKey;
        LWESwitchingKey switchKey;
        deserializeFile(options.contextPath, cc);
        deserializeFile(options.refreshKeyPath, refreshKey);
        deserializeFile(options.switchKeyPath, switchKey);
        cc.BTKeyLoad({refreshKey, switchKey});

        std::map<std::string, std::vector<NativeInteger>> lutCache;
        std::ofstream manifest(options.outputDir / "outlier_flag_manifest.csv");
        manifest << "row_id,column,encrypted_flag_ciphertext,plaintext_modulus,threshold,comparison\n";

        uint64_t flagCount = 0;
        for (const auto& row : rows) {
            LWECiphertext ciphertext;
            deserializeFile(options.inputDir / row.ciphertextPath, ciphertext);

            const std::string cacheKey = row.packed ? row.comparison + ":" + std::to_string(row.plaintextModulus) +
                                                          ":" + std::to_string(row.bitsPerFeature) + ":" +
                                                          row.packId
                                                    : row.comparison + ":" + std::to_string(row.plaintextModulus) +
                                                          ":" + std::to_string(row.threshold);
            if (!lutCache.count(cacheKey)) {
                lutCache[cacheKey] =
                    row.packed ? buildPackedAnyGreaterThanBucketLut(cc,
                                                                     row.plaintextModulus,
                                                                     row.bitsPerFeature,
                                                                     row.thresholdBuckets)
                               : buildGreaterThanLut(cc, row.plaintextModulus, row.threshold);
            }
            auto flag = cc.EvalFunc(ciphertext, lutCache.at(cacheKey));

            const std::string fileName =
                "row_" + safeFileName(row.rowId) + "_" + safeFileName(row.column) + ".flag.bin";
            serializeFile(options.outputDir / "flags" / fileName, flag);
            manifest << row.rowId << ',' << row.column << ',' << fileName << ',' << row.plaintextModulus << ','
                     << (row.packed ? 0 : row.threshold) << ',' << row.comparison << '\n';
            ++flagCount;
        }

        std::cout << "server_binfhe_outlier_flags complete\n";
        std::cout << "flags: " << flagCount << "\n";
        std::cout << "manifest: " << (options.outputDir / "outlier_flag_manifest.csv") << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "server_binfhe_outlier_flags failed: " << ex.what() << "\n";
        return 1;
    }
}
