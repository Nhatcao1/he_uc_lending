cmake_minimum_required(VERSION 3.16)

project(he_uc_lending LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenFHE CONFIG REQUIRED)

separate_arguments(OPENFHE_CXX_FLAGS_LIST NATIVE_COMMAND "${OpenFHE_CXX_FLAGS}")
separate_arguments(OPENFHE_EXE_LINKER_FLAGS_LIST NATIVE_COMMAND "${OpenFHE_EXE_LINKER_FLAGS}")

add_executable(server_numeric_summary
    code/server/numeric_summary/server_numeric_summary.cpp
)

add_executable(client_binfhe_keygen
    code/client/binfhe_outliers/client_binfhe_keygen.cpp
)

add_executable(client_binfhe_encrypt_outliers
    code/client/binfhe_outliers/client_binfhe_encrypt_outliers.cpp
)

add_executable(client_binfhe_decrypt_outliers
    code/client/binfhe_outliers/client_binfhe_decrypt_outliers.cpp
)

add_executable(server_binfhe_outlier_flags
    code/server/binfhe_outliers/server_binfhe_outlier_flags.cpp
)

set(HE_UC_OPENFHE_TARGETS
    server_numeric_summary
    client_binfhe_keygen
    client_binfhe_encrypt_outliers
    client_binfhe_decrypt_outliers
    server_binfhe_outlier_flags
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
