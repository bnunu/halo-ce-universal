cmake_minimum_required(VERSION 3.28)
project(HaloIOS LANGUAGES C CXX OBJC ASM)
get_filename_component(HALO_ROOT "../.." ABSOLUTE)
set(HALO_BUILD "${HALO_ROOT}/build/ios")
set(HALO_BUNDLE_IDENTIFIER "local.halo.ce-universal.ios" CACHE STRING "Unique iOS app bundle identifier")
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)
set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
set(SDL_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory("${HALO_ROOT}/build/android/third_party/SDL3" "sdl")
file(GLOB HOST_SOURCES "${HALO_ROOT}/port/macos/host/*.c")
list(FILTER HOST_SOURCES EXCLUDE REGEX "host_(main|loader)\\.c$")
add_executable(Halo MACOSX_BUNDLE ${HOST_SOURCES} host/host_loader.c host/host_main.m host/host_controls.m
    "${HALO_ROOT}/port/macos/host/entry.s" "${HALO_BUILD}/host/host_import_table.c"
    "${HALO_BUILD}/embed/guest_image.s")
target_sources(Halo PRIVATE Assets.xcassets)
set_source_files_properties(Assets.xcassets PROPERTIES MACOSX_PACKAGE_LOCATION Resources)
target_compile_definitions(Halo PRIVATE HALO_IOS=1 HALO_MACOS=1 _DARWIN_C_SOURCE=1)
target_compile_options(Halo PRIVATE -O2 -g -Wall -Wextra -Wno-unused-parameter -Wno-unused-function
    "$<$<COMPILE_LANGUAGE:OBJC>:-fobjc-arc>")
target_include_directories(Halo PRIVATE "${HALO_ROOT}" "${HALO_ROOT}/port/macos/host"
    "${HALO_ROOT}/port/android/include" "${HALO_ROOT}/port/linux/src"
    "${HALO_ROOT}/build/macos/toolchain/gl" "${HALO_BUILD}/embed")
if(CMAKE_OSX_SYSROOT MATCHES "simulator")
    set(ANGLE_PLATFORM ios-arm64-simulator)
else()
    set(ANGLE_PLATFORM ios-arm64)
endif()
foreach(NAME EGL GLESv2)
    set(FRAMEWORK "${HALO_ROOT}/build/macos/angle/dist/${NAME}.xcframework/${ANGLE_PLATFORM}/lib${NAME}.framework")
    list(APPEND ANGLE_FRAMEWORKS "${FRAMEWORK}")
    target_link_libraries(Halo PRIVATE "${FRAMEWORK}")
endforeach()
target_link_libraries(Halo PRIVATE SDL3::SDL3-static "-framework Foundation" "-framework UIKit" "-framework GameController")
set_target_properties(Halo PROPERTIES
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
    XCODE_ATTRIBUTE_PRODUCT_BUNDLE_IDENTIFIER "${HALO_BUNDLE_IDENTIFIER}"
    XCODE_ATTRIBUTE_ASSETCATALOG_COMPILER_APPICON_NAME "AppIcon"
    XCODE_ATTRIBUTE_TARGETED_DEVICE_FAMILY "1"
    XCODE_ATTRIBUTE_CODE_SIGN_STYLE "Automatic"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${CMAKE_CURRENT_SOURCE_DIR}/Halo.entitlements"
    XCODE_ATTRIBUTE_ENABLE_HARDENED_RUNTIME NO
    XCODE_EMBED_FRAMEWORKS "${ANGLE_FRAMEWORKS}"
    XCODE_EMBED_FRAMEWORKS_CODE_SIGN_ON_COPY YES
    XCODE_EMBED_FRAMEWORKS_REMOVE_HEADERS_ON_COPY YES
    XCODE_ATTRIBUTE_LD_RUNPATH_SEARCH_PATHS "@executable_path/Frameworks")
if(HALO_DEVELOPMENT_TEAM)
    set_target_properties(Halo PROPERTIES XCODE_ATTRIBUTE_DEVELOPMENT_TEAM "${HALO_DEVELOPMENT_TEAM}")
endif()
if(HALO_BUNDLE_MAPS)
    file(GLOB HALO_MAPS "${HALO_ROOT}/assets/maps/*")
    target_sources(Halo PRIVATE ${HALO_MAPS})
    set_source_files_properties(${HALO_MAPS} PROPERTIES MACOSX_PACKAGE_LOCATION "GameData/maps")
endif()
