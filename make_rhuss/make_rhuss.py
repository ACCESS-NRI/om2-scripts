import xarray as xr
import netCDF4 as nc
import os
import datetime
from glob import glob
from calendar import isleap
import numpy as np

# JRA-55 input file directory
JRAin = '/g/data/ik11/inputs/JRA-55/RYF/v1-4/'

# RYF year
RYFyrs = '1990_1991'

# Input files
tairfile = os.path.join(JRAin,'RYF.tas.' + RYFyrs + '.nc')
qairfile = os.path.join(JRAin,'RYF.huss.' + RYFyrs + '.nc')
slpfile = os.path.join(JRAin,'RYF.psl.' + RYFyrs + '.nc')

# Output directory and file
JRAout = '/g/data/e14/rmh561/access-om2/input/JRA-55/RYF/v1-4/'
rairfile = os.path.join(JRAout,'RYF.rhuss.' + RYFyrs + '.nc')

# Load input fields
qair_ds = xr.open_dataset(qairfile,decode_coords=False)
tair_ds = xr.open_dataset(tairfile,decode_coords=False)
slp_ds = xr.open_dataset(slpfile,decode_coords=False)

# Copy specific humidity field and change meta-data
rair_ds = qair_ds.rename({'huss':'rhuss'})
rair_ds["rhuss"].attrs["standard_name"] = "relative_humidity"
rair_ds["rhuss"].attrs["long_name"] = "Near-Surface Relative Humidity"
rair_ds["rhuss"].attrs["comment"] = "Near-surface (usually, 2 meter) relative humidity"
rair_ds["rhuss"].attrs["units"] = "percent"
rair_ds.attrs["comment"] = 'Created from JRA55-do input by https://github.com/COSIMA/make_rhuss"

# Note: The below calculation mirrors that performed in the code to
# convert the relative humidity back to specific humidity.
#
# See https://github.com/COSIMA/cice5/pull/59
# https://github.com/COSIMA/cice5/issues/57

# Reference:
# Wallance and Hobbs (2006) Atmospheric Science: An introductory
# survey. Second edition. Vol 92 in the International Geophysics
# Series, Elsevier.

# Conversion constants (see CICE5/drivers/auscom/ice_constants.F90)
eref = 6.11e2 # Pascals
Lvap = 2.501e6 # Latent heat vaporization freshwater, J/kg
Tffresh = 273.15 # 0K in Celsius
rvgas = 461.5 # gas constant for water vapour
rdgas = 287.04 # gas constant for dry air
rtgas = rdgas/rvgas # ratio of gas constants

# Saturation specific humidity using Clasius-Clapeyron
e_sat = eref*np.exp((Lvap/rvgas)*(1./Tffresh-1./tair_ds.tas))

# vapor pressure
e = qair_ds.huss*slp_ds.psl/(rtgas+(1.-rtgas)*qair_ds.huss)

# relative humidity
rh = e/e_sat*100.0

# save to file
rair_ds.rhuss.values = rh
rair_ds.to_netcdf(rairfile)

