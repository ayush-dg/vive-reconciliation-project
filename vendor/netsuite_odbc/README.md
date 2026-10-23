# NetSuite SuiteAnalytics Connect ODBC driver (Linux 64-bit)

The driver files are **not committed** (licensed vendor binaries, ~55 MB). The
Dockerfile copies this folder to `/opt/netsuite/odbcclient/` and registers the
driver as `NetSuite ODBC Drivers 9.0`; with only this README present the image
builds without it.

To build an image with the driver:

1. In NetSuite: Setup > SuiteAnalytics Connect > download **Linux 64-bit**
   (`NetSuiteODBCDrivers_Linux64bit.zip`) and unzip it.
2. Copy its `lib64/`, `cert/`, `locale/` and `odbc64.ini` into this folder of
   the build context (for `az acr build`, the clean `git archive` copy you
   build from -- the driver is git-ignored, so it isn't in the archive).
3. Build. `scripts/check_odbc_drivers.py` runs during the build and fails it
   if the NetSuite or SQL Server driver can't be loaded.

Installing or using the driver means accepting NetSuite's Licensing
Information User Manual for SuiteAnalytics Connect (see the driver's
README.txt).
