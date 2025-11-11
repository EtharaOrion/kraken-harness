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

import datetime
import json
import sys

import requests
from bs4 import BeautifulSoup

sys.path.append("../../harness")
from utils import get_instances

PATH_TASKS_PYDICOM = "<path to pydicom task instances>"
PATH_TASKS_PYDICOM_V = "<path to pydicom task instances with versions>"

data_tasks = get_instances(PATH_TASKS_PYDICOM)
resp = requests.get("https://pydicom.github.io/pydicom/dev/faq/index.html")
soup = BeautifulSoup(resp.text, "html.parser")
release_table = soup.find("table", {"class": "docutils align-default"})

times = []
for row in release_table.find_all("tr"):
    cells = row.find_all("td")
    if len(cells) == 3:
        version = cells[0].text.strip()
        date = cells[1].text.strip().strip("~")
        if date == "Jan 2024":
            date = "2024-01-01"
        else:
            date = datetime.strptime(date, "%B %Y").strftime("%Y-%m-%d")
        python_versions = max(cells[2].text.strip().split(", "))
        times.append((date, version))

times = sorted(times, key=lambda x: x[0], reverse=True)
for task in data_tasks:
    created_at = task["created_at"].split("T")[0]
    found = False
    for t in times:
        if t[0] < created_at:
            task["version"] = t[1]
            found = True
            break
    if not found:
        task["version"] = times[-1][1]

with open(PATH_TASKS_PYDICOM_V, "w") as f:
    json.dump(data_tasks, fp=f)
