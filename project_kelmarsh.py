"""
This is the import script for Cubico's Kelmarsh & Penmanshiel projects. These projects are
available under a Creative Commons Attribution 4.0 International license (CC-BY-4.0), and are cited
below:

*Kelmarsh*:

    Plumley, Charlie. (2022). Kelmarsh wind farm data [Data set].
    Zenodo. https://doi.org/10.5281/zenodo.5841833

*Penmanshiel*:

    Plumley, Charlie. (2022). Penmanshiel Wind Farm Data [Data set].
    Zenodo. https://doi.org/10.5281/zenodo.5946807

Below is a description of the data imported and an overview of the steps taken to correct the raw
data for use in the OpenOA code.

1. SCADA
   - 10-minute SCADA data for each of the turbines in the project
   - Power, wind speed, wind direction, nacelle position, wind vane, temperature, blade pitch

2. Meter data
   - 10-minute performance data provided in energy units (kWh)

3. Curtailment data
   - 10-minute availability and curtailment data in kwh

4. Reanalysis products
   - MERRA2 and ERA5 1-hour reanalysis data where available on Zenodo
   - ERA5 and MERRA2 monthly reanalysis data at ground level (10m)
"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import yaml
import pandas as pd
from typing import Literal

from openoa.plant import PlantData
from openoa.logging import logging


logger = logging.getLogger()


def get_scada_headers(scada_files: list[str]) -> pd.DataFrame:
    """
    Get just the headers from the SCADA files.

    Args:
        scada_files(obj:`list[str]`): List of SCADA file paths.

    Returns:
        scada_headers(:obj:`dataframe`): Dataframe containing details of all the SCADA files.
    """

    csv_params = {
        "index_col": 0,
        "skiprows": 2,
        "nrows": 4,
        "delimiter": ": ",
        "header": None,
        "engine": "python",
    }

    scada_headers = pd.concat(
        (pd.read_csv(f, **csv_params).rename(columns={1: f}) for f in scada_files), axis=1
    )

    scada_headers.index = scada_headers.index.str.replace("# ", "")

    scada_headers = scada_headers.transpose().reset_index().rename(columns={"index": "File"})

    return scada_headers


def get_scada_df(scada_headers: pd.DataFrame, use_columns: list[str] | None = None) -> pd.DataFrame:
    """
    Extract the desired SCADA data.

    Args:
        scada_headers(:obj:`dataframe`): Dataframe containing details of all SCADA files.
        usecolumns(obj:`list[str]`): Selection of columns to be imported from the SCADA files.
            Defaults to None.

    Returns:
        scada(:obj:`dataframe`): Dataframe with SCADA data.
    """

    if use_columns is None:
        use_columns = [
            "# Date and time",
            "Power (kW)",
            "Wind speed (m/s)",
            "Wind direction (°)",
            "Nacelle position (°)",
            "Nacelle ambient temperature (°C)",
            "Blade angle (pitch position) A (°)",
        ]

    csv_params = {
        "index_col": "# Date and time",
        "parse_dates": True,
        "skiprows": 9,
        "usecols": use_columns,
    }

    scada_lst = list()
    for turbine in scada_headers["Turbine"].unique():
        scada_wt = pd.concat(
            pd.read_csv(f, **csv_params)
            for f in list(scada_headers.loc[scada_headers["Turbine"] == turbine]["File"])
        )

        scada_wt["Turbine"] = turbine
        scada_wt.index.names = ["Timestamp"]
        scada_lst.append(scada_wt.copy())

    scada = pd.concat(scada_lst)

    return scada


def get_curtailment_df(scada_headers: pd.DataFrame) -> pd.DataFrame:
    """
    Get the curtailment and availability data.

    Args:
        scada_headers(:obj:`dataframe`): Dataframe containing details of all SCADA files.

    Returns:
        curtailment_df(:obj:`dataframe`): Dataframe with curtailment data.
    """

    # Curtailment data is available as a subset of the SCADA data
    use_columns = [
        "# Date and time",
        "Lost Production to Curtailment (Total) (kWh)",
        "Lost Production to Downtime (kWh)",
    ]

    curtailment_df = get_scada_df(scada_headers, use_columns)

    return curtailment_df


def get_meter_data(path: str = "data/kelmarsh") -> pd.DataFrame:
    """
    Get the PMU meter data.

    Args:
        path(:obj:`str`): Path to meter data. Defaults to "data/kelmarsh".

    Returns:
        meter_df(:obj:`dataframe`): Dataframe with meter data.
    """

    use_columns = ["# Date and time", "GMS Energy Export (kWh)"]

    csv_params = {
        "index_col": "# Date and time",
        "parse_dates": True,
        "skiprows": 10,
        "usecols": use_columns,
    }

    meter_files = list(Path(path).rglob("Device*PMU*.csv"))

    meter_df = pd.read_csv(meter_files[0], **csv_params)

    meter_df.index.names = ["Timestamp"]

    return meter_df


def prepare(root_folder: str | Path, asset: str = "Kelmarsh", output_folder: str | Path = "data", year: int | None = None, return_value: Literal["dataframes", "plantdata"] = "plantdata", extract: bool = True) -> PlantData | pd.DataFrame:
    """
    Do all loading and preparation of the data for this plant.

    Args:
        asset(:obj:`str`): Asset name, currently either "kelmarsh" or "penmanshiel". Defaults
            to "kelmarsh".
        return_value(:obj:`str`):  One of "plantdata" or "dataframes" with the below behavior.
            Defaults to "plantdata".

            - "plantdata" will return a fully constructed PlantData object.
            - "dataframes" will return a list of dataframes instead.

    Returns:
        Either PlantData object or Dataframes dependent upon return_value.
    """

    # Set the path to store and access all the data

    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    
    if extract:
        for p in root_folder.iterdir():
            if p.suffix == ".zip":
                with ZipFile(p) as zipfile:
                    zipfile.extractall(output_folder)
            else:
                link = Path(output_folder) / p.name
                if link.is_symlink():
                    link.unlink()
                link.resolve().symlink_to(p)

    ##############
    # ASSET DATA #
    ##############

    path = output_folder
    
    logger.info("Reading in the asset data")
    asset_df = pd.read_csv(f"{path}/{asset}_WT_static.csv")

    # Remove any empty lines
    asset_df = asset_df.dropna(how="all")

    # Assign type to turbine for all assets
    asset_df["type"] = "turbine"

    ###################
    # SCADA DATA #
    ###################

    logger.info("Reading in the SCADA data")

    if year is not None:
        scada_files = Path(path).rglob(f"Turbine_Data*{year}*.csv")
    else:
        scada_files = Path(path).rglob(f"Turbine_Data*.csv")
 
    scada_headers = get_scada_headers(scada_files)
    scada_df = get_scada_df(scada_headers)
    scada_df = scada_df.reset_index()

    ##############
    # METER DATA #
    ##############

    logger.info("Reading in the meter data")
    meter_df = get_meter_data(path)
    meter_df = meter_df.reset_index()

    #####################################
    # Availability and Curtailment Data #
    #####################################

    logger.info("Reading in the curtailment and availability losses data")
    curtail_df = get_curtailment_df(scada_headers)
    curtail_df = curtail_df.reset_index()

    ###################
    # REANALYSIS DATA #
    ###################

    logger.info("Reading in the reanalysis data")

    # reanalysis datasets are held in a dictionary
    reanalysis_dict = dict()

    # MERRA2 from Zenodo
    asset_path = Path(path).resolve()
    if (asset_path / f"{asset}_merra2.csv").exists():
        logger.info("Reading MERRA2")
        reanalysis_merra2_df = pd.read_csv(f"{path}/{asset}_merra2.csv")
        reanalysis_dict.update(dict(merra2=reanalysis_merra2_df))

    # ERA5 from Zenodo
    if (asset_path / f"{asset}_era5.csv").exists():
        logger.info("Reading ERA5")
        reanalysis_era5_df = pd.read_csv(f"{path}/{asset}_era5.csv")
        reanalysis_dict.update(dict(era5=reanalysis_era5_df))

    # MERRA2 monthly 10m from GES DISC
    if Path(f"{path}/merra2_monthly_10m/{asset}_merra2_monthly_10m.csv").exists():
        logger.info("Reading MERRA2 monthly")
        reanalysis_merra2_monthly_df = pd.read_csv(
            f"{path}/merra2_monthly_10m/{asset}_merra2_monthly_10m.csv"
        )

    ###################
    # PLANT DATA #
    ###################

    # Create plant_meta.json
    asset_json = {
        "asset": {
            "elevation": "Elevation (m)",
            "hub_height": "Hub Height (m)",
            "asset_id": "Title",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "rated_power": "Rated power (kW)",
            "rotor_diameter": "Rotor Diameter (m)",
        },
        "curtail": {
            "IAVL_DnWh": "Lost Production to Downtime (kWh)",
            "IAVL_ExtPwrDnWh": "Lost Production to Curtailment (Total) (kWh)",
            "frequency": "10min",
            "time": "Timestamp",
        },
        "latitude": str(asset_df["Latitude"].mean()),
        "longitude": str(asset_df["Longitude"].mean()),
        "capacity": str(asset_df["Rated power (kW)"].sum() / 1000),
        "meter": {"MMTR_SupWh": "GMS Energy Export (kWh)", "time": "Timestamp"},
        "reanalysis": {},
        "scada": {
            "WMET_EnvTmp": "Nacelle ambient temperature (°C)",
            "WMET_HorWdDir": "Wind direction (°)",
            "WMET_HorWdSpd": "Wind speed (m/s)",
            "WROT_BlPthAngVal": "Blade angle (pitch position) A (°)",
            "asset_id": "Turbine",
            "WTUR_W": "Power (kW)",
            "frequency": "10min",
            "time": "Timestamp",
        },
    }

    with open(f"{path}/plant_meta.json", "w") as outfile:
        json.dump(asset_json, outfile, indent=2)

    with open(f"{path}/plant_meta.yml", "w") as outfile:
        yaml.dump(asset_json, outfile, default_flow_style=False)

    # Return the appropriate data format
    if return_value == "dataframes":
        return (
            scada_df,
            meter_df,
            curtail_df,
            asset_df,
            reanalysis_dict,
        )
    elif return_value == "plantdata":
        # Build and return PlantData
        plantdata = PlantData(
            analysis_type="MonteCarloAEP",  # Choosing a random type that doesn't fail validation
            metadata=f"{path}/plant_meta.yml",
            scada=scada_df,
            meter=meter_df,
            curtail=curtail_df,
            asset=asset_df,
            reanalysis={},
        )

        return plantdata


if __name__ == "__main__":
    prepare()