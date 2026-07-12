#include "openfhe.h"

#include "ciphertext-ser.h"
#include "cryptocontext-ser.h"
#include "key/key-ser.h"
#include "scheme/ckksrns/ckksrns-ser.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <complex>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
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
    std::filesystem::path secretKeyPath;
    std::filesystem::path manifestPath;
    std::filesystem::path inputDir;
    std::filesystem::path outputCsv;
    std::string manifestType;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr
        << "Usage:\n"
        << "  decrypt_ckks_results \\\n"
        << "    --context <crypto_context.bin> \\\n"
        << "    --secret-key <secret_key.bin> \\\n"
        << "    --manifest <result_manifest.csv> \\\n"
        << "    --input-dir <result_dir> \\\n"
        << "    --output-csv <decrypted.csv> \\\n"
        << "    --manifest-type numeric|aggregate|score\n";
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
        else if (arg == "--manifest-type") {
            options.manifestType = needValue(arg);
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }
    if (options.contextPath.empty() || options.secretKeyPath.empty() || options.manifestPath.empty() ||
        options.inputDir.empty() || options.outputCsv.empty() || options.manifestType.empty()) {
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

void deserializeContext(const std::filesystem::path& path, CryptoContext<DCRTPoly>& cc) {
    if (!Serial::DeserializeFromFile(path.string(), cc, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize crypto context: " + path.string());
    }
}

void deserializeSecretKey(const std::filesystem::path& path, PrivateKey<DCRTPoly>& secretKey) {
    if (!Serial::DeserializeFromFile(path.string(), secretKey, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize secret key: " + path.string());
    }
}

Ciphertext<DCRTPoly> deserializeCiphertext(const std::filesystem::path& path) {
    Ciphertext<DCRTPoly> ciphertext;
    if (!Serial::DeserializeFromFile(path.string(), ciphertext, SerType::BINARY)) {
        throw std::runtime_error("cannot deserialize ciphertext: " + path.string());
    }
    return ciphertext;
}

std::vector<double> decryptValues(const CryptoContext<DCRTPoly>& cc, const PrivateKey<DCRTPoly>& secretKey,
                                  const std::filesystem::path& path, size_t length) {
    const auto ciphertext = deserializeCiphertext(path);
    Plaintext plaintext;
    cc->Decrypt(secretKey, ciphertext, &plaintext);
    plaintext->SetLength(length);
    const auto packed = plaintext->GetCKKSPackedValue();
    std::vector<double> values;
    values.reserve(packed.size());
    for (const auto& value : packed) {
        values.push_back(value.real());
    }
    return values;
}

void decryptNumeric(const Options& options, const CryptoContext<DCRTPoly>& cc, const PrivateKey<DCRTPoly>& secretKey,
                    std::ifstream& manifest, std::ofstream& output) {
    output << "column,value,total_rows,total_slots,chunk_count\n";
    std::string line;
    while (std::getline(manifest, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != 5) {
            throw std::runtime_error("numeric manifest rows must have 5 fields");
        }
        const auto values = decryptValues(cc, secretKey, options.inputDir / fields[1], 1);
        output << csvEscape(fields[0]) << ',' << values.at(0) << ',' << fields[2] << ',' << fields[3] << ','
               << fields[4] << '\n';
    }
}

void decryptAggregate(const Options& options, const CryptoContext<DCRTPoly>& cc,
                      const PrivateKey<DCRTPoly>& secretKey, std::ifstream& manifest, std::ofstream& output) {
    output << "analysis,group,label,operation,value_name,value,total_rows,total_slots,chunk_count\n";
    std::string line;
    while (std::getline(manifest, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != 9) {
            throw std::runtime_error("aggregate manifest rows must have 9 fields");
        }
        const auto values = decryptValues(cc, secretKey, options.inputDir / fields[5], 1);
        output << csvEscape(fields[0]) << ',' << csvEscape(fields[1]) << ',' << csvEscape(fields[2]) << ','
               << csvEscape(fields[3]) << ',' << csvEscape(fields[4]) << ',' << values.at(0) << ',' << fields[6]
               << ',' << fields[7] << ',' << fields[8] << '\n';
    }
}

void decryptScore(const Options& options, const CryptoContext<DCRTPoly>& cc, const PrivateKey<DCRTPoly>& secretKey,
                  std::ifstream& manifest, std::ofstream& output) {
    output << "chunk,slot,score\n";
    std::string line;
    while (std::getline(manifest, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto fields = splitCsvLine(line);
        if (fields.size() != 5) {
            throw std::runtime_error("score manifest rows must have 5 fields");
        }
        const size_t rows = static_cast<size_t>(std::stoull(fields[2]));
        const size_t slots = static_cast<size_t>(std::stoull(fields[3]));
        const auto values = decryptValues(cc, secretKey, options.inputDir / fields[1], slots);
        for (size_t i = 0; i < rows; ++i) {
            output << fields[0] << ',' << i << ',' << values.at(i) << '\n';
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto totalStarted = Clock::now();
        const auto options = parseArgs(argc, argv);

        const auto deserializeStarted = Clock::now();
        CryptoContext<DCRTPoly> cc;
        PrivateKey<DCRTPoly> secretKey;
        deserializeContext(options.contextPath, cc);
        deserializeSecretKey(options.secretKeyPath, secretKey);
        printTiming("deserialize_context_secret_seconds", secondsSince(deserializeStarted));

        const auto decryptStarted = Clock::now();
        std::ifstream manifest(options.manifestPath);
        if (!manifest.is_open()) {
            throw std::runtime_error("cannot open result manifest: " + options.manifestPath.string());
        }
        std::string header;
        if (!std::getline(manifest, header)) {
            throw std::runtime_error("result manifest is empty");
        }

        if (!options.outputCsv.parent_path().empty()) {
            std::filesystem::create_directories(options.outputCsv.parent_path());
        }
        std::ofstream output(options.outputCsv);
        if (!output.is_open()) {
            throw std::runtime_error("cannot write output CSV: " + options.outputCsv.string());
        }

        if (options.manifestType == "numeric") {
            decryptNumeric(options, cc, secretKey, manifest, output);
        }
        else if (options.manifestType == "aggregate") {
            decryptAggregate(options, cc, secretKey, manifest, output);
        }
        else if (options.manifestType == "score") {
            decryptScore(options, cc, secretKey, manifest, output);
        }
        else {
            throw std::runtime_error("unknown manifest type: " + options.manifestType);
        }
        printTiming("decrypt_rows_seconds", secondsSince(decryptStarted));
        printTiming("total_seconds", secondsSince(totalStarted));

        std::cout << "decrypt_ckks_results complete\n";
        std::cout << "output: " << options.outputCsv << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "decrypt_ckks_results failed: " << ex.what() << '\n';
        return 1;
    }
}
