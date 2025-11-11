#!/bin/bash

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


ROOT_DIR=data

export extract_archive
extract_archive() {
    archive="$1"
    dir="$(dirname "$archive")"
    basename=$(basename "$archive" .tar)
    if [ -d "$dir/$basename" ]; then
        echo "Directory $dir/$basename already exists, skipping."
        return
    fi
    echo "Extracting $archive in $dir"
    case "$archive" in
        *.tar)    tar -xf "$archive" -C "$dir" ;;
    esac
}

export -f extract_archive

find "$ROOT_DIR" -type f \( -name "*.tar" -o -name "*.tar.gz" -o -name "*.tgz" \) \
    | grep "pandas" | parallel --jobs 8 extract_archive {}