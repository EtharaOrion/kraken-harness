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

"""Version detection constants for TypeScript repositories.

Mirrors swefficiency.versioning.constants but for TypeScript projects.
Version metadata in TypeScript libraries is much more uniform than C++ —
the canonical source is the top-level package.json "version" field. When
that fails (monorepos, prerelease branches, missing manifest at the probed
ref), we fall back to the latest matching git tag using the same semver
heuristic as the C++ pipeline.
"""

NS_VERSION_TS = "version_ts"
NS_REPO_SPECS_TS = "repo_specs_ts"

PACKAGE_JSON_VERSION_KEY = "version"

# Ordered list of git-tag patterns probed as a fallback when no
# package.json (or matching version field) is found at the ref. Mirrors
# the cpp pipeline's git-tag fallback heuristic. First match wins.
FALLBACK_GIT_TAG_PATTERNS_TS = [
    # Standard semver tags: v1.2.3, 1.2.3, v1.2.3-rc.1
    r"^v?(\d+\.\d+\.\d+(?:[-+][\w.]+)?)$",
    # Two-component versions: v1.2, 1.2
    r"^v?(\d+\.\d+)$",
    # Monorepo-style tags: pkg@1.2.3, @scope/pkg@1.2.3
    r"@v?(\d+\.\d+\.\d+(?:[-+][\w.]+)?)$",
]


# Constants - Task Instance Version File (TypeScript).
#
# Each entry maps a GitHub repo to an ordered list of candidate paths,
# probed in order; first match wins. For TypeScript the canonical version
# source is the top-level package.json — monorepos may additionally
# expose a workspace-root manifest with the umbrella version.
MAP_REPO_TO_VERSION_PATHS_TS = {
    "lodash/lodash": [
        "package.json",
    ],
    "axios/axios": [
        "package.json",
    ],
    "expressjs/express": [
        "package.json",
    ],
    "prettier/prettier": [
        "package.json",
    ],
    "vitest-dev/vitest": [
        "package.json",
    ],
    "microsoft/TypeScript": [
        "package.json",
    ],
}

# Fallback candidate paths probed for unknown repos in the TS pipeline.
# Ordered most-canonical first.
_FALLBACK_VERSION_PATHS_TS = [
    "package.json",
    "VERSION",
    "VERSION.txt",
    "version.txt",
    "lerna.json",
    "pnpm-workspace.yaml",
]


# Constants - Task Instance Version Regex Pattern (TypeScript).
#
# For each path family we maintain a list of regex patterns; first match
# wins per file. Patterns must use a single capture group containing the
# version string. The package.json "version" field is canonical for the
# TypeScript ecosystem.
MAP_REPO_TO_VERSION_PATTERNS_TS = {
    k: [
        # package.json / lerna.json: "version": "x.y.z".
        r'"version"\s*:\s*"([^"]+)"',
        # TypeScript source: export const version = "x.y.z";
        r'export\s+const\s+version\s*=\s*["\']([^"\']+)["\']',
        # TypeScript namespace constant: const VERSION = "x.y.z";
        r'const\s+VERSION\s*=\s*["\']([^"\']+)["\']',
    ]
    for k in [
        "lodash/lodash",
        "axios/axios",
        "expressjs/express",
        "prettier/prettier",
        "vitest-dev/vitest",
        "microsoft/TypeScript",
    ]
}


# Generic fallback patterns used when neither MAP_REPO_TO_VERSION_PATHS_TS
# nor MAP_REPO_TO_VERSION_PATTERNS_TS yields a hit. Caller (get_versions_ts)
# should iterate these against any file content it has, in this order.
GENERIC_VERSION_PATTERNS_TS = [
    # JSON manifests (package.json, lerna.json, etc.)
    r'"version"\s*:\s*"([^"]+)"',
    # Plain VERSION/VERSION.txt: bare semver on first line.
    r"^v?(\d+\.\d+(?:\.\d+)?)\s*$",
    # TypeScript export const version = "x.y.z";
    r'export\s+const\s+version\s*=\s*["\']([^"\']+)["\']',
    # TypeScript const VERSION = "x.y.z";
    r'const\s+VERSION\s*=\s*["\']([^"\']+)["\']',
]
