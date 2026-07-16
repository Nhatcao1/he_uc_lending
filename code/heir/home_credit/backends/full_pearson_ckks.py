"""One-pair full-CKKS Pearson trial using HEIR generated dot products."""

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
#include <cmath>
#include <filesystem>
#include <fstream>
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
  std::getline(input, line);
  std::vector<double> values;
  while (std::getline(input, line)) {
    const auto value = trim(line);
    if (!value.empty()) values.push_back(std::stod(value));
  }
  return values;
}

std::vector<CiphertextT> generatedDot(
    CryptoContextT cc, PublicKeyT pk, const std::vector<double>& left, const std::vector<double>& right,
    double& encryptionSeconds, double& computeSeconds) {
  if (left.size() != right.size()) throw std::runtime_error("vector size mismatch");
  constexpr std::size_t kChunkSize = @VECTOR_SIZE@;
  std::vector<CiphertextT> outputs;
  for (std::size_t offset = 0; offset < left.size(); offset += kChunkSize) {
    std::vector<double> leftChunk(kChunkSize, 0.0), rightChunk(kChunkSize, 0.0);
    for (std::size_t i = 0; i < kChunkSize && offset + i < left.size(); ++i) {
      leftChunk[i] = left[offset + i];
      rightChunk[i] = right[offset + i];
    }
    const auto encryptStarted = std::chrono::steady_clock::now();
    auto leftCt = dot_product__encrypt__arg0(cc, leftChunk, pk);
    auto rightCt = dot_product__encrypt__arg1(cc, rightChunk, pk);
    const auto encryptEnded = std::chrono::steady_clock::now();
    encryptionSeconds += std::chrono::duration<double>(encryptEnded - encryptStarted).count();
    const auto computeStarted = std::chrono::steady_clock::now();
    auto result = dot_product(cc, leftCt, rightCt);
    const auto computeEnded = std::chrono::steady_clock::now();
    computeSeconds += std::chrono::duration<double>(computeEnded - computeStarted).count();
    outputs.push_back(result.at(0));
  }
  if (outputs.empty()) throw std::runtime_error("empty generated dot-product input");
  auto total = outputs.front();
  for (std::size_t i = 1; i < outputs.size(); ++i) cc->EvalAddInPlace(total, outputs[i]);
  return {total};
}

CiphertextT multiply(CryptoContextT cc, const CiphertextT& left, const CiphertextT& right) {
  auto result = cc->EvalMult(left, right);
  cc->ModReduceInPlace(result);
  return result;
}

CiphertextT multiplyScalar(CryptoContextT cc, const CiphertextT& value, double factor) {
  // CKKS scalar multiplication remains encrypted and avoids manufacturing a
  // second all-slots plaintext solely for an aggregate scalar.
  auto result = cc->EvalMult(value, factor);
  cc->ModReduceInPlace(result);
  return result;
}

