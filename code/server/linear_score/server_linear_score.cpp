#include "openfhe.h"

#include "ciphertext-ser.h"
#include "cryptocontext-ser.h"
#include "scheme/ckksrns/ckksrns-ser.h"

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
    std::filesystem::path manifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputDir;
};

struct FeatureChunk {
    std::string feature;
    uint32_t chunk = 0;
    std::filesystem::path ciphertext;
    uint32_t rows = 0;
    uint32_t slots = 0;
    double weight = 0.0;
    double bias = 0.0;
};

struct ScoreResult {
    uint32_t chunk = 0;
    std::filesystem::path outputCiphertext;
    uint32_t rows = 0;
    uint32_t slots = 0;
    uint64_t featureCount = 0;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  server_linear_score \\\n"
        << "    --context <crypto_context.bin> \\\n"
        << "    --manifest <score_manifest.csv> \\\n"
        << "    --input-dir <encrypted_score_features_dir> \\\n"
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
    if (options.contextPath.empty() || options.manifestPath.empty() || options.inputDir.empty() ||
        options.outputDir.empty()) {
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

std::string safeFileStem(std::string value) {
    for (char& ch : value) {
        const bool ok = std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == '-' || ch == '.';
        if (!ok) {
            ch = '_';
        }
    }
    return value.empty() ? "score" : value;
}

std::vector<FeatureChunk> readManifest(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("cannot open score manifest: " + path.string());
    }
    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("score manifest is empty");
    }
    const auto header = splitCsvLine(line);
    const std::vector<std::string> expected = {"feature", "chunk", "ciphertext", "rows", "slots", "weight", "bias"};
    if (header != expected) {
        throw std::runtime_error("score manifest header must be: feature,chunk,ciphertext,rows,slots,weight,bias");
    }

    std::vector<FeatureChunk> chunks;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != 7) {
            throw std::runtime_error("score manifest row must have 7 fields");
        }
        FeatureChunk chunk;
        chunk.feature = fields[0];
        chunk.chunk = static_cast<uint32_t>(std::stoul(fields[1]));
        chunk.ciphertext = fields[2];
        chunk.rows = static_cast<uint32_t>(std::stoul(fields[3]));
        chunk.slots = static_cast<uint32_t>(std::stoul(fields[4]));
        chunk.weight = std::stod(fields[5]);
        chunk.bias = std::stod(fields[6]);
        chunks.push_back(chunk);
    }
    if (chunks.empty()) {
        throw std::runtime_error("score manifest contains no feature chunks");
    }
    return chunks;
}

void deserializeContext(const std::filesystem::path& path, CryptoContext<DCRTPoly>& cc) {
    if (!Serial::DeserializeFromFile(path.string(), cc, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize crypto context: " + path.string());
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

std::map<uint32_t, std::vector<FeatureChunk>> groupByChunk(const std::vector<FeatureChunk>& chunks) {
    std::map<uint32_t, std::vector<FeatureChunk>> grouped;
    for (const auto& chunk : chunks) {
        grouped[chunk.chunk].push_back(chunk);
    }
    return grouped;
}

std::vector<ScoreResult> runScore(const Options& options, const CryptoContext<DCRTPoly>& cc,
                                  const std::map<uint32_t, std::vector<FeatureChunk>>& grouped) {
    std::filesystem::create_directories(options.outputDir / "scores");
    std::vector<ScoreResult> results;

    for (const auto& [chunkIndex, chunks] : grouped) {
        if (chunks.empty()) {
            continue;
        }
        const auto rows = chunks.front().rows;
        const auto slots = chunks.front().slots;
        const auto bias = chunks.front().bias;
        Ciphertext<DCRTPoly> score;

        for (const auto& chunk : chunks) {
            if (chunk.rows != rows || chunk.slots != slots) {
                throw std::runtime_error("score feature chunks must align within chunk " + std::to_string(chunkIndex));
            }
            auto featureCiphertext = deserializeCiphertext(options.inputDir / chunk.ciphertext);
            auto weightPlaintext = cc->MakeCKKSPackedPlaintext(std::vector<double>(slots, chunk.weight));
            auto weighted = cc->EvalMult(featureCiphertext, weightPlaintext);
            if (!score) {
                score = weighted;
            }
            else {
                score = cc->EvalAdd(score, weighted);
            }
        }

        auto biasPlaintext = cc->MakeCKKSPackedPlaintext(std::vector<double>(slots, bias));
        score = cc->EvalAdd(score, biasPlaintext);

        ScoreResult result;
        result.chunk = chunkIndex;
        result.rows = rows;
        result.slots = slots;
        result.featureCount = chunks.size();
        result.outputCiphertext = std::filesystem::path("scores") / (safeFileStem("score_" + std::to_string(chunkIndex)) + ".bin");
        serializeCiphertext(options.outputDir / result.outputCiphertext, score);
        results.push_back(result);
    }
    return results;
}

void writeOutputManifest(const std::filesystem::path& outputDir, const std::vector<ScoreResult>& results) {
    std::ofstream output(outputDir / "score_summary_manifest.csv");
    if (!output.is_open()) {
        throw std::runtime_error("cannot write score output manifest");
    }
    output << "chunk,encrypted_score_ciphertext,rows,slots,feature_count\n";
    for (const auto& result : results) {
        output << result.chunk << ',' << csvEscape(result.outputCiphertext.string()) << ',' << result.rows << ','
               << result.slots << ',' << result.featureCount << '\n';
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        const auto chunks = readManifest(options.manifestPath);
        const auto grouped = groupByChunk(chunks);

        CryptoContext<DCRTPoly> cc;
        deserializeContext(options.contextPath, cc);

        const auto results = runScore(options, cc, grouped);
        writeOutputManifest(options.outputDir, results);

        std::cout << "server_linear_score complete\n";
        std::cout << "chunks: " << results.size() << "\n";
        std::cout << "output: " << (options.outputDir / "score_summary_manifest.csv") << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "server_linear_score failed: " << ex.what() << '\n';
        return 1;
    }
}
