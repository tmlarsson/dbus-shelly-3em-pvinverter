# dbus-shelly-3em-pvinverter

Publish a Shelly 3EM as a Victron Venus OS PV inverter (`com.victronenergy.pvinverter`).

Use this when the 3EM is clamped on a grid-tied inverter (Growatt, GTIL, etc.) so Venus can show solar on the overview.

## What it does

The driver is a daemontools service. Every `PollIntervalSeconds` (default 2) it GETs `http://<host>/status` and maps `emeters[0..2]` to L1–L3 plus `/Ac/Power` from `total_power`.

`/Position` is the Victron PV position: `0` AC-in 1, `1` AC-out, `2` AC-in 2.

## Config

Edit `/data/dbus-shelly-3em-pvinverter/config.ini` on the GX.

| Section | Key | Meaning |
|---|---|---|
| `DEFAULT` | `Deviceinstance` | Venus instance (`http_100` if 100) |
| `DEFAULT` | `CustomName` | Name in Remote Console |
| `DEFAULT` | `Position` | `0` AC-in 1, `1` AC-out, `2` AC-in 2 |
| `DEFAULT` | `SignOfLifeLog` | Minutes between info log lines |
| `DEFAULT` | `PollIntervalSeconds` | How often to poll (default 2, minimum 1) |
| `ONPREMISE` | `Host` | Shelly 3EM IP/hostname |
| `ONPREMISE` | `Username` / `Password` | Optional HTTP basic auth |

## Install

On the GX (root SSH):

```bash
wget -O /tmp/shelly-3em.zip https://github.com/tmlarsson/dbus-shelly-3em-pvinverter/archive/refs/heads/main.zip
unzip /tmp/shelly-3em.zip -d /tmp
rm -rf /data/dbus-shelly-3em-pvinverter
cp -R /tmp/dbus-shelly-3em-pvinverter-main /data/dbus-shelly-3em-pvinverter
chmod a+x /data/dbus-shelly-3em-pvinverter/install.sh
/data/dbus-shelly-3em-pvinverter/install.sh
```

Edit `config.ini`, then restart.

## Restart / uninstall / logs

```bash
/data/dbus-shelly-3em-pvinverter/restart.sh
/data/dbus-shelly-3em-pvinverter/uninstall.sh
tail -n 100 -f /data/log/dbus-shelly-3em-pvinverter/current | tai64nlocal
```

If that log path is empty, try `/var/log/dbus-shelly-3em-pvinverter/current`.

## Docs

- [Venus D-Bus PV inverter](https://github.com/victronenergy/venus/wiki/dbus#pv-inverters)
- [Shelly 3EM status](https://shelly-api-docs.shelly.cloud/gen1/#shelly-3em)
- [GX root access](https://www.victronenergy.com/live/ccgx:root_access)
