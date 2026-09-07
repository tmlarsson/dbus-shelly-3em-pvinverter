# dbus-shelly-3em-pvinverter

Publish a Shelly 3EM as a Victron Venus OS PV inverter (`com.victronenergy.pvinverter`).

Use this when the 3EM is clamped on a grid-tied inverter (Growatt, GTIL, etc.) so Venus can show solar on the overview.

## What it does

The driver is a daemontools service. Every `PollIntervalSeconds` (default 2) it GETs `http://<host>/status` and maps `emeters[0..2]` to L1–L3 plus `/Ac/Power` from `total_power`.

`/Position` is the Victron PV position: `0` AC-in 1, `1` AC-out, `2` AC-in 2.

If the Shelly is unreachable, `/Connected` goes to `0` and live watts go to `0`. Lifetime `/Ac/Energy/Forward` is left alone (VRM must not see yield run backwards). Night-time CT standby (a few negative watts) is clamped to `0` unless `AllowNegativePower=1`.

HTTP basic auth uses an `Authorization` header, not `user:pass@host` in the URL.

## Config

Edit `/data/dbus-shelly-3em-pvinverter/config.ini` on the GX.

| Section | Key | Meaning |
|---|---|---|
| `DEFAULT` | `Deviceinstance` | Venus instance (`http_41` if 41). Must not collide with other `pvinverter.http_*` drivers. |
| `DEFAULT` | `CustomName` | Name in Remote Console |
| `DEFAULT` | `Position` | `0` AC-in 1, `1` AC-out, `2` AC-in 2 |
| `DEFAULT` | `SignOfLifeLog` | Minutes between info log lines |
| `DEFAULT` | `PollIntervalSeconds` | How often to poll (default 2, minimum 1). HTTP timeout stays below this. |
| `DEFAULT` | `AllowNegativePower` | `0` (default) clamps generation at 0 W; `1` publishes CT sign as-is |
| `ONPREMISE` | `Host` | Shelly 3EM IP/hostname |
| `ONPREMISE` | `Username` / `Password` | Optional HTTP basic auth |

Older configs had `Phase=L3`. The Python never read that key — all three emeters were always published — so dropping it does not hide or show extra phases.

The sample `Deviceinstance` is `41`. Other community HTTP PV drivers often sit nearby; check existing `com.victronenergy.pvinverter.http_*` names before picking.

## Install

On the GX (root SSH):

```bash
wget -O /tmp/shelly-3em.zip https://github.com/tmlarsson/dbus-shelly-3em-pvinverter/archive/refs/heads/main.zip
unzip /tmp/shelly-3em.zip -d /tmp
# Keep live settings if this is an update
if [ -f /data/dbus-shelly-3em-pvinverter/config.ini ]; then
  cp /data/dbus-shelly-3em-pvinverter/config.ini /tmp/shelly-3em-config.ini
fi
mkdir -p /data/dbus-shelly-3em-pvinverter
cp -R /tmp/dbus-shelly-3em-pvinverter-main/. /data/dbus-shelly-3em-pvinverter/
if [ -f /tmp/shelly-3em-config.ini ]; then
  cp /tmp/shelly-3em-config.ini /data/dbus-shelly-3em-pvinverter/config.ini
fi
chmod a+x /data/dbus-shelly-3em-pvinverter/install.sh
/data/dbus-shelly-3em-pvinverter/install.sh
```

Edit `config.ini` after a first install, then restart. Updates keep the existing `config.ini`.

## Restart / uninstall / logs

```bash
/data/dbus-shelly-3em-pvinverter/restart.sh
/data/dbus-shelly-3em-pvinverter/uninstall.sh
tail -n 100 -f /var/log/dbus-shelly-3em-pvinverter/current | tai64nlocal
```

On some Venus images `/var/log` is the same as `/data/log`.

## Docs

- [Venus D-Bus PV inverter](https://github.com/victronenergy/venus/wiki/dbus#pv-inverters)
- [Shelly 3EM status](https://shelly-api-docs.shelly.cloud/gen1/#shelly-3em)
- [GX root access](https://www.victronenergy.com/live/ccgx:root_access)
