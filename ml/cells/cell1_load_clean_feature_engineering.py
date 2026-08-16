"""Cell 1 — Load, Clean, Feature Engineering"""

import pandas as pd
import numpy as np

# ---- 1. LOAD ----
PATH = '/kaggle/input/datasets/atikurrahman21/solar-data/solar_data_raw.csv'
df = pd.read_csv(PATH, low_memory=False)   # low_memory=False: charging_source has mixed types
print(f"Loaded: {df.shape[0]:,} rows, {df.shape[1]} columns")

# ---- 2. CLEAN ----
df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.sort_values('timestamp').reset_index(drop=True)
df['charging_source'] = df['charging_source'].fillna('None')   # NaN = no charging = valid 'None' state

before = len(df)
df = df.drop_duplicates(subset='timestamp', keep='first').reset_index(drop=True)
print(f"Dropped {before - len(df):,} duplicate timestamps")

# battery_current == load_current (no battery-side sensor), battery_power == -load_power,
# relay_state == constant 1 (zero variance)
drop_cols = ['battery_current', 'battery_power', 'relay_state']
df = df.drop(columns=[c for c in drop_cols if c in df.columns])
print(f"Dropped broken columns: {drop_cols}")

# ---- 3. SEGMENT (split at reboots and big gaps so rolling/lag never cross a discontinuity) ----
gap    = df['timestamp'].diff().dt.total_seconds()
reboot = df['uptime_s'].diff() < 0
new_segment = (gap > 300) | reboot
new_segment.iloc[0] = True
df['segment_id'] = new_segment.cumsum()
print(f"Data split into {df['segment_id'].nunique()} clean segments "
      f"({reboot.sum()} reboots, {(gap>300).sum()} big gaps)")

# ---- 4. FEATURE ENGINEERING (reusable function, also used on the Pi at deploy time) ----
PV_EFF = 0.90   # ASSUMED conversion efficiency (typical MPPT value); NOT measured on this system

def engineer_features(g):
    g = g.copy()
    # cyclical time: 23h and 0h are adjacent, so encode as sin/cos
    h = g['timestamp'].dt.hour + g['timestamp'].dt.minute / 60.0
    g['hour_sin'] = np.sin(2 * np.pi * h / 24)
    g['hour_cos'] = np.cos(2 * np.pi * h / 24)
    # physics-based net battery current (battery_current column is broken)
    # I_batt = (eta*P_solar + eta*P_charge - P_load) / V_batt , eta assumed 0.90
    g['ibatt_est'] = (PV_EFF * g['solar_power'] + PV_EFF * g['charge_power']
                      - g['load_power']) / g['battery_voltage'].replace(0, np.nan)
    g['ibatt_est'] = g['ibatt_est'].fillna(0)
    # rolling mean/std (window 30 = 60s, 150 = 300s @ 2s interval)
    for col in ['battery_voltage', 'load_current', 'solar_power', 'soc']:
        g[f'{col}_rmean60']  = g[col].rolling(30, min_periods=1).mean()
        g[f'{col}_rstd60']   = g[col].rolling(30, min_periods=1).std().fillna(0)
        g[f'{col}_rmean300'] = g[col].rolling(150, min_periods=1).mean()
    # lag + rate-of-change
    for col in ['battery_voltage', 'soc', 'load_current']:
        g[f'{col}_lag30']  = g[col].shift(30)
        g[f'{col}_diff60'] = g[col] - g[f'{col}_lag30']
    g['soc_slope300'] = g['soc'] - g['soc'].shift(150)
    return g

# preserve segment_id across all pandas versions (newer ones drop grouping col in apply)
seg = df['segment_id'].copy()
df = df.groupby('segment_id', group_keys=False).apply(engineer_features).reset_index(drop=True)
if 'segment_id' not in df.columns:
    df['segment_id'] = seg.values

# ---- 5. SUMMARY ----
print("charging_source:", df['charging_source'].value_counts().to_dict())
print("segments:", df['segment_id'].nunique())
df.head()
