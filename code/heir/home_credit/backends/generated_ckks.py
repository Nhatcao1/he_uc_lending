"""Strict HEIR-generated CKKS/OpenFHE backend.

This backend proves the encrypted kernel came from HEIR-generated OpenFHE
source. It refuses to run if the generated source is missing, non-CKKS, or does
not compile into a runner that calls the generated function.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


RUNNER_CPP_TEMPLATE = r'''
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "heir_output.h"

namespace {

struct TensorRow {
  std::string name;
  std::string kind;
  std::string label;
  std::string file;
  std::size_t rows = 0;
};

std::string trim(const std::string& value) {
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return "";
  }
  const auto last = value.find_last_not_of(" \t\r\n");
  return value.substr(first, last - first + 1);
}

std::vector<std::string> splitCsvLine(const std::string& line) {
  std::vector<std::string> fields;
  std::string current;
  bool quoted = false;
  for (std::size_t i = 0; i < line.size(); ++i) {
    const char ch = line[i];
    if (quoted) {
      if (ch == '"' && i + 1 < line.size() && line[i + 1] == '"') {
        current.push_back('"');
        ++i;
      } else if (ch == '"') {
        quoted = false;
      } else {
        current.push_back(ch);
      }
    } else if (ch == '"') {
      quoted = true;
    } else if (ch == ',') {
      fields.push_back(current);
      current.clear();
    } else {
      current.push_back(ch);
    }
  }
  fields.push_back(current);
  return fields;
}

std::string jsonEscape(const std::string& value) {
  std::string escaped;
  for (const char ch : value) {
    switch (ch) {
      case '\\': escaped += "\\\\"; break;
      case '"': escaped += "\\\""; break;
      case '\n': escaped += "\\n"; break;
      case '\r': escaped += "\\r"; break;
      case '\t': escaped += "\\t"; break;
      default: escaped.push_back(ch); break;
    }
  }
  return escaped;
}

std::vector<TensorRow> readManifest(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open tensor manifest: " + path.string());
  }
  std::string line;
  if (!std::getline(input, line)) {
    throw std::runtime_error("empty tensor manifest: " + path.string());
  }
  std::vector<TensorRow> rows;
  while (std::getline(input, line)) {
    if (trim(line).empty()) {
      continue;
    }
    const auto fields = splitCsvLine(line);
    if (fields.size() < 5) {
      throw std::runtime_error("bad tensor manifest row: " + line);
    }
    TensorRow row;
    row.name = fields[0];
    row.kind = fields[1];
    row.label = fields[2];
    row.file = fields[3];
    row.rows = static_cast<std::size_t>(std::stoull(fields[4]));
    rows.push_back(row);
  }
  return rows;
}

std::vector<double> readVector(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open vector: " + path.string());
  }
  std::string line;
  std::getline(input, line);  // header
  std::vector<double> values;
  while (std::getline(input, line)) {
    const auto text = trim(line);
    if (text.empty()) {
      continue;
    }
    values.push_back(std::stod(splitCsvLine(text)[0]));
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
  double total = 0.0;
  constexpr std::size_t kChunkSize = @VECTOR_SIZE@;
  for (std::size_t offset = 0; offset < left.size(); offset += kChunkSize) {
    std::vector<double> chunkLeft(kChunkSize, 0.0);
    std::vector<double> chunkRight(kChunkSize, 0.0);
    for (std::size_t i = 0; i < kChunkSize && offset + i < left.size(); ++i) {
      chunkLeft[i] = left[offset + i];
      chunkRight[i] = right[offset + i];
    }
    const auto encryptStarted = std::chrono::steady_clock::now();
    auto encryptedLeft = dot_product__encrypt__arg0(cryptoContext, chunkLeft, publicKey);
    auto encryptedRight = dot_product__encrypt__arg1(cryptoContext, chunkRight, publicKey);
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
  if (argc != 4) {
    std::cerr << "usage: " << argv[0] << " <run_dir> <tensor_manifest.csv> <output_json>\n";
    return 2;
  }

  const auto started = std::chrono::steady_clock::now();
  const std::filesystem::path runDir = argv[1];
  const std::filesystem::path manifestPath = argv[2];
  const std::filesystem::path outputPath = argv[3];

  try {
    const auto manifestRows = readManifest(manifestPath);
    TensorRow targetRow;
    std::vector<TensorRow> groupRows;
    for (const auto& row : manifestRows) {
      if (row.kind == "target_mask") {
        targetRow = row;
      } else if (row.kind == "group_mask") {
        groupRows.push_back(row);
      }
    }
    if (targetRow.file.empty()) {
      throw std::runtime_error("tensor manifest has no target_mask row");
    }

    auto targetMask = readVector(runDir / targetRow.file);
    std::vector<double> oneMask(targetMask.size(), 1.0);

    const auto contextStarted = std::chrono::steady_clock::now();
    auto cryptoContext = dot_product__generate_crypto_context();
    const auto contextEnded = std::chrono::steady_clock::now();
    const double contextSeconds = std::chrono::duration<double>(contextEnded - contextStarted).count();

    const auto keygenStarted = std::chrono::steady_clock::now();
    auto keyPair = cryptoContext->KeyGen();
    cryptoContext = dot_product__configure_crypto_context(cryptoContext, keyPair.secretKey);
    const auto keygenEnded = std::chrono::steady_clock::now();
    const double keygenSeconds = std::chrono::duration<double>(keygenEnded - keygenStarted).count();

    const auto evalStarted = std::chrono::steady_clock::now();
    double encryptionSeconds = 0.0;
    double computeSeconds = 0.0;
    double decryptionSeconds = 0.0;

    struct Result {
      std::string label;
      double count;
      double defaultCount;
    };
    std::vector<Result> results;
    results.reserve(groupRows.size());
    for (const auto& groupRow : groupRows) {
      auto groupMask = readVector(runDir / groupRow.file);
      const double count = generatedDotSum(
          cryptoContext, keyPair.publicKey, keyPair.secretKey, groupMask, oneMask,
          encryptionSeconds, computeSeconds, decryptionSeconds);
      const double defaultCount = generatedDotSum(
          cryptoContext, keyPair.publicKey, keyPair.secretKey, groupMask, targetMask,
          encryptionSeconds, computeSeconds, decryptionSeconds);
      results.push_back({groupRow.label, count, defaultCount});
    }

    const auto evalEnded = std::chrono::steady_clock::now();
    const auto ended = std::chrono::steady_clock::now();
    const double evalSeconds = std::chrono::duration<double>(evalEnded - evalStarted).count();
    const double totalSeconds = std::chrono::duration<double>(ended - started).count();

    std::ofstream output(outputPath);
    if (!output) {
      throw std::runtime_error("cannot write output json: " + outputPath.string());
    }
    output << "{\n";
    output << "  \"backend\": \"heir_generated_ckks_openfhe\",\n";
    output << "  \"scheme\": \"CKKS\",\n";
    output << "  \"codegen\": \"heir_generated_openfhe_cpp\",\n";
    output << "  \"generated_function\": \"dot_product\",\n";
    output << "  \"chunk_size\": @VECTOR_SIZE@,\n";
    output << "  \"context_setup_seconds\": " << contextSeconds << ",\n";
    output << "  \"keygen_configure_seconds\": " << keygenSeconds << ",\n";
    output << "  \"encryption_seconds\": " << encryptionSeconds << ",\n";
    output << "  \"encrypted_compute_seconds\": " << computeSeconds << ",\n";
    output << "  \"decryption_seconds\": " << decryptionSeconds << ",\n";
    output << "  \"eval_seconds_inside_runner\": " << evalSeconds << ",\n";
    output << "  \"total_seconds_inside_runner\": " << totalSeconds << ",\n";
    output << "  \"results\": [\n";
    for (std::size_t i = 0; i < results.size(); ++i) {
      const auto& item = results[i];
      output << "    {\"label\": \"" << jsonEscape(item.label) << "\", "
             << "\"count\": " << item.count << ", "
             << "\"default_count\": " << item.defaultCount << "}";
      output << (i + 1 == results.size() ? "\n" : ",\n");
    }
    output << "  ]\n";
    output << "}\n";

    std::cout << "HEIR-generated CKKS OpenFHE runner complete\n";
    std::cout << "Generated function: dot_product\n";
    std::cout << "Results: " << results.size() << "\n";
    std::cout << "Encrypted compute seconds: " << computeSeconds << "\n";
    std::cout << "Eval seconds: " << evalSeconds << "\n";
    std::cout << "Total seconds: " << totalSeconds << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "heir_generated_ckks_runner failed: " << error.what() << "\n";
    return 1;
  }
}
'''


CMAKE_TEMPLATE = r'''
cmake_minimum_required(VERSION 3.16.3)

project(home_credit_heir_generated_ckks LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(OpenFHE CONFIG REQUIRED)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${OpenFHE_CXX_FLAGS}")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} ${OpenFHE_EXE_LINKER_FLAGS}")

add_executable(
    home_credit_heir_generated_ckks_runner
    heir_output.cpp
    home_credit_heir_generated_ckks_runner.cpp
)

target_include_directories(
    home_credit_heir_generated_ckks_runner
    PRIVATE
    "${OpenFHE_INCLUDE}"
    "${OpenFHE_INCLUDE}/third-party/include"
    "${OpenFHE_INCLUDE}/core"
    "${OpenFHE_INCLUDE}/pke"
    "${OpenFHE_INCLUDE}/binfhe"
)

target_link_directories(
    home_credit_heir_generated_ckks_runner
    PRIVATE
    "${OpenFHE_LIBDIR}"
)

target_link_libraries(
    home_credit_heir_generated_ckks_runner
    PRIVATE
    ${OpenFHE_SHARED_LIBRARIES}
)

if(UNIX AND NOT APPLE)
  target_link_options(home_credit_heir_generated_ckks_runner PRIVATE -Wl,--no-as-needed)
endif()

set_target_properties(
    home_credit_heir_generated_ckks_runner
    PROPERTIES
    BUILD_RPATH "${OpenFHE_LIBDIR}"
)
'''


def run_command(command: list[str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)  # noqa: S603
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError(
            "command failed with exit code "
            f"{completed.returncode}: {' '.join(command)}\n{output}"
        )
    return time.perf_counter() - started, output


def resolve_executable(executable: str) -> str:
    if not executable:
        raise ValueError("missing executable path")
    if "/" in executable:
        path = Path(executable)
        if not path.exists():
            raise FileNotFoundError(f"executable does not exist: {executable}")
        return executable
    resolved = shutil.which(executable)
    if not resolved:
        raise FileNotFoundError(f"executable not found on PATH: {executable}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dot_product_ckks_mlir(vector_size: int) -> str:
    return f"""func.func @dot_product(
    %arg0: tensor<{vector_size}xf64> {{secret.secret}},
    %arg1: tensor<{vector_size}xf64> {{secret.secret}}
) -> f64 {{
  %c0 = arith.constant 0.0 : f64

  %result = affine.for %i = 0 to {vector_size}
      iter_args(%sum = %c0) -> (f64) {{
    %x = tensor.extract %arg0[%i] : tensor<{vector_size}xf64>
    %y = tensor.extract %arg1[%i] : tensor<{vector_size}xf64>
    %product = arith.mulf %x, %y : f64
    %next = arith.addf %sum, %product : f64
    affine.yield %next : f64
  }}

  return %result : f64
}}
"""


def generate_heir_sources(
    mlir_path: Path,
    work_dir: Path,
    heir_opt: str,
    heir_translate: str,
    heir_opt_pipeline: str,
) -> tuple[dict[str, float], str]:
    if not heir_opt_pipeline:
        raise ValueError(
            "--backend heir-generated-ckks requires --heir-opt-pipeline, "
            "or provide pre-generated CKKS heir_output.cpp/h with --heir-generated-dir"
        )
    heir_opt = resolve_executable(heir_opt)
    heir_translate = resolve_executable(heir_translate)

    timings: dict[str, float] = {}
    logs: list[str] = []
    lowered_mlir = work_dir / "output.mlir"
    timings["heir_opt_lower_seconds"], output = run_command(
        [heir_opt, str(mlir_path), f"--pass-pipeline={heir_opt_pipeline}", "-o", str(lowered_mlir)],
        work_dir,
    )
    logs.append(output)
    timings["heir_translate_cpp_seconds"], output = run_command(
        [heir_translate, "--emit-openfhe-pke", str(lowered_mlir), "-o", str(work_dir / "heir_output.cpp")],
        work_dir,
    )
    logs.append(output)
    timings["heir_translate_header_seconds"], output = run_command(
        [heir_translate, "--emit-openfhe-pke-header", str(lowered_mlir), "-o", str(work_dir / "heir_output.h")],
        work_dir,
    )
    logs.append(output)
    return timings, "\n".join(logs)


def copy_generated_sources(generated_dir: Path, work_dir: Path) -> None:
    for name in ("heir_output.cpp", "heir_output.h"):
        source = generated_dir / name
        if not source.exists():
            raise FileNotFoundError(f"missing HEIR generated source: {source}")
        shutil.copy2(source, work_dir / name)


def validate_generated_ckks(work_dir: Path) -> dict[str, Any]:
    cpp = work_dir / "heir_output.cpp"
    header = work_dir / "heir_output.h"
    text = cpp.read_text(encoding="utf-8", errors="replace") + "\n" + header.read_text(
        encoding="utf-8", errors="replace"
    )
    if "CryptoContextCKKSRNS" not in text and "CKKS" not in text:
        raise ValueError("HEIR generated source does not appear to use CKKS")
    forbidden = ["CryptoContextBGVRNS", "CryptoContextBFVRNS", "BinFHEContext"]
    found_forbidden = [item for item in forbidden if item in text]
    if found_forbidden:
        raise ValueError(f"HEIR generated source is not CKKS-only; found {found_forbidden}")
    required_symbols = [
        "dot_product__generate_crypto_context",
        "dot_product__configure_crypto_context",
        "dot_product__encrypt__arg0",
        "dot_product__encrypt__arg1",
        "dot_product__decrypt__result0",
        "dot_product",
    ]
    missing = [symbol for symbol in required_symbols if symbol not in text]
    if missing:
        raise ValueError(f"HEIR generated source/header missing expected symbols: {missing}")
    vector_match = re.search(r"tensor<([0-9]+)xf64>|std::vector<double>\s+\w+\(([0-9]+),\s*0", text)
    return {
        "heir_output_cpp": str(cpp),
        "heir_output_h": str(header),
        "heir_output_cpp_sha256": sha256_file(cpp),
        "heir_output_h_sha256": sha256_file(header),
        "detected_vector_size": next((int(group) for group in (vector_match.groups() if vector_match else []) if group), None),
        "required_symbols": required_symbols,
    }


def read_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_generated_ckks_backend(
    run_dir: Path,
    generated_dir: Path,
    openfhe_dir: str,
    vector_size: int,
    heir_opt: str,
    heir_translate: str,
    heir_opt_pipeline: str,
) -> tuple[dict[str, float], dict[str, Any], str]:
    # Commands run from the benchmark directory; use absolute paths so CMake
    # does not resolve a relative run path a second time.
    run_dir = run_dir.resolve()
    work_dir = run_dir / "heir_generated_ckks"
    build_dir = work_dir / "build"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    mlir_path = work_dir / f"home_credit_dot_product_ckks_{vector_size}.mlir"
    mlir_path.write_text(dot_product_ckks_mlir(vector_size), encoding="utf-8")

    timings: dict[str, float] = {}
    logs: list[str] = []
    if heir_opt_pipeline:
        generated_timings, output = generate_heir_sources(
            mlir_path=mlir_path,
            work_dir=work_dir,
            heir_opt=heir_opt,
            heir_translate=heir_translate,
            heir_opt_pipeline=heir_opt_pipeline,
        )
        timings.update(generated_timings)
        logs.append(output)
    else:
        copy_generated_sources(generated_dir, work_dir)

    proof = validate_generated_ckks(work_dir)
    if proof["detected_vector_size"] and int(proof["detected_vector_size"]) != vector_size:
        raise ValueError(
            f"generated CKKS vector size mismatch: requested {vector_size}, "
            f"detected {proof['detected_vector_size']}"
        )

    (work_dir / "home_credit_heir_generated_ckks_runner.cpp").write_text(
        RUNNER_CPP_TEMPLATE.replace("@VECTOR_SIZE@", str(vector_size)),
        encoding="utf-8",
    )
    (work_dir / "CMakeLists.txt").write_text(CMAKE_TEMPLATE, encoding="utf-8")

    configure_command = ["cmake", "-S", str(work_dir), "-B", str(build_dir)]
    if openfhe_dir:
        configure_command.append(f"-DOpenFHE_DIR={openfhe_dir}")

    timings["heir_generated_ckks_cmake_configure_seconds"], output = run_command(configure_command, run_dir)
    logs.append(output)
    timings["heir_generated_ckks_build_seconds"], output = run_command(
        ["cmake", "--build", str(build_dir), "--target", "home_credit_heir_generated_ckks_runner"],
        run_dir,
    )
    logs.append(output)

    result_path = run_dir / "heir_result.json"
    runner = build_dir / "home_credit_heir_generated_ckks_runner"
    timings["heir_generated_ckks_runner_seconds"], output = run_command(
        [str(runner), str(run_dir), str(run_dir / "tensor_manifest.csv"), str(result_path)],
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
