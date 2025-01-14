import argparse
import csv
import logging
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger("wdb")
DEFAULT_OUTPUT_FILE = "./outputs/windows-desktop-builds.csv"


def get_win_build_info(os_version, url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    # Scrape the release names
    release_names = []
    for version in soup.find_all("strong"):
        if (
            "Version" in version.contents[0]
            and version.contents[0] not in release_names
        ):
            release_names.append(version.contents[0])

    # Scrape the release data and match them with their corresponding release names
    i = 0
    release_list = []
    tables = soup.find_all("table", class_="cells-centered")

    for table in tables:
        if table.find_all(string="Long-Term Servicing Channel (LTSC)"):
            continue

        rows = table.find_all("tr")

        for row in rows:
            row_dict = {
                "os_major_version": os_version,
                "feature_release_version": release_names[i].split(" ")[1],
                "release_full_name": release_names[i],
            }
            cols = row.find_all("td")
            for data in cols:
                if re.match("\\d+-\\d+-\\d+", data.text):
                    row_dict["release_date"] = data.text
                elif re.match("\\d+\\.\\d+", data.text):
                    row_dict["build_number"] = data.text
                elif re.match("KB\\d+", data.text):
                    row_dict["kb"] = data.text

            if "release_date" in row_dict:
                release_list.append(row_dict)

        i += 1

    return release_list


def export_data(output_file, all_builds):
    export_file = Path(output_file).absolute()

    (export_file.parent).mkdir(parents=True, exist_ok=True)

    with open(export_file, "w", newline="") as ef:
        writer = csv.writer(ef)
        csv_header = list(all_builds[0].keys())
        writer.writerow(csv_header)

        for build in all_builds:
            csv_row: list = build.values()
            writer.writerow(csv_row)


def get_config_args():
    # Define the parser
    parser = argparse.ArgumentParser(description="Microsoft Windows Desktop Builds")
    parser.add_argument(
        "--output-file",
        action="store",
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help="Where to output the file",
    )
    parser.add_argument(
        "--debug-logging",
        action="store_true",
        help="Enables Debug Level Logging",
    )
    parser.add_argument(
        "--info-logging",
        action="store_true",
        help="Enables Info Level Logging. Superseded by debug-logging",
    )
    args = parser.parse_args()

    return args


def configure_logging(debug_logging: bool = False, info_logging: bool = False):
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    if debug_logging:
        LOGGER.setLevel(logging.DEBUG)
    elif info_logging:
        LOGGER.setLevel(logging.INFO)
    else:
        LOGGER.setLevel(logging.NOTSET)
    log_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    ch.setFormatter(log_formatter)

    # make sure all other log handlers are removed before adding it back
    for handler in LOGGER.handlers:
        LOGGER.removeHandler(handler)
    LOGGER.addHandler(ch)


def main():
    assert sys.version_info >= (3, 12)

    config_args = get_config_args()

    configure_logging(
        debug_logging=config_args.debug_logging, info_logging=config_args.info_logging
    )

    all_builds = []

    win10_builds = get_win_build_info(
        "Windows 10",
        "https://learn.microsoft.com/en-us/windows/release-health/release-information",
    )

    all_builds.extend(win10_builds)

    win11_builds = get_win_build_info(
        "Windows 11",
        "https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information",
    )
    all_builds.extend(win11_builds)

    for build in all_builds:
        LOGGER.info(build)

    output_file = (
        DEFAULT_OUTPUT_FILE
        if DEFAULT_OUTPUT_FILE == config_args.output_file
        else config_args.output_file
    )

    export_data(output_file, all_builds)


if __name__ == "__main__":
    main()
