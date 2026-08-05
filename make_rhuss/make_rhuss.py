# Copyright 2026 ACCESS-NRI and contributors. See the top-level COPYRIGHT file for details.
# SPDX-License-Identifier: Apache-2.0

# =========================================================================================
# Create a JRA55-do relative humidity input file from the provided specific humidity fields.
# This is intended to be used when one wants to provide relative humidity as a forcing field
# instead of specific humidity (e.g. to keep the relative humidity constant when applying an
# air temperature perturbation). See discussion here: https://github.com/COSIMA/cice5/issues/57
#
# This script is strongly based on code written by Ryan Holmes at
# https://github.com/COSIMA/make_rhuss/tree/main. The original code has been extended to
# support RYF and IAF data and to add provenance metadata to the generated files.
#
# To force ACCESS-OM2 with relative humidity instead of specific humidity, make the following
# changes to the configuration:
# - Change `qair_i` to `relh_i` in ice/input_ice.nml
# - Change `qair_ai qair_i` to `relh_ai relh_i` in namcouple
# - In atmosphere/forcing.json change:
#   ```
#   "filename": "INPUT/RYF.huss.1990_1991.nc",
#   "fieldname": "huss",
#   "cname": "qair_ai"
#   ```
# to
#   ```
#   "filename": "INPUT/RYF.rhuss.1990_1991.nc",
#   "fieldname": "rhuss",
#   "cname": "relh_ai"
#   ```
#
# To run this script:
#   python make_rhuss.py RYF --input-path <path-to-jra55do-huss-files>
#       --output-path <path-to-output-directory>
#
#   or
#
#   python make_rhuss.py IAF --input-path <path-to-jra55do-huss-files>
#       --output-path <path-to-output-directory> [--start-year=<first-year-to-process> \
#       --end-year=<last-year-to-process>]
#
# For more information, run `python make_rhuss.py -h`
#
# The run command and full github url of the current version of this script is added to the
# metadata of the generated file. This is to uniquely identify the script and inputs used to
# generate the file. To produce files for sharing, ensure you are using a version of this script
# which is committed and pushed to github. For files intended for released configurations, use the
# latest version checked in to the main branch of the github repository.
#
# Contact:
#   Dougie Squire <dougie.squire@anu.edu.au>
#
# Dependencies:
#   xarray, numpy
# =========================================================================================

import argparse
import os
import glob
import subprocess
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import xarray as xr

xr.set_options(use_new_combine_kwarg_defaults=True)

# Conversion constants. These must match those used by CICE5 when it converts the relative
# humidity back to specific humidity. See:
# - CICE5/drivers/auscom/ice_constants.F90
# - CICE5/drivers/auscom/cpl_forcing_handler.F90::rh2q
# Reference:
#   Wallace and Hobbs (2006) Atmospheric Science: An introductory survey. Second edition.
#   Vol 92 in the International Geophysics Series, Elsevier.
EREF = 611.00  # saturation vapour pressure at 273.15 K [Pa]
LVAP = 2.501e6  # latent heat of vaporization, freshwater [J/kg]
TFFRESH = 273.15  # freezing temp of fresh ice [K]
RVGAS = 461.50  # gas constant for water vapour
RDGAS = 287.04  # gas constant for dry air
RTGAS = RDGAS / RVGAS  # ratio of gas constants
TMIN = 114.0  # c114, lower temperature clamp applied by rh2q
TMAX = 373.0  # c373, upper temperature clamp applied by rh2q

