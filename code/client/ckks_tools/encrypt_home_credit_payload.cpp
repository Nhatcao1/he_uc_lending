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
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using namespace lbcrypto;

namespace {

struct Options {
    std::filesystem::path preparedDir;
    std::filesystem::path serverOutputDir;
    std::filesystem::path clientKeyDir;
    uint32_t slots = 4096;
    uint32_t multiplicativeDepth = 3;
    uint32_t scalingModSize = 50;
    uint32_t firstModSize = 60;
};

struct VectorSpec {
    std::string name;
    std::string kind;
    std::string sourceColumn;
    std::string analysis;
    std::string group;
    std::string label;
    uint64_t rows = 0;
    std::filesystem::path file;
};

struct ChunkInfo {
    uint32_t chunk = 0;
    uint32_t rows = 0;
    uint32_t slots = 0;
    std::filesystem::path vectorCiphertext;
    std::filesystem::path columnCiphertext;
    std::filesystem::path scoreCiphertext;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  encrypt_home_credit_payload \\\n"
        << "    --prepared-dir <prepared_payload_dir> \\\n"
        << "    --server-output-dir <encrypted_payload_dir> \\\n"
        << "    --client-key-dir <keys_dir> \\\n"
        << "    [--slots 4096]\n";
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

        if (arg == "--prepared-dir") {
            options.preparedDir = needValue(arg);
        }
        else if (arg == "--server-output-dir") {
            options.serverOutputDir = needValue(arg);
        }
        else if (arg == "--client-key-dir") {
            options.clientKeyDir = needValue(arg);
        }
        else if (arg == "--slots") {
            options.slots = static_cast<uint32_t>(std::stoul(needValue(arg)));
        }
        else if (arg == "--multiplicative-depth") {
            options.multiplicativeDepth = static_cast<uint32_t>(std::stoul(needValue(arg)));
        }
        else if (arg == "--scaling-mod-size") {
            options.scalingModSize = static_cast<uint32_t>(std::stoul(needValue(arg)));
        }
        else if (arg == "--first-mod-size") {
            options.firstModSize = static_cast<uint32_t>(std::stoul(needValue(arg)));
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }

