"""OpenFHE runner adapter for HEIR-generated dot_product kernel.

The synced HEIR sample generates a BGV/OpenFHE function:

    dot_product(arg0, arg1) = sum(arg0 * arg1)

for static `tensor<8xi16>` inputs. This adapter reuses that generated kernel as
the first real Home Credit HEIR-backed computation by chunking prepared 0/1
masks into blocks of 8.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


RUNNER_CPP = r'''
#include <cstdint>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
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

std::vector<int16_t> readVector(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open vector: " + path.string());
  }
  std::string line;
  std::getline(input, line);  // header
  std::vector<int16_t> values;
  while (std::getline(input, line)) {
    const auto text = trim(line);
    if (text.empty()) {
      continue;
    }
    const double parsed = std::stod(splitCsvLine(text)[0]);
    values.push_back(static_cast<int16_t>(parsed >= 0.5 ? 1 : 0));
  }
  return values;
}

int64_t encryptedDotSum(
    CryptoContextT cryptoContext,
    PublicKeyT publicKey,
    PrivateKeyT secretKey,
    const std::vector<int16_t>& left,
    const std::vector<int16_t>& right) {
  if (left.size() != right.size()) {
    throw std::runtime_error("vector size mismatch");
  }
  int64_t total = 0;
  for (std::size_t offset = 0; offset < left.size(); offset += 8) {
    std::vector<int16_t> chunkLeft(8, 0);
    std::vector<int16_t> chunkRight(8, 0);
    for (std::size_t i = 0; i < 8 && offset + i < left.size(); ++i) {
      chunkLeft[i] = left[offset + i];
      chunkRight[i] = right[offset + i];
    }
    auto encryptedLeft = dot_product__encrypt__arg0(cryptoContext, chunkLeft, publicKey);
    auto encryptedRight = dot_product__encrypt__arg1(cryptoContext, chunkRight, publicKey);
    auto encryptedResult = dot_product(cryptoContext, encryptedLeft, encryptedRight);
    total += dot_product__decrypt__result0(cryptoContext, encryptedResult, secretKey);
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
    std::vector<int16_t> oneMask(targetMask.size(), 1);

    auto cryptoContext = dot_product__generate_crypto_context();
    auto keyPair = cryptoContext->KeyGen();
    cryptoContext = dot_product__configure_crypto_context(cryptoContext, keyPair.secretKey);

    const auto evalStarted = std::chrono::steady_clock::now();

    struct Result {
      std::string label;
      int64_t count;
      int64_t defaultCount;
    };
    std::vector<Result> results;
    results.reserve(groupRows.size());
    for (const auto& groupRow : groupRows) {
      auto groupMask = readVector(runDir / groupRow.file);
      const int64_t count = encryptedDotSum(cryptoContext, keyPair.publicKey, keyPair.secretKey, groupMask, oneMask);
      const int64_t defaultCount = encryptedDotSum(cryptoContext, keyPair.publicKey, keyPair.secretKey, groupMask, targetMask);
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
    output << "  \"backend\": \"heir_openfhe_dot_product\",\n";
    output << "  \"chunk_size\": 8,\n";
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

    std::cout << "HEIR OpenFHE dot-product runner complete\n";
    std::cout << "Results: " << results.size() << "\n";
    std::cout << "Eval seconds: " << evalSeconds << "\n";
    std::cout << "Total seconds: " << totalSeconds << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "heir_openfhe_dot_runner failed: " << error.what() << "\n";
    return 1;
  }
}
'''


CMAKE_TEMPLATE = r'''
cmake_minimum_required(VERSION 3.16.3)

project(home_credit_heir_openfhe_dot LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(OpenFHE CONFIG REQUIRED)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${OpenFHE_CXX_FLAGS}")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} ${OpenFHE_EXE_LINKER_FLAGS}")

add_executable(
    home_credit_heir_dot_runner
    heir_output.cpp
    home_credit_heir_dot_runner.cpp
)

target_include_directories(
    home_credit_heir_dot_runner
    PRIVATE
    "${OpenFHE_INCLUDE}"
    "${OpenFHE_INCLUDE}/third-party/include"
    "${OpenFHE_INCLUDE}/core"
    "${OpenFHE_INCLUDE}/pke"
    "${OpenFHE_INCLUDE}/binfhe"
)

target_link_directories(
    home_credit_heir_dot_runner
    PRIVATE
    "${OpenFHE_LIBDIR}"
)

target_link_libraries(
    home_credit_heir_dot_runner
    PRIVATE
    ${OpenFHE_SHARED_LIBRARIES}
)

if(UNIX AND NOT APPLE)
  target_link_options(home_credit_heir_dot_runner PRIVATE -Wl,--no-as-needed)
endif()

set_target_properties(
    home_credit_heir_dot_runner
    PROPERTIES
    BUILD_RPATH "${OpenFHE_LIBDIR}"
)
'''


def run_command(command: list[str], cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)  # noqa: S603
    return time.perf_counter() - started, completed.stdout + completed.stderr


def copy_generated_heir_sources(generated_dir: Path, work_dir: Path) -> None:
    for name in ("heir_output.cpp", "heir_output.h"):
        source = generated_dir / name
        if not source.exists():
            raise FileNotFoundError(f"missing HEIR generated source: {source}")
        shutil.copy2(source, work_dir / name)


def read_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_openfhe_dot_backend(
    run_dir: Path,
    generated_dir: Path,
    openfhe_dir: str,
) -> tuple[dict[str, float], dict[str, Any], str]:
    work_dir = run_dir / "heir_openfhe_dot"
    build_dir = work_dir / "build"
    work_dir.mkdir(parents=True, exist_ok=True)
    copy_generated_heir_sources(generated_dir, work_dir)
    (work_dir / "home_credit_heir_dot_runner.cpp").write_text(RUNNER_CPP, encoding="utf-8")
    (work_dir / "CMakeLists.txt").write_text(CMAKE_TEMPLATE, encoding="utf-8")

    configure_command = ["cmake", "-S", str(work_dir), "-B", str(build_dir)]
    if openfhe_dir:
        configure_command.append(f"-DOpenFHE_DIR={openfhe_dir}")

    timings: dict[str, float] = {}
    logs: list[str] = []
    timings["heir_openfhe_cmake_configure_seconds"], output = run_command(configure_command, run_dir)
    logs.append(output)
    timings["heir_openfhe_build_seconds"], output = run_command(
        ["cmake", "--build", str(build_dir), "--target", "home_credit_heir_dot_runner"],
        run_dir,
    )
    logs.append(output)

    result_path = run_dir / "heir_result.json"
    runner = build_dir / "home_credit_heir_dot_runner"
    timings["heir_openfhe_runner_seconds"], output = run_command(
        [str(runner), str(run_dir), str(run_dir / "tensor_manifest.csv"), str(result_path)],
        run_dir,
    )
    logs.append(output)
    return timings, read_result(result_path), "\n".join(logs)
