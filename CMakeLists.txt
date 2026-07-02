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

target_compile_options(server_numeric_summary PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
    ${OPENFHE_CXX_FLAGS_LIST}
)

target_include_directories(server_numeric_summary SYSTEM PRIVATE
    ${OPENMP_INCLUDES}
    ${OpenFHE_INCLUDE}
    ${OpenFHE_INCLUDE}/third-party/include
    ${OpenFHE_INCLUDE}/core
    ${OpenFHE_INCLUDE}/pke
    ${OpenFHE_INCLUDE}/binfhe
)

target_link_directories(server_numeric_summary PRIVATE
    ${OpenFHE_LIBDIR}
    ${OPENMP_LIBRARIES}
)

if(UNIX AND NOT APPLE)
    target_link_options(server_numeric_summary PRIVATE -Wl,--no-as-needed)
endif()

target_link_options(server_numeric_summary PRIVATE ${OPENFHE_EXE_LINKER_FLAGS_LIST})
target_link_libraries(server_numeric_summary PRIVATE ${OpenFHE_SHARED_LIBRARIES})
