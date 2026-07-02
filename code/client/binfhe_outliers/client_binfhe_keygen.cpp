#include "binfhecontext-ser.h"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace lbcrypto;

namespace {

struct Options {
    std::filesystem::path outputDir = "keys/binfhe_outliers";
    uint32_t logQ = 12;
    bool toy = false;
};

[[noreturn]] void usage(const std::string& error = "") {
    if (!error.empty()) {
        std::cerr << "error: " << error << "\n\n";
    }
    std::cerr << "Usage:\n"
              << "  client_binfhe_keygen [--out-dir keys/binfhe_outliers] [--log-q 12] [--toy]\n";
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
        if (arg == "--out-dir") {
            options.outputDir = needValue(arg);
        }
        else if (arg == "--log-q") {
            options.logQ = static_cast<uint32_t>(std::stoul(needValue(arg)));
        }
        else if (arg == "--toy") {
            options.toy = true;
        }
        else if (arg == "--help" || arg == "-h") {
            usage();
        }
        else {
            usage("unknown argument: " + arg);
        }
    }
    return options;
}

template <typename T>
void serializeFile(const std::filesystem::path& path, const T& value) {
    if (!Serial::SerializeToFile(path.string(), value, SerType::BINARY)) {
        throw std::runtime_error("cannot serialize: " + path.string());
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parseArgs(argc, argv);
        std::filesystem::create_directories(options.outputDir);

        BinFHEContext cc;
        cc.GenerateBinFHEContext(options.toy ? TOY : STD128, true, options.logQ);

        auto sk = cc.KeyGen();
        cc.BTKeyGen(sk);

        serializeFile(options.outputDir / "binfhe_context.bin", cc);
        serializeFile(options.outputDir / "binfhe_refresh_key.bin", cc.GetRefreshKey());
        serializeFile(options.outputDir / "binfhe_switch_key.bin", cc.GetSwitchKey());
        serializeFile(options.outputDir / "binfhe_secret_key.bin", sk);

        const auto maxPlaintext = cc.GetMaxPlaintextSpace().ConvertToInt();
        std::ofstream manifest(options.outputDir / "binfhe_key_manifest.json");
        manifest << "{\n"
                 << "  \"scheme\": \"BinFHE/FHEW\",\n"
                 << "  \"security\": \"" << (options.toy ? "TOY" : "STD128") << "\",\n"
                 << "  \"log_q\": " << options.logQ << ",\n"
                 << "  \"max_plaintext_space\": " << maxPlaintext << ",\n"
                 << "  \"server_files\": [\"binfhe_context.bin\", \"binfhe_refresh_key.bin\", \"binfhe_switch_key.bin\"],\n"
                 << "  \"client_secret_file\": \"binfhe_secret_key.bin\"\n"
                 << "}\n";

        std::cout << "client_binfhe_keygen complete\n";
        std::cout << "output_dir: " << options.outputDir << "\n";
        std::cout << "max_plaintext_space: " << maxPlaintext << "\n";
        return 0;
    }
    catch (const std::exception& ex) {
        std::cerr << "client_binfhe_keygen failed: " << ex.what() << "\n";
        return 1;
    }
}
