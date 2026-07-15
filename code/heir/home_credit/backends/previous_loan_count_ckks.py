"""HEIR-generated CKKS benchmark for one applicant-history feature.

The source-side layout is anonymous and fixed-shape: each applicant has a
row of 0/1 history slots. The generated HEIR dot-product kernel sums that row
against encrypted ones, yielding one encrypted previous-loan count per row.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from code.heir.home_credit.backends.generated_ckks import (
    CMAKE_TEMPLATE,
    copy_generated_sources,
    dot_product_ckks_mlir,
    generate_heir_sources,
    read_result,
    run_command,
    validate_generated_ckks,
)


RUNNER_CPP_TEMPLATE = r'''
#include <chrono>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "heir_output.h"

namespace {

std::string trim(const std::string& value) {
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) return "";
  const auto last = value.find_last_not_of(" \t\r\n");
  return value.substr(first, last - first + 1);
}

std::vector<double> readVector(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open vector: " + path.string());
  std::string line;
  std::getline(input, line);  // value header
  std::vector<double> values;
  while (std::getline(input, line)) {
    const auto value = trim(line);
    if (!value.empty()) values.push_back(std::stod(value));
  }
  return values;
}

double generatedDotSum(
    CryptoContextT cryptoContext,
    PublicKeyT publicKey,
    PrivateKeyT secretKey,
    const std::vector<double>& left,
    const std::vector<double>& right,
    double& encryptionSeconds,
    double& computeSeconds,
    double& decryptionSeconds) {
  if (left.size() != right.size()) {
    throw std::runtime_error("vector size mismatch");
  }
  constexpr std::size_t kChunkSize = @VECTOR_SIZE@;
  double total = 0.0;
  for (std::size_t offset = 0; offset < left.size(); offset += kChunkSize) {
    std::vector<double> leftChunk(kChunkSize, 0.0);
    std::vector<double> rightChunk(kChunkSize, 0.0);
    for (std::size_t index = 0; index < kChunkSize && offset + index < left.size(); ++index) {
      leftChunk[index] = left[offset + index];
      rightChunk[index] = right[offset + index];
    }
    const auto encryptStarted = std::chrono::steady_clock::now();
    auto encryptedLeft = dot_product__encrypt__arg0(cryptoContext, leftChunk, publicKey);
    auto encryptedRight = dot_product__encrypt__arg1(cryptoContext, rightChunk, publicKey);
    const auto encryptEnded = std::chrono::steady_clock::now();
    encryptionSeconds += std::chrono::duration<double>(encryptEnded - encryptStarted).count();

    const auto computeStarted = std::chrono::steady_clock::now();
    auto encryptedResult = dot_product(cryptoContext, encryptedLeft, encryptedRight);
    const auto computeEnded = std::chrono::steady_clock::now();
    computeSeconds += std::chrono::duration<double>(computeEnded - computeStarted).count();

    const auto decryptStarted = std::chrono::steady_clock::now();
    total += static_cast<double>(dot_product__decrypt__result0(cryptoContext, encryptedResult, secretKey));
    const auto decryptEnded = std::chrono::steady_clock::now();
    decryptionSeconds += std::chrono::duration<double>(decryptEnded - decryptStarted).count();
  }
  return total;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 7) {
    std::cerr << "usage: " << argv[0]
              << " <history_masks.csv> <unit_weights.csv> <application_count> <slots_per_application>"
              << " <output_json> <decrypted_output.csv>\n";
    return 2;
  }

  const auto started = std::chrono::steady_clock::now();
  try {
    const auto historyMasks = readVector(argv[1]);
    const auto unitWeights = readVector(argv[2]);
    const std::size_t applicationCount = std::stoull(argv[3]);
    const std::size_t slotsPerApplication = std::stoull(argv[4]);
    const std::filesystem::path outputJson = argv[5];
    const std::filesystem::path decryptedOutput = argv[6];

    if (applicationCount == 0 || slotsPerApplication == 0) {
      throw std::runtime_error("application_count and slots_per_application must be positive");
    }
    if (historyMasks.size() != applicationCount * slotsPerApplication) {
      throw std::runtime_error("history mask matrix shape does not match application_count * slots_per_application");
    }
    if (unitWeights.size() != slotsPerApplication) {
      throw std::runtime_error("unit weights length does not match slots_per_application");
    }

    const auto contextStarted = std::chrono::steady_clock::now();
    auto cryptoContext = dot_product__generate_crypto_context();
    const auto contextEnded = std::chrono::steady_clock::now();
    const double contextSeconds = std::chrono::duration<double>(contextEnded - contextStarted).count();

    const auto keygenStarted = std::chrono::steady_clock::now();
    auto keyPair = cryptoContext->KeyGen();
    cryptoContext = dot_product__configure_crypto_context(cryptoContext, keyPair.secretKey);
    const auto keygenEnded = std::chrono::steady_clock::now();
    const double keygenSeconds = std::chrono::duration<double>(keygenEnded - keygenStarted).count();

    std::ofstream decryptedFile(decryptedOutput);
    if (!decryptedFile) throw std::runtime_error("cannot write decrypted output: " + decryptedOutput.string());
    decryptedFile << "app_index,previous_loan_count\n";
    decryptedFile << std::setprecision(17);

    const auto evalStarted = std::chrono::steady_clock::now();
    double encryptionSeconds = 0.0;
    double computeSeconds = 0.0;
    double decryptionSeconds = 0.0;
    double totalPreviousLoanCount = 0.0;
    for (std::size_t appIndex = 0; appIndex < applicationCount; ++appIndex) {
      const auto begin = historyMasks.begin() + static_cast<std::ptrdiff_t>(appIndex * slotsPerApplication);
      const auto end = begin + static_cast<std::ptrdiff_t>(slotsPerApplication);
      std::vector<double> historyRow(begin, end);
      const double count = generatedDotSum(
          cryptoContext, keyPair.publicKey, keyPair.secretKey, historyRow, unitWeights,
          encryptionSeconds, computeSeconds, decryptionSeconds);
      totalPreviousLoanCount += count;
      decryptedFile << appIndex << ',' << count << '\n';
    }
    const auto evalEnded = std::chrono::steady_clock::now();
    const auto ended = std::chrono::steady_clock::now();
    const double evalSeconds = std::chrono::duration<double>(evalEnded - evalStarted).count();
    const double totalSeconds = std::chrono::duration<double>(ended - started).count();

    std::ofstream output(outputJson);
    if (!output) throw std::runtime_error("cannot write output json: " + outputJson.string());
    output << "{\n"
           << "  \"backend\": \"heir_generated_ckks_openfhe\",\n"
           << "  \"scheme\": \"CKKS\",\n"
           << "  \"codegen\": \"heir_generated_openfhe_cpp\",\n"
           << "  \"generated_function\": \"dot_product\",\n"
           << "  \"analysis_mode\": \"per_applicant_history_count\",\n"
           << "  \"chunk_size\": @VECTOR_SIZE@,\n"
           << "  \"application_count\": " << applicationCount << ",\n"
           << "  \"slots_per_application\": " << slotsPerApplication << ",\n"
           << "  \"decrypted_output_csv\": \"" << decryptedOutput.string() << "\",\n"
           << "  \"total_previous_loan_count\": " << totalPreviousLoanCount << ",\n"
           << "  \"context_setup_seconds\": " << contextSeconds << ",\n"
           << "  \"keygen_configure_seconds\": " << keygenSeconds << ",\n"
           << "  \"encryption_seconds\": " << encryptionSeconds << ",\n"
           << "  \"encrypted_compute_seconds\": " << computeSeconds << ",\n"
           << "  \"decryption_seconds\": " << decryptionSeconds << ",\n"
           << "  \"eval_seconds_inside_runner\": " << evalSeconds << ",\n"
           << "  \"total_seconds_inside_runner\": " << totalSeconds << "\n"
           << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "previous_loan_count_runner failed: " << error.what() << "\n";
    return 1;
  }
}
'''


def run_previous_loan_count_generated_ckks_backend(
    run_dir: Path,
    generated_dir: Path,
    openfhe_dir: str,
    vector_size: int,
    heir_opt: str,
    heir_translate: str,
    heir_opt_pipeline: str,
    application_count: int,
    slots_per_application: int,
) -> tuple[dict[str, float], dict[str, object], str]:
    """Compile and run the generated dot-product kernel for each anonymous row."""
    run_dir = run_dir.resolve()
    work_dir = run_dir / "heir_generated_ckks"
    build_dir = work_dir / "build"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    mlir_path = work_dir / f"home_credit_previous_loan_count_{vector_size}.mlir"
    mlir_path.write_text(dot_product_ckks_mlir(vector_size), encoding="utf-8")
    timings: dict[str, float] = {}
    logs: list[str] = []
    if heir_opt_pipeline:
        generated_timings, output = generate_heir_sources(
            mlir_path, work_dir, heir_opt, heir_translate, heir_opt_pipeline
        )
        timings.update(generated_timings)
        logs.append(output)
    else:
        copy_generated_sources(generated_dir, work_dir)

    proof = validate_generated_ckks(work_dir)
    detected_size = proof.get("detected_vector_size")
    if detected_size and int(detected_size) != vector_size:
        raise ValueError(f"generated CKKS vector size mismatch: requested {vector_size}, detected {detected_size}")

    runner_source = work_dir / "home_credit_heir_generated_ckks_runner.cpp"
    runner_source.write_text(RUNNER_CPP_TEMPLATE.replace("@VECTOR_SIZE@", str(vector_size)), encoding="utf-8")
    (work_dir / "CMakeLists.txt").write_text(CMAKE_TEMPLATE, encoding="utf-8")

    configure_command = ["cmake", "-S", str(work_dir), "-B", str(build_dir)]
    if openfhe_dir:
        configure_command.append(f"-DOpenFHE_DIR={openfhe_dir}")
    timings["heir_generated_ckks_cmake_configure_seconds"], output = run_command(configure_command, run_dir)
    logs.append(output)
    timings["heir_generated_ckks_build_seconds"], output = run_command(
        ["cmake", "--build", str(build_dir), "--target", "home_credit_heir_generated_ckks_runner"], run_dir
    )
    logs.append(output)

    result_path = run_dir / "heir_result.json"
    decrypted_path = run_dir / "heir_decrypted_previous_loan_count.csv"
    runner = build_dir / "home_credit_heir_generated_ckks_runner"
    timings["heir_generated_ckks_runner_seconds"], output = run_command(
        [
            str(runner),
            str(run_dir / "tensors" / "history_mask_matrix.csv"),
            str(run_dir / "tensors" / "unit_weights.csv"),
            str(application_count),
            str(slots_per_application),
            str(result_path),
            str(decrypted_path),
        ],
        run_dir,
    )
    logs.append(output)
    result = read_result(result_path)
    result["heir_proof"] = proof
    result["mlir_input"] = str(mlir_path)
    result["runner_binary"] = str(runner)
    result["cmake_project_dir"] = str(work_dir)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return timings, result, "\n".join(logs)