def get_provenance_metadata():
    """
    Return a history string recording the run command and the full github url of the current
    version of this script, so generated files can be traced back to the code that made them.

    Warns if the working copy contains uncommitted changes or the commit is unpushed.
    """
    def _git(args, cwd):
        """Run a git command, returning stripped stdout, or None on failure."""
        try:
            return subprocess.check_output(
                ["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
            return None

    this_file = os.path.abspath(__file__)
    cwd = os.path.dirname(this_file)
    runcmd = f"{os.path.basename(sys.executable)} {this_file} " + " ".join(sys.argv[1:])
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    root = _git(["rev-parse", "--show-toplevel"], cwd)
    if root is None:
        warnings.warn(
            "This script is not in a git repository, so its version cannot be recorded in "
            "the output metadata. Do not share the generated files."
        )
        return f"{timestamp}: {runcmd} (unknown version: not in a git repository)"

    sha = _git(["rev-parse", "HEAD"], cwd)
    remote = _git(["config", "--get", "remote.origin.url"], cwd)
    relpath = os.path.relpath(this_file, root)

    if _git(["status", "--porcelain", "--", relpath], cwd):
        warnings.warn(
            f"{relpath} has uncommitted changes, so the url recorded in the output metadata "
            "will not reflect the code that was run. Do not share the generated files."
        )
    if not _git(["branch", "-r", "--contains", sha], cwd):
        warnings.warn(
            f"Commit {sha} has not been pushed, so the url recorded in the output metadata "
            "will not resolve for other users. Do not share the generated files."
        )

    if remote is None:
        url = f"unknown remote, commit {sha}, {relpath}"
    else:
        if remote.startswith("git@github.com:"):
            remote = "https://github.com/" + remote[len("git@github.com:") :]
        if remote.endswith(".git"):
            remote = remote[: -len(".git")]
        url = f"{remote}/blob/{sha}/{relpath}"

    return f"Created on {timestamp} using {url}: {runcmd}"

def find_file(input_path, forcing_type, variable, year):
    """
    Return the path of the JRA55-do forcing file for a provided variable and year.
    """
    if forcing_type == "IAF":
        var_path = input_path.replace("huss", variable)
        matches = glob.glob(os.path.join(var_path, f"{variable}*_{year}*-{year}*.nc"))
        if len(matches) == 1:
            path = matches[0]
        else:
            raise FileNotFoundError(f"Expected one IAF {variable} file for {year}, got {len(matches)}")
    elif forcing_type == "RYF":
        path = os.path.join(input_path, f"RYF.{variable}.{year}.nc")
        if not os.path.exists(path):
            raise FileNotFoundError(f"RYF {variable} file for {year} not found")
    return path

def open_year(input_path, forcing_type, year):
    """
    Open the huss, tas and psl data for given year as a single dataset. Global attributes are
    taken from huss.
    """
    variables = ("huss", "tas", "psl")
    paths = {v: find_file(input_path, forcing_type, v, year) for v in variables}
    ds = xr.merge(
        [xr.open_dataset(p, decode_coords=False) for p in paths.values()],
        join="exact",
        combine_attrs="override",
    )
    ds.attrs["source_files"] = ", ".join(paths.values())
    return ds

def calculate_and_save_rhuss(input_path, forcing_type, year, output_path, history):
    """
    Calculate and save the relative humidity from specific humidity, air temperature and pressure.
    """
    ds = open_year(input_path, forcing_type, year)

    rair = ds.drop_vars(["tas", "psl"]).rename({"huss": "rhuss"})

    # Saturation vapour pressure using Clausius-Clapeyron. The clamp mirrors rh2q.
    e_sat = EREF * np.exp((LVAP / RVGAS) * (1.0 / TFFRESH - 1.0 / np.clip(ds["tas"], TMIN, TMAX)))

    # Vapour pressure.
    e = ds["huss"] * ds["psl"] / (RTGAS + (1.0 - RTGAS) * ds["huss"])

    # Relative humidity.
    rair["rhuss"] = e / e_sat * 100.0

    # Fix up the metadata and rhuss encoding
    rair["rhuss"].attrs["standard_name"] = "relative_humidity"
    rair["rhuss"].attrs["long_name"] = "Near-Surface Relative Humidity"
    rair["rhuss"].attrs["comment"] = "Near-surface (usually, 2 meter) relative humidity"
    rair["rhuss"].attrs["units"] = "percent"
    rair.attrs["variable_id"] = "rhuss"
    rair.attrs["history"] = "\n".join(filter(None, [history, ds.attrs.get("history")]))

    rair["rhuss"].encoding = {
        "dtype": "float32",
        "_FillValue": 1.0e20,
        "zlib": True,
        "complevel": 4,
    }
    chunksizes = ds["huss"].encoding.get("chunksizes")
    if chunksizes is not None:
        rair["rhuss"].encoding["chunksizes"] = chunksizes

    # netCDF4 writes a default _FillValue on any variable without one specified, which is not
    # CF compliant for dimension/coordinate/bounds variables.
    for var in rair.variables:
        if var != "rhuss":
            rair[var].encoding["_FillValue"] = None

    output_filename = os.path.basename(
        find_file(input_path, forcing_type, "huss", year)
    ).replace("huss", "rhuss")
    rair.to_netcdf(
        os.path.join(output_path, output_filename),
        unlimited_dims="time",
    )

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Create JRA55-do relative humidity (rhuss) forcing files"
        ),
    )
    subparsers = parser.add_subparsers(dest="forcing_type", required=True)

    # Arguments common to both forcing modes
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--output-path", required=True, help="Directory to write the rhuss file(s) to."
    )
    common.add_argument(
        "--input-path",
        required=True,
        help=(
            "Path to the directory containing the JRA55-do huss files. E.g. for IAF, something like "
            "/g/data/qv56/replicas/input4MIPs/CMIP6Plus/OMIP/MRI/MRI-JRA55-do-1-6-0/atmos/3hrPt/huss/gr/v20240531; "
            "and for RYF, something like /g/data/vk83/configurations/inputs/JRA-55/RYF/v1-6/2026.04.15."
        )
    )

    # IAF-specific arguments
    iaf = subparsers.add_parser(
        "IAF", parents=[common], help="Interannual forcing (per-year input4MIPs files)."
    )
    iaf.add_argument(
        "--start-year", type=int, default=1958, help="First year to process (inclusive)."
    )
    iaf.add_argument(
        "--end-year", type=int, default=2024, help="Last year to process (inclusive)."
    )

    # RYF-specific arguments
    ryf = subparsers.add_parser(
        "RYF", parents=[common], help="Repeat-year forcing (single RYF file set)."
    )

    args = parser.parse_args()
    forcing_type = args.forcing_type
    input_path = os.path.abspath(args.input_path)
    output_path = os.path.abspath(args.output_path)

    history = get_provenance_metadata()

    if forcing_type == "IAF":
        for year in range(args.start_year, args.end_year+1):
            calculate_and_save_rhuss(input_path, forcing_type, year, output_path, history)
    elif forcing_type == "RYF":
        calculate_and_save_rhuss(input_path, forcing_type, "1990_1991", output_path, history)

if __name__ == "__main__":
    main()


