cmake_minimum_required(VERSION 3.16)

project(he_uc_credit LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenFHE CONFIG REQUIRED)

separate_arguments(OPENFHE_CXX_FLAGS_LIST NATIVE_COMMAND "${OpenFHE_CXX_FLAGS}")
separate_arguments(OPENFHE_EXE_LINKER_FLAGS_LIST NATIVE_COMMAND "${OpenFHE_EXE_LINKER_FLAGS}")

add_executable(server_numeric_summary
    code/server/numeric_summary/server_numeric_summary.cpp
)

add_executable(server_home_credit_aggregate
    code/server/home_credit_aggregate/server_home_credit_aggregate.cpp
)

add_executable(server_home_credit_token_join_aggregate
    code/server/home_credit_aggregate/server_home_credit_token_join_aggregate.cpp
)

add_executable(server_home_credit_fhew_match
    code/server/fhew_match/server_home_credit_fhew_match.cpp
)

add_executable(server_home_credit_fhew_amt_bins
    code/server/fhew_amt_bins/server_home_credit_fhew_amt_bins.cpp
)

add_executable(server_linear_score
    code/server/linear_score/server_linear_score.cpp
)

add_executable(encrypt_home_credit_payload
    code/client/ckks_tools/encrypt_home_credit_payload.cpp
)

add_executable(decrypt_ckks_results
    code/client/ckks_tools/decrypt_ckks_results.cpp
)

add_executable(encrypt_home_credit_fhew_match
    code/client/fhew_tools/encrypt_home_credit_fhew_match.cpp
)

add_executable(decrypt_home_credit_fhew_match
    code/client/fhew_tools/decrypt_home_credit_fhew_match.cpp
)

add_executable(encrypt_home_credit_fhew_amt
    code/client/fhew_tools/encrypt_home_credit_fhew_amt.cpp
)

add_executable(decrypt_home_credit_fhew_amt_bins
    code/client/fhew_tools/decrypt_home_credit_fhew_amt_bins.cpp
)

set(HE_UC_OPENFHE_TARGETS
    server_numeric_summary
    server_home_credit_aggregate
    server_home_credit_token_join_aggregate
    server_home_credit_fhew_match
    server_home_credit_fhew_amt_bins
    server_linear_score
    encrypt_home_credit_payload
    decrypt_ckks_results
    encrypt_home_credit_fhew_match
    decrypt_home_credit_fhew_match
    encrypt_home_credit_fhew_amt
    decrypt_home_credit_fhew_amt_bins
)

foreach(target_name IN LISTS HE_UC_OPENFHE_TARGETS)
    target_compile_options(${target_name} PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
        ${OPENFHE_CXX_FLAGS_LIST}
    )

    target_include_directories(${target_name} SYSTEM PRIVATE
        ${OPENMP_INCLUDES}
        ${OpenFHE_INCLUDE}
        ${OpenFHE_INCLUDE}/third-party/include
        ${OpenFHE_INCLUDE}/core
        ${OpenFHE_INCLUDE}/pke
        ${OpenFHE_INCLUDE}/binfhe
    )

    target_link_directories(${target_name} PRIVATE
        ${OpenFHE_LIBDIR}
        ${OPENMP_LIBRARIES}
    )

    if(UNIX AND NOT APPLE)
        target_link_options(${target_name} PRIVATE -Wl,--no-as-needed)
    endif()

    target_link_options(${target_name} PRIVATE ${OPENFHE_EXE_LINKER_FLAGS_LIST})
    target_link_libraries(${target_name} PRIVATE ${OpenFHE_SHARED_LIBRARIES})
endforeach()