    if (options.preparedDir.empty() || options.serverOutputDir.empty() || options.clientKeyDir.empty()) {
        usage("prepared-dir, server-output-dir, and client-key-dir are required");
    }
    if (options.slots == 0) {
        usage("slots must be positive");
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

std::string safeFileStem(std::string value) {
    for (char& ch : value) {
        const bool ok = std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == '-' || ch == '.';
        if (!ok) {
            ch = '_';
        }
    }
    if (value.empty()) {
        return "value";
    }
    return value;
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

std::unordered_map<std::string, VectorSpec> readVectorManifest(const std::filesystem::path& preparedDir) {
    std::unordered_map<std::string, VectorSpec> specs;
    for (const auto& row : readCsv(preparedDir / "vector_manifest.csv")) {
        VectorSpec spec;
        spec.name = row.at("name");
        spec.kind = row.at("kind");
        spec.sourceColumn = row.at("source_column");
        spec.analysis = row.at("analysis");
        spec.group = row.at("group");
        spec.label = row.at("label");
        spec.rows = std::stoull(row.at("rows"));
        spec.file = row.at("file");
        specs[spec.name] = spec;
    }
    return specs;
}

CryptoContext<DCRTPoly> makeContext(const Options& options) {
    CCParams<CryptoContextCKKSRNS> parameters;
    parameters.SetMultiplicativeDepth(options.multiplicativeDepth);
    parameters.SetScalingModSize(options.scalingModSize);
    parameters.SetFirstModSize(options.firstModSize);
    parameters.SetBatchSize(options.slots);

    auto cc = GenCryptoContext(parameters);
    cc->Enable(PKE);
    cc->Enable(KEYSWITCH);
    cc->Enable(LEVELEDSHE);
    cc->Enable(ADVANCEDSHE);
    return cc;
}

void serializeContextAndKeys(const Options& options, const CryptoContext<DCRTPoly>& cc,
                             const KeyPair<DCRTPoly>& keys) {
    std::filesystem::create_directories(options.serverOutputDir);
    std::filesystem::create_directories(options.clientKeyDir);

    if (!Serial::SerializeToFile((options.serverOutputDir / "crypto_context.bin").string(), cc, SerType::BINARY)) {
        throw std::runtime_error("cannot serialize crypto context");
    }
    if (!Serial::SerializeToFile((options.serverOutputDir / "public_key.bin").string(), keys.publicKey,
                                 SerType::BINARY)) {
        throw std::runtime_error("cannot serialize public key");
    }
    if (!Serial::SerializeToFile((options.clientKeyDir / "secret_key.bin").string(), keys.secretKey,
                                 SerType::BINARY)) {
        throw std::runtime_error("cannot serialize secret key");
    }

    {
        std::ofstream output(options.serverOutputDir / "eval_sum_keys.bin", std::ios::binary);
        if (!output.is_open() || !cc->SerializeEvalSumKey(output, SerType::BINARY)) {
            throw std::runtime_error("cannot serialize eval sum keys");
        }
    }
    {
        std::ofstream output(options.serverOutputDir / "eval_mult_keys.bin", std::ios::binary);
        if (!output.is_open() || !cc->SerializeEvalMultKey(output, SerType::BINARY)) {
            throw std::runtime_error("cannot serialize eval mult keys");
        }
    }
}

std::vector<double> readChunk(std::ifstream& input, uint32_t maxSlots) {
    std::vector<double> values;
    values.reserve(maxSlots);
    std::string line;
    while (values.size() < maxSlots && std::getline(input, line)) {
        const auto cleaned = trim(line);
        if (cleaned.empty()) {
            continue;
        }
        values.push_back(std::stod(cleaned));
    }
    return values;
}

void serializeCiphertext(const std::filesystem::path& path, const Ciphertext<DCRTPoly>& ciphertext) {
    if (!Serial::SerializeToFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot serialize ciphertext: " + path.string());
    }
}

std::unordered_map<std::string, std::vector<ChunkInfo>> encryptVectors(
    const Options& options,
    const CryptoContext<DCRTPoly>& cc,
    const PublicKey<DCRTPoly>& publicKey,
    const std::unordered_map<std::string, VectorSpec>& specs) {
    std::unordered_map<std::string, std::vector<ChunkInfo>> chunksByVector;
    const auto vectorDir = options.serverOutputDir / "vectors";
    const auto columnsDir = options.serverOutputDir / "columns";
    const auto scoreDir = options.serverOutputDir / "score_features";
    std::filesystem::create_directories(vectorDir);
    std::filesystem::create_directories(columnsDir);
    std::filesystem::create_directories(scoreDir);

    for (const auto& [name, spec] : specs) {
        std::ifstream input(options.preparedDir / spec.file);
        if (!input.is_open()) {
            throw std::runtime_error("cannot open vector file: " + (options.preparedDir / spec.file).string());
        }

        uint64_t totalRows = 0;
        uint32_t chunkIndex = 0;
        while (true) {
            auto values = readChunk(input, options.slots);
            if (values.empty()) {
                break;
            }

            auto plaintext = cc->MakeCKKSPackedPlaintext(values);
            auto ciphertext = cc->Encrypt(publicKey, plaintext);
            const auto stem = safeFileStem(name) + "_" + std::to_string(chunkIndex) + ".bin";

            ChunkInfo info;
            info.chunk = chunkIndex;
            info.rows = static_cast<uint32_t>(values.size());
            info.slots = static_cast<uint32_t>(values.size());
            info.vectorCiphertext = stem;
            serializeCiphertext(vectorDir / info.vectorCiphertext, ciphertext);

            if (spec.kind == "numeric") {
                info.columnCiphertext = stem;
                serializeCiphertext(columnsDir / info.columnCiphertext, ciphertext);
            }
            if (spec.kind == "ml_feature") {
                info.scoreCiphertext = stem;
                serializeCiphertext(scoreDir / info.scoreCiphertext, ciphertext);
            }

            chunksByVector[name].push_back(info);
            totalRows += values.size();
            ++chunkIndex;
        }

        if (totalRows != spec.rows) {
            throw std::runtime_error("vector row count mismatch for " + name + ": manifest=" +
                                     std::to_string(spec.rows) + " actual=" + std::to_string(totalRows));
        }
    }

    return chunksByVector;
}

const std::vector<ChunkInfo>& requireChunks(
    const std::unordered_map<std::string, std::vector<ChunkInfo>>& chunksByVector,
    const std::string& vectorName) {
    const auto found = chunksByVector.find(vectorName);
    if (found == chunksByVector.end()) {
        throw std::runtime_error("unknown vector in manifest: " + vectorName);
    }
    return found->second;
}

void writeColumnManifest(const Options& options,
                         const std::unordered_map<std::string, std::vector<ChunkInfo>>& chunksByVector) {
    const auto rows = readCsv(options.preparedDir / "numeric_vectors.csv");
    std::ofstream output(options.serverOutputDir / "column_manifest.csv");
    if (!output.is_open()) {
        throw std::runtime_error("cannot write column manifest");
    }
    output << "column,ciphertext,rows,slots\n";
    for (const auto& row : rows) {
        const auto& chunks = requireChunks(chunksByVector, row.at("vector"));
        for (const auto& chunk : chunks) {
            if (chunk.columnCiphertext.empty()) {
                throw std::runtime_error("numeric vector missing column ciphertext: " + row.at("vector"));
            }
            output << csvEscape(row.at("column")) << ',' << csvEscape(chunk.columnCiphertext.string()) << ','
                   << chunk.rows << ',' << chunk.slots << '\n';
        }
    }
}

void writeAggregateManifest(const Options& options,
                            const std::unordered_map<std::string, std::vector<ChunkInfo>>& chunksByVector) {
    const auto rows = readCsv(options.preparedDir / "aggregate_operations.csv");
    std::ofstream output(options.serverOutputDir / "aggregate_manifest.csv");
    if (!output.is_open()) {
        throw std::runtime_error("cannot write aggregate manifest");
    }
    output << "analysis,group,label,operation,value_name,mask_ciphertext,value_ciphertext,rows,slots,chunk\n";
    for (const auto& row : rows) {
        const auto& maskChunks = requireChunks(chunksByVector, row.at("mask_vector"));
        const auto valueVector = row.at("value_vector");
        const std::vector<ChunkInfo>* valueChunks = nullptr;
        if (!valueVector.empty()) {
            valueChunks = &requireChunks(chunksByVector, valueVector);
            if (valueChunks->size() != maskChunks.size()) {
                throw std::runtime_error("chunk count mismatch for operation " + row.at("operation"));
            }
        }
        for (size_t i = 0; i < maskChunks.size(); ++i) {
            const auto& mask = maskChunks[i];
            const std::string valuePath = valueChunks ? (*valueChunks)[i].vectorCiphertext.string() : "";
            if (valueChunks && ((*valueChunks)[i].rows != mask.rows || (*valueChunks)[i].slots != mask.slots)) {
                throw std::runtime_error("chunk row/slot mismatch for operation " + row.at("operation"));
            }
            output << csvEscape(row.at("analysis")) << ',' << csvEscape(row.at("group")) << ','
                   << csvEscape(row.at("label")) << ',' << csvEscape(row.at("operation")) << ','
                   << csvEscape(row.at("value_name")) << ',' << csvEscape(mask.vectorCiphertext.string()) << ','
                   << csvEscape(valuePath) << ',' << mask.rows << ',' << mask.slots << ',' << mask.chunk << '\n';
        }
    }
}

void writeScoreManifest(const Options& options,
                        const std::unordered_map<std::string, std::vector<ChunkInfo>>& chunksByVector) {
    const auto rows = readCsv(options.preparedDir / "linear_score_vectors.csv");
    std::ofstream output(options.serverOutputDir / "score_manifest.csv");
    if (!output.is_open()) {
        throw std::runtime_error("cannot write score manifest");
    }
    output << "feature,chunk,ciphertext,rows,slots,weight,bias\n";
    for (const auto& row : rows) {
        const auto& chunks = requireChunks(chunksByVector, row.at("vector"));
        for (const auto& chunk : chunks) {
            if (chunk.scoreCiphertext.empty()) {
                throw std::runtime_error("ML feature missing score ciphertext: " + row.at("vector"));
            }
            output << csvEscape(row.at("feature")) << ',' << chunk.chunk << ','
                   << csvEscape(chunk.scoreCiphertext.string()) << ',' << chunk.rows << ',' << chunk.slots << ','
                   << row.at("weight") << ',' << row.at("bias") << '\n';
        }
    }
}

void writeBundleManifest(const Options& options, const std::unordered_map<std::string, VectorSpec>& specs) {
    std::ofstream output(options.serverOutputDir / "bundle_manifest.json");
    if (!output.is_open()) {
        throw std::runtime_error("cannot write bundle manifest");
    }
    output << "{\n";
    output << "  \"scheme\": \"CKKS\",\n";
    output << "  \"slots\": " << options.slots << ",\n";
    output << "  \"multiplicative_depth\": " << options.multiplicativeDepth << ",\n";
    output << "  \"scaling_mod_size\": " << options.scalingModSize << ",\n";
    output << "  \"first_mod_size\": " << options.firstModSize << ",\n";
    output << "  \"vector_count\": " << specs.size() << ",\n";
    output << "  \"server_files\": [\n";
    output << "    \"crypto_context.bin\",\n";
    output << "    \"public_key.bin\",\n";
    output << "    \"eval_sum_keys.bin\",\n";
    output << "    \"eval_mult_keys.bin\",\n";
    output << "    \"column_manifest.csv\",\n";
    output << "    \"aggregate_manifest.csv\",\n";
    output << "    \"score_manifest.csv\"\n";
    output << "  ],\n";
    output << "  \"client_secret_key\": \"" << (options.clientKeyDir / "secret_key.bin").string() << "\"\n";
    output << "}\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto specs = readVectorManifest(options.preparedDir);

        auto cc = makeContext(options);
        const auto keys = cc->KeyGen();
        cc->EvalMultKeyGen(keys.secretKey);
        cc->EvalSumKeyGen(keys.secretKey);

        serializeContextAndKeys(options, cc, keys);
        const auto chunksByVector = encryptVectors(options, cc, keys.publicKey, specs);

        writeColumnManifest(options, chunksByVector);
        writeAggregateManifest(options, chunksByVector);
        writeScoreManifest(options, chunksByVector);
        writeBundleManifest(options, specs);

        std::cout << "encrypt_home_credit_payload complete\n";
        std::cout << "server bundle: " << options.serverOutputDir << "\n";
        std::cout << "client key: " << (options.clientKeyDir / "secret_key.bin") << "\n";
        std::cout << "vectors: " << specs.size() << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "encrypt_home_credit_payload failed: " << ex.what() << '\n';
        return 1;
    }
}