double decryptScalar(CryptoContextT cc, const CiphertextT& value, PrivateKeyT sk, double& decryptionSeconds) {
  const auto started = std::chrono::steady_clock::now();
  const double result = static_cast<double>(dot_product__decrypt__result0(cc, {value}, sk));
  decryptionSeconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
  return result;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 10) {
    std::cerr << "usage: " << argv[0]
              << " <x.csv> <y.csv> <x_over_n.csv> <y_over_n.csv> <inverse_n.csv> <ones.csv>"
              << " <inverse_sqrt_scale> <chebyshev_degree> <output.json>\n";
    return 2;
  }
  try {
    const auto x = readVector(argv[1]);
    const auto y = readVector(argv[2]);
    const auto xOverN = readVector(argv[3]);
    const auto yOverN = readVector(argv[4]);
    const auto inverseN = readVector(argv[5]);
    const auto ones = readVector(argv[6]);
    const double inverseSqrtScale = std::stod(argv[7]);
    const uint32_t chebyshevDegree = static_cast<uint32_t>(std::stoul(argv[8]));
    const std::filesystem::path outputPath = argv[9];
    if (x.empty() || x.size() != y.size() || x.size() != xOverN.size() || x.size() != yOverN.size() ||
        x.size() != inverseN.size() || x.size() != ones.size()) {
      throw std::runtime_error("Pearson input vectors must be non-empty and equal length");
    }
    if (!(inverseSqrtScale > 0.0)) throw std::runtime_error("inverse_sqrt_scale must be positive");

    const auto started = std::chrono::steady_clock::now();
    lbcrypto::CCParams<lbcrypto::CryptoContextCKKSRNS> params;
    params.SetMultiplicativeDepth(20);
    params.SetScalingModSize(50);
    params.SetFirstModSize(60);
    params.SetSecurityLevel(lbcrypto::HEStd_128_classic);
    params.SetBatchSize(@VECTOR_SIZE@);
    auto cc = lbcrypto::GenCryptoContext(params);
    cc->Enable(lbcrypto::PKE);
    cc->Enable(lbcrypto::KEYSWITCH);
    cc->Enable(lbcrypto::LEVELEDSHE);
    cc->Enable(lbcrypto::ADVANCEDSHE);
    const auto contextEnded = std::chrono::steady_clock::now();
    auto keyPair = cc->KeyGen();
    cc = dot_product__configure_crypto_context(cc, keyPair.secretKey);
    const auto keygenEnded = std::chrono::steady_clock::now();

    double encryptionSeconds = 0.0, dotComputeSeconds = 0.0, decryptionSeconds = 0.0;
    const auto computeStarted = std::chrono::steady_clock::now();
    const auto count = generatedDot(cc, keyPair.publicKey, ones, ones, encryptionSeconds, dotComputeSeconds).at(0);
    const auto meanX = generatedDot(cc, keyPair.publicKey, x, inverseN, encryptionSeconds, dotComputeSeconds).at(0);
    const auto meanY = generatedDot(cc, keyPair.publicKey, y, inverseN, encryptionSeconds, dotComputeSeconds).at(0);
    const auto meanXY = generatedDot(cc, keyPair.publicKey, x, yOverN, encryptionSeconds, dotComputeSeconds).at(0);
    const auto meanX2 = generatedDot(cc, keyPair.publicKey, x, xOverN, encryptionSeconds, dotComputeSeconds).at(0);
    const auto meanY2 = generatedDot(cc, keyPair.publicKey, y, yOverN, encryptionSeconds, dotComputeSeconds).at(0);

    const auto covariance = cc->EvalSub(meanXY, multiply(cc, meanX, meanY));
    const auto varianceX = cc->EvalSub(meanX2, multiply(cc, meanX, meanX));
    const auto varianceY = cc->EvalSub(meanY2, multiply(cc, meanY, meanY));
    const auto scaledVarianceProduct = multiplyScalar(cc, multiply(cc, varianceX, varianceY), inverseSqrtScale);
    const auto inverseSqrt = cc->EvalChebyshevFunction(
        [](double value) { return 1.0 / std::sqrt(value); }, scaledVarianceProduct, 0.5, 1.5, chebyshevDegree);
    const auto correlation = multiplyScalar(
        cc, multiply(cc, covariance, inverseSqrt), std::sqrt(inverseSqrtScale));
    const auto computeEnded = std::chrono::steady_clock::now();

    const double countValue = decryptScalar(cc, count, keyPair.secretKey, decryptionSeconds);
    const double meanXValue = decryptScalar(cc, meanX, keyPair.secretKey, decryptionSeconds);
    const double meanYValue = decryptScalar(cc, meanY, keyPair.secretKey, decryptionSeconds);
    const double meanXYValue = decryptScalar(cc, meanXY, keyPair.secretKey, decryptionSeconds);
    const double meanX2Value = decryptScalar(cc, meanX2, keyPair.secretKey, decryptionSeconds);
    const double meanY2Value = decryptScalar(cc, meanY2, keyPair.secretKey, decryptionSeconds);
    const double correlationValue = decryptScalar(cc, correlation, keyPair.secretKey, decryptionSeconds);
    const auto ended = std::chrono::steady_clock::now();

    std::ofstream output(outputPath);
    if (!output) throw std::runtime_error("cannot write output json");
    output << "{\n"
           << "  \"backend\": \"heir_generated_ckks_plus_openfhe_chebyshev\",\n"
           << "  \"scheme\": \"CKKS\",\n"
           << "  \"generated_function\": \"dot_product\",\n"
           << "  \"analysis_mode\": \"single_pair_full_pearson\",\n"
           << "  \"chunk_size\": @VECTOR_SIZE@,\n"
           << "  \"complete_rows\": " << x.size() << ",\n"
           << "  \"inverse_sqrt_scale\": " << inverseSqrtScale << ",\n"
           << "  \"chebyshev_degree\": " << chebyshevDegree << ",\n"
           << "  \"count\": " << countValue << ",\n"
           << "  \"mean_x\": " << meanXValue << ",\n"
           << "  \"mean_y\": " << meanYValue << ",\n"
           << "  \"mean_xy\": " << meanXYValue << ",\n"
           << "  \"mean_x2\": " << meanX2Value << ",\n"
           << "  \"mean_y2\": " << meanY2Value << ",\n"
           << "  \"correlation\": " << correlationValue << ",\n"
           << "  \"context_setup_seconds\": " << std::chrono::duration<double>(contextEnded - started).count() << ",\n"
           << "  \"keygen_configure_seconds\": " << std::chrono::duration<double>(keygenEnded - contextEnded).count() << ",\n"
           << "  \"encryption_seconds\": " << encryptionSeconds << ",\n"
           << "  \"heir_dot_compute_seconds\": " << dotComputeSeconds << ",\n"
           << "  \"pearson_postprocess_seconds\": " << std::chrono::duration<double>(computeEnded - computeStarted).count() - dotComputeSeconds << ",\n"
           << "  \"encrypted_compute_seconds\": " << std::chrono::duration<double>(computeEnded - computeStarted).count() << ",\n"
           << "  \"decryption_seconds\": " << decryptionSeconds << ",\n"
           << "  \"total_seconds_inside_runner\": " << std::chrono::duration<double>(ended - started).count() << "\n"
           << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "full_pearson_runner failed: " << error.what() << "\n";
    return 1;
  }
}
'''


def run_full_pearson_generated_ckks_backend(
    run_dir: Path, generated_dir: Path, openfhe_dir: str, vector_size: int,
    heir_opt: str, heir_translate: str, heir_opt_pipeline: str,
    inverse_sqrt_scale: float, chebyshev_degree: int,
) -> tuple[dict[str, float], dict[str, object], str]:
    run_dir = run_dir.resolve()
    work_dir, build_dir = run_dir / "heir_generated_ckks", run_dir / "heir_generated_ckks" / "build"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    mlir_path = work_dir / f"home_credit_full_pearson_{vector_size}.mlir"
    mlir_path.write_text(dot_product_ckks_mlir(vector_size), encoding="utf-8")
    timings: dict[str, float] = {}
    logs: list[str] = []
    if heir_opt_pipeline:
        generated_timings, output = generate_heir_sources(mlir_path, work_dir, heir_opt, heir_translate, heir_opt_pipeline)
        timings.update(generated_timings); logs.append(output)
    else:
        copy_generated_sources(generated_dir, work_dir)
    proof = validate_generated_ckks(work_dir)
    if proof.get("detected_vector_size") and int(proof["detected_vector_size"]) != vector_size:
        raise ValueError("generated CKKS vector size does not match requested Pearson vector size")
    (work_dir / "home_credit_heir_generated_ckks_runner.cpp").write_text(
        RUNNER_CPP_TEMPLATE.replace("@VECTOR_SIZE@", str(vector_size)), encoding="utf-8"
    )
    (work_dir / "CMakeLists.txt").write_text(CMAKE_TEMPLATE, encoding="utf-8")
    configure = ["cmake", "-S", str(work_dir), "-B", str(build_dir)]
    if openfhe_dir:
        configure.append(f"-DOpenFHE_DIR={openfhe_dir}")
    timings["heir_generated_ckks_cmake_configure_seconds"], output = run_command(configure, run_dir); logs.append(output)
    timings["heir_generated_ckks_build_seconds"], output = run_command(
        ["cmake", "--build", str(build_dir), "--target", "home_credit_heir_generated_ckks_runner"], run_dir
    ); logs.append(output)
    result_path = run_dir / "heir_result.json"
    runner = build_dir / "home_credit_heir_generated_ckks_runner"
    tensors = run_dir / "tensors"
    timings["heir_generated_ckks_runner_seconds"], output = run_command(
        [str(runner), str(tensors / "x.csv"), str(tensors / "y.csv"), str(tensors / "x_times_inverse_n.csv"),
         str(tensors / "y_times_inverse_n.csv"), str(tensors / "inverse_n.csv"), str(tensors / "ones.csv"),
         str(inverse_sqrt_scale), str(chebyshev_degree), str(result_path)], run_dir
    ); logs.append(output)
    result = read_result(result_path)
    result.update({"heir_proof": proof, "mlir_input": str(mlir_path), "runner_binary": str(runner), "cmake_project_dir": str(work_dir)})
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return timings, result, "\n".join(logs)
