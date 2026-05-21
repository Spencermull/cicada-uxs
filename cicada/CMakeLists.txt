cmake_minimum_required(VERSION 3.20)
project(cicada LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(PkgConfig REQUIRED)
pkg_check_modules(ZeroMQ REQUIRED libzmq)

set(MAVLINK_INCLUDE_DIR  ${CMAKE_CURRENT_SOURCE_DIR}/third_party/mavlink)
set(CPPZMQ_INCLUDE_DIR   ${CMAKE_CURRENT_SOURCE_DIR}/third_party/cppzmq)
set(JSON_INCLUDE_DIR     ${CMAKE_CURRENT_SOURCE_DIR}/third_party)

add_executable(cicada src/main.cpp)

target_include_directories(cicada
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${MAVLINK_INCLUDE_DIR}
        ${CPPZMQ_INCLUDE_DIR}
        ${JSON_INCLUDE_DIR}
        ${ZeroMQ_INCLUDE_DIRS}
)

target_link_libraries(cicada
    PRIVATE
        ${ZeroMQ_LIBRARIES}
)

target_compile_options(cicada
    PRIVATE
        ${ZeroMQ_CFLAGS_OTHER}
)
