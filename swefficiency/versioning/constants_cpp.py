# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Version detection constants for C++ repositories.

Mirrors swefficiency.versioning.constants but for C++ projects. Version
metadata in C++ libraries lives in a much more varied set of locations than
Python — most commonly in CMakeLists.txt (project(... VERSION x.y.z)),
generated version.h headers, or package manager manifests (vcpkg.json,
package.json). When all those fail we fall back to the latest matching git
tag.
"""

# Constants - Task Instance Version File (C++).
#
# Each entry maps a GitHub repo to an ordered list of candidate paths,
# probed in order; first match wins. Use {project} as a placeholder for the
# repo's leaf name when the path differs per-repo (callers may .format()
# it; we keep literal values here for the curated set since CMake's
# project(<name>) macro doesn't always match the GitHub repo name).
MAP_REPO_TO_VERSION_PATHS_CPP = {
    # fmtlib/fmt: project(FMT VERSION x.y.z) in root CMakeLists.txt.
    "fmtlib/fmt": [
        "CMakeLists.txt",
        "include/fmt/base.h",
        "include/fmt/core.h",
        "include/fmt/format.h",
    ],
    # gabime/spdlog: project(spdlog VERSION x.y.z) + version.h macros.
    "gabime/spdlog": [
        "CMakeLists.txt",
        "include/spdlog/version.h",
    ],
    # nlohmann/json: project(nlohmann_json VERSION x.y.z); the single-header
    # also contains NLOHMANN_JSON_VERSION_{MAJOR,MINOR,PATCH} macros.
    "nlohmann/json": [
        "CMakeLists.txt",
        "include/nlohmann/json.hpp",
        "single_include/nlohmann/json.hpp",
    ],
    # abseil/abseil-cpp: no project(... VERSION ...) line — version lives in
    # LTS branch names (e.g. lts_2024_01_16). Fall back to git tag.
    "abseil/abseil-cpp": [
        "CMakeLists.txt",
        "absl/base/options.h",
    ],
    # ericniebler/range-v3: project(range-v3 VERSION x.y.z).
    "ericniebler/range-v3": [
        "CMakeLists.txt",
        "include/range/v3/version.hpp",
    ],
    # eigen-mirror/eigen: project(Eigen3 VERSION x.y.z) + Eigen/src/Core/util/Macros.h.
    "eigen-mirror/eigen": [
        "CMakeLists.txt",
        "Eigen/src/Core/util/Macros.h",
    ],
}

# Fallback candidate paths probed for unknown repos in the C++ pipeline.
# Ordered most-canonical first.
_FALLBACK_VERSION_PATHS_CPP = [
    "CMakeLists.txt",
    "VERSION",
    "VERSION.txt",
    "version.txt",
    "vcpkg.json",
    "package.json",
    "conanfile.py",
    "conanfile.txt",
]


# Constants - Task Instance Version Regex Pattern (C++).
#
# For each path family we maintain a list of regex patterns; first match
# wins per file. Patterns must use a single capture group containing the
# version string. Multi-line group concatenation (as in networkx) is not
# needed for our C++ shortlist — the CMake project() macro is canonical.
MAP_REPO_TO_VERSION_PATTERNS_CPP = {
    k: [
        # CMake: project(<name> [LANGUAGES ...] VERSION x.y.z) — case-insensitive.
        r"project\s*\([^)]*?\bVERSION\s+(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)",
        # Generated version headers: #define FMT_VERSION 100100  (packed int).
        r"#\s*define\s+\w*VERSION\s+(\d+)",
        # version.h with separate major/minor/patch macros.
        r"#\s*define\s+\w*VERSION_MAJOR\s+(\d+)",
        # vcpkg.json / package.json: "version": "x.y.z".
        r'"version"\s*:\s*"([^"]+)"',
        # Eigen-style macros.
        r"#\s*define\s+EIGEN_WORLD_VERSION\s+(\d+)",
        # range-v3-style namespace constexpr.
        r"constexpr\s+\w+\s+VERSION\s*=\s*\"([^\"]+)\"",
    ]
    for k in [
        "fmtlib/fmt",
        "gabime/spdlog",
        "nlohmann/json",
        "abseil/abseil-cpp",
        "ericniebler/range-v3",
        "eigen-mirror/eigen",
    ]
}


# Generic fallback patterns used when neither MAP_REPO_TO_VERSION_PATHS_CPP
# nor MAP_REPO_TO_VERSION_PATTERNS_CPP yields a hit. Caller (get_versions_cpp)
# should iterate these against any file content it has, in this order.
GENERIC_VERSION_PATTERNS_CPP = [
    # CMake project(... VERSION x.y.z)
    r"project\s*\([^)]*?\bVERSION\s+(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)",
    # JSON manifests
    r'"version"\s*:\s*"([^"]+)"',
    # Plain VERSION/VERSION.txt: bare semver on first line.
    r"^v?(\d+\.\d+(?:\.\d+)?)\s*$",
    # Header macros: #define FOO_VERSION 100100, FOO_VERSION_MAJOR 1, etc.
    r"#\s*define\s+\w*VERSION_MAJOR\s+(\d+)",
    r"#\s*define\s+\w*VERSION\s+\"?(\d+\.\d+(?:\.\d+)?)\"?",
    # Git tag-ish constexpr or constants.
    r"constexpr\s+\w+\s+VERSION\s*=\s*\"([^\"]+)\"",
]
