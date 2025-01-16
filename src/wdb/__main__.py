import argparse
import csv
import itertools
import logging
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from shutil import copy2, move

import requests
import yaml
from bs4 import BeautifulSoup
from packaging.version import Version

LOGGER = logging.getLogger("wdb")

DEFAULT_SYNCRO_FILE = "./inputs/syncro-data.csv"
DEFAULT_CONFIG_LOCATION = Path(__file__).parent.joinpath("data/config/config.yaml")


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


def export_data(output_path, output_data):
    output_path = Path(output_path).expanduser()

    output_path.mkdir(parents=True, exist_ok=True)

    spreadsheet = output_path / "desktop-build-statistics.xlsx"
    one_month_file = output_path / "one-month-statistics.csv"
    two_month_file = output_path / "two-month-statistics.csv"
    three_month_file = output_path / "three-month-statistics.csv"

    if not spreadsheet.is_file():
        spreadsheet_source = Path(__file__).parent.joinpath(
            "data/desktop-build-statistics.xlsx"
        )
        copy2(spreadsheet_source, output_path)

    if three_month_file.is_file():
        os.remove(three_month_file)
    if two_month_file.is_file():
        move(two_month_file, three_month_file)
    if one_month_file.is_file():
        move(one_month_file, two_month_file)

    csv_categories: list = []
    for os_name in output_data.keys():
        for release in output_data[os_name].keys():
            csv_header = ["Operating System", "Release"]
            for category in output_data[os_name][release].keys():
                csv_categories.append(category)
            break
        break
    csv_header.extend(csv_categories)

    with open(one_month_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(csv_header)
        for os_name in output_data.keys():
            for release in output_data[os_name].keys():
                csv_entry: list = [os_name, release]
                for category in csv_categories:
                    csv_entry.append(output_data[os_name][release][category])
                writer.writerow(csv_entry)


def get_config_args():
    # Define the parser
    parser = argparse.ArgumentParser(description="Microsoft Windows Desktop Builds")
    parser.add_argument(
        "--output-path",
        action="store",
        type=str,
        default=Path("/") / "wdb",
        help="Where to put output files",
    )
    parser.add_argument(
        "--syncro-input-file",
        action="store",
        type=str,
        default=DEFAULT_SYNCRO_FILE,
        help="Where to import Syncro data from",
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
    parser.add_argument(
        "--config-file",
        action="store",
        type=str,
        default=DEFAULT_CONFIG_LOCATION,
        help="Path to Configuration File",
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


def windows_builds(config_settings):
    all_builds = []

    os_checks = config_settings["os-checks"]

    for os_name in os_checks:
        os_builds = get_win_build_info(os_name, os_checks[os_name])

        all_builds.extend(os_builds)

    for build in all_builds:
        LOGGER.info(build)

    return all_builds


def syncro_report(import_file_path):
    import_file = Path(import_file_path).absolute()
    with open(import_file, "r") as file:
        csv_reader = csv.reader(file)

        syncro_data: list = []
        syncro_data_header: list = []

        for row in csv_reader:
            syncro_data_entry: dict = {}
            if len(syncro_data_header) == 0:
                syncro_data_header = row
                continue

            syncro_data_entry = dict(zip(syncro_data_header, row))

            syncro_data.append(syncro_data_entry)
    for sd in syncro_data:
        LOGGER.info(sd)
    return syncro_data


def map_syncro_to_microsoft(syncro_data, ms_build_data):
    build_map: dict = {}

    for i, j in itertools.product(syncro_data, ms_build_data):
        if i["OS Build"] == j["build_number"]:
            if i["OS Build"] in build_map:
                build_map[i["OS Build"]] += 1
            else:
                build_map[i["OS Build"]] = 1

    build_map = dict(sorted(build_map.items(), reverse=True))

    return build_map


def map_builds_to_os(ms_build_data):
    build_map: dict = {}

    for d in ms_build_data:
        if d["os_major_version"] not in build_map:
            build_entry: list = [d["build_number"]]
            feature_entry: dict = {d["feature_release_version"]: build_entry}
            build_map[d["os_major_version"]] = feature_entry
        elif d["feature_release_version"] not in build_map[d["os_major_version"]]:
            build_entry: list = [d["build_number"]]
            feature_entry: dict = {d["feature_release_version"]: build_entry}
            feature_entry = dict(sorted(feature_entry.items(), reverse=True))
            build_map[d["os_major_version"]][d["feature_release_version"]] = build_entry
        elif (
            d["build_number"]
            not in build_map[d["os_major_version"]][d["feature_release_version"]]
        ):
            existing_build_entry = build_map[d["os_major_version"]][
                d["feature_release_version"]
            ]
            build_entry: list = [d["build_number"]]
            build_entry.extend(existing_build_entry)
            build_entry = list(sorted(build_entry, reverse=True, key=Version))
            feature_entry: dict = {d["feature_release_version"]: build_entry}
            build_map[d["os_major_version"]][d["feature_release_version"]] = build_entry

    build_map = dict(sorted(build_map.items(), reverse=True))

    return build_map


def map_allowed_builds(
    os_build_map,
    current_build_count=3,
    aging_build_count=2,
):
    current_builds: list = []
    aging_builds: list = []
    disallowed_builds: list = []
    build_map: dict = {}

    aging_build_sum = aging_build_count + current_build_count

    for os_name in os_build_map.keys():
        for feature in os_build_map[os_name].keys():
            i = 0
            for build in os_build_map[os_name][feature]:
                if i < current_build_count:
                    current_builds.append(build)
                elif i < aging_build_sum:
                    aging_builds.append(build)
                else:
                    disallowed_builds.append(build)
                i += 1

    build_map["current"] = current_builds
    build_map["aging"] = aging_builds
    build_map["disallowed"] = disallowed_builds

    return build_map


def recursive_merge(dict1, dict2):
    for key, value in dict2.items():
        if key in dict1 and isinstance(dict1[key], dict) and isinstance(value, dict):
            # Recursively merge nested dictionaries
            dict1[key] = recursive_merge(dict1[key], value)
        else:
            # Merge non-dictionary values
            dict1[key] = value
    return dict1


def map_allowed_deployed(deployed_os_builds, build_allowed_builds, build_os_mappings):
    release_build_frame: dict = {"current": 0, "aging": 0, "disallowed": 0}
    build_map: dict = {}

    # Build Deployment Counts Frame
    for os_name in build_os_mappings.keys():
        for release in build_os_mappings[os_name]:
            for build in build_os_mappings[os_name][release]:
                if build in deployed_os_builds:
                    os_build_frame: dict = {
                        os_name: {release: deepcopy(release_build_frame)}
                    }

                    build_map = recursive_merge(build_map, os_build_frame)

    for os_name in build_os_mappings.keys():
        for release in build_os_mappings[os_name]:
            for build in build_os_mappings[os_name][release]:
                if build in deployed_os_builds:
                    for classification in build_allowed_builds.keys():
                        if build in build_allowed_builds[classification]:
                            new_count = (
                                build_map[os_name][release][classification]
                                + deployed_os_builds[build]
                            )

                            build_map[os_name][release][classification] = new_count

    return build_map


def main():
    assert sys.version_info >= (3, 12)

    config_args = get_config_args()

    configure_logging(
        debug_logging=config_args.debug_logging, info_logging=config_args.info_logging
    )

    config_file = Path(config_args.config_file).absolute()
    with open(config_file, "r") as cf:
        config_settings: dict = yaml.safe_load(cf)

    syncro_data_file = (
        DEFAULT_SYNCRO_FILE
        if DEFAULT_SYNCRO_FILE == config_args.syncro_input_file
        else str(config_args.syncro_input_file)
    )

    output_path = config_args.output_path

    all_builds: list = windows_builds(config_settings)

    syncro_data = syncro_report(syncro_data_file)

    deployed_os_builds = map_syncro_to_microsoft(syncro_data, all_builds)

    build_os_mappings = map_builds_to_os(all_builds)

    build_allowed_builds = map_allowed_builds(
        build_os_mappings,
        current_build_count=config_settings["current-build-count"],
        aging_build_count=config_settings["aging-build-count"],
    )

    build_allowed_deployed_os_builds = map_allowed_deployed(
        deployed_os_builds, build_allowed_builds, build_os_mappings
    )

    export_data(output_path, build_allowed_deployed_os_builds)


if __name__ == "__main__":
    main()
