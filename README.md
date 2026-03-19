# python-powercalc

Standalone Python library for calculating device power usage from 
[homeassistant-powercalc](https://github.com/bramstroker/homeassistant-powercalc)
profile data and LUT files, without any **Home Assistant dependency**.

## Requirements

- Python 3.11+
- No third-party runtime dependencies (stdlib only)

## Installation

```bash
pip install -e .
# or for development:
pip install -e ".[dev]"
```

---

## Quick start

```python
from powercalc_engine import PowercalcEngine

engine = PowercalcEngine(profile_dir="profile_library")

# ON - hs mode
watts = engine.get_power(
    manufacturer="signify",
    model="LCA001",
    state={
        "is_on": True,
        "brightness": 180,
        "color_mode": "hs",
        "hue": 24000,
        "saturation": 180,
        "color_temp": None,
        "effect": None,
    },
)
print(f"{watts:.3f} W")

# OFF → returns standby_power from model.json (or 0.0)
watts_off = engine.get_power(
    manufacturer="signify",
    model="LCA001",
    state={"is_on": False},
)
print(f"Standby: {watts_off:.3f} W")
```

---

## Remote profile download

Profiles are sourced from the
[homeassistant-powercalc](https://github.com/bramstroker/homeassistant-powercalc)
repository (`profile_library/` directory, branch `master`).
Use `GithubProfileStore` to download or update individual profiles on demand -
**no full clone required**.

```python
from powercalc_engine import PowercalcEngine
from powercalc_engine.remote import GithubProfileStore

store = GithubProfileStore(
    profile_dir="profile_library",   # local cache directory
    repo_owner="bramstroker",
    repo_name="homeassistant-powercalc",
    repo_ref="master",               # confirmed default branch
)

# Check remote existence without downloading
if store.profile_exists("signify", "LCA001"):
    result = store.download_profile("signify", "LCA001")
    print(result.message)
    # linked_profile entries in model.json are downloaded automatically
    print("Linked:", result.linked_profiles_downloaded)

# Download only if not already local
store.ensure_profile_available("signify", "LCA001")

# Update a single cached profile (compares Git blob SHA, not dates)
update = store.update_profile("signify", "LCA001")
if update.updated:
    print("Changed files:", update.files_changed)
else:
    print("Already up to date")

# Update every locally cached profile
results = store.update_all_local_profiles()
for r in results:
    print(f"{r.manufacturer}/{r.model}: {r.message}")

# Then calculate power normally - PowercalcEngine is unchanged
engine = PowercalcEngine(profile_dir="profile_library")
watts = engine.get_power("signify", "LCA001", state={"is_on": True, "brightness": 200})
```

### GitHub rate limits

Unauthenticated API calls are limited to **60 requests/hour** per IP.
Set `GITHUB_TOKEN` (or `GH_TOKEN`) in the environment to raise this to 5 000/hour:

```bash
export GITHUB_TOKEN=ghp_...
```

### Local manifest

Every downloaded profile gets a `.powercalc_source.json` manifest alongside
its CSV files.  The manifest stores Git blob SHA fingerprints for each file
and is used by `update_profile` to detect changes without re-downloading
unchanged files.

```
profile_library/
└── signify/
    └── LCA001/
        ├── model.json
        ├── brightness.csv.gz
        ├── hs.csv.gz
        ├── color_temp.csv.gz
        └── .powercalc_source.json   ← manifest
```

---

## Supported color modes

| mode         | CSV file              | Columns               |
|--------------|-----------------------|-----------------------|
| `brightness` | `brightness.csv(.gz)` | `bri, watt`           |
| `color_temp` | `color_temp.csv(.gz)` | `bri, mired, watt`    |
| `hs`         | `hs.csv(.gz)`         | `bri, hue, sat, watt` |
| `effect`     | `effect.csv(.gz)`     | `effect, bri, watt`   |

---

## Standby / off behaviour

| Condition                                   | Result                          |
|---------------------------------------------|---------------------------------|
| `is_on = False`                             | `standby_power` from model.json |
| `is_on = True`, `brightness = 0`, no effect | `standby_power` from model.json |
| `standby_power` absent from model.json      | `0.0`                           |

---

## CLI

### Power calculation

```bash
python -m powercalc_engine.cli get-power \
  --profile-dir ./profile_library \
  --manufacturer signify \
  --model LCA001 \
  --is-on true \
  --brightness 180 \
  --color-mode hs \
  --hue 24000 \
  --saturation 180

# Device off → standby_power
python -m powercalc_engine.cli get-power \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001 \
  --is-on false

# JSON output
python -m powercalc_engine.cli get-power \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001 \
  --is-on false --output json

# Inspect a local profile
python -m powercalc_engine.cli inspect \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001
```

### Remote profile management

```bash
# Check if a profile exists in the remote repo
python -m powercalc_engine.cli profile exists \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001

# Download a profile (also fetches linked_profile automatically)
python -m powercalc_engine.cli profile download \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001

# Update a single cached profile
python -m powercalc_engine.cli profile update \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001

# Update all locally cached profiles
python -m powercalc_engine.cli profile update-all \
  --profile-dir ./profile_library

# Optional flags for all profile subcommands
#   --repo-owner   (default: bramstroker)
#   --repo-name    (default: homeassistant-powercalc)
#   --repo-ref     (default: master)
#   --output plain|json
```

`profile exists` exits with code **0** if found, **2** if not found, **1** on error -
usable in shell scripts:

```bash
python -m powercalc_engine.cli profile exists \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001 \
&& echo "ready" || python -m powercalc_engine.cli profile download \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001
```

---

## Project structure

```
powercalc_engine/
├── __init__.py        # Public API exports
├── engine.py          # PowercalcEngine - main entry point
├── loader.py          # Profile directory discovery (alias + linked_profile)
├── model_json.py      # model.json parsing
├── models.py          # ModelProfile dataclass + DeviceState TypedDict
├── exceptions.py      # Custom exceptions (local + remote)
├── cli.py             # CLI: get-power, inspect, profile subcommands
├── lut/
│   ├── __init__.py
│   ├── base.py        # Shared helpers: file open, interpolation
│   ├── brightness.py  # brightness.csv(.gz)
│   ├── color_temp.py  # color_temp.csv(.gz)
│   ├── hs.py          # hs.csv(.gz)
│   └── effect.py      # effect.csv(.gz)
└── remote/
    ├── __init__.py    # GithubProfileStore, DownloadResult, UpdateResult
    ├── models.py      # RemoteFile, DownloadResult, UpdateResult
    ├── manifest.py    # .powercalc_source.json read/write
    ├── github_client.py  # urllib-based GitHub Contents API client
    └── github_store.py   # GithubProfileStore - full public API

tests/
├── conftest.py
├── test_base_helpers.py
├── test_engine.py
├── test_lut_brightness.py
├── test_lut_color_temp.py
├── test_lut_hs.py
├── test_lut_effect.py
├── test_model_json_and_loader.py
├── test_aliases_and_linked_profile.py
├── test_standby_detection.py
└── test_remote.py             # GithubProfileStore - all mocked, no real HTTP
```

---

## Exceptions

| Exception                   | When raised                                               |
|-----------------------------|-----------------------------------------------------------|
| `ModelNotFoundError`        | Profile directory not found locally                       |
| `MissingLookupTableError`   | Required CSV/CSV.GZ file absent                           |
| `InvalidModelJsonError`     | model.json missing, unreadable, or bad JSON               |
| `LutCalculationError`       | Unknown effect name in effect LUT                         |
| `RemoteProfileNotFoundError`| Profile does not exist in remote repo (HTTP 404)          |
| `RemoteAccessError`         | Network failure or GitHub API error (rate limit, 5xx, …)  |
| `ProfileUpdateError`        | update_profile called with no local copy present          |

All inherit from `PowercalcError`.

---

## Deviations from original powercalc

Intentional changes are marked `# DEVIATION FROM ORIGINAL` in the source.

1. **`LutCalculationError` instead of logger warning** for unknown effects -
   the engine raises explicitly so callers can decide to fall through
   (which `engine.py` does automatically).
2. **`brightness = None` guard** - HA always provides brightness; the
   standalone engine treats `None` brightness with no effect as standby.
3. **`brightness = 0` + active effect** - still computes effect power
   (effect table may have a `bri=0` sample).

The remote module (`GithubProfileStore`) has no equivalent in the original
HA integration and is entirely new.

---

## Running tests

```bash
pip install -e ".[dev]"
pytest
# With coverage:
pytest --cov=powercalc_engine --cov-report=term-missing
```

---

## Dokumentacja (PL)

### Szybki start

```python
from powercalc_engine import PowercalcEngine

engine = PowercalcEngine(profile_dir="profile_library")

# Urządzenie włączone - tryb hs
watts = engine.get_power(
    manufacturer="signify",
    model="LCA001",
    state={
        "is_on": True,
        "brightness": 180,
        "color_mode": "hs",
        "hue": 24000,
        "saturation": 180,
        "color_temp": None,
        "effect": None,
    },
)
print(f"{watts:.3f} W")

# Urządzenie wyłączone → zwraca standby_power z model.json (lub 0.0)
watts_off = engine.get_power(
    manufacturer="signify",
    model="LCA001",
    state={"is_on": False},
)
print(f"Tryb czuwania: {watts_off:.3f} W")
```

### Zdalne pobieranie profili

Profile urządzeń są pobierane z repozytorium
[homeassistant-powercalc](https://github.com/bramstroker/homeassistant-powercalc)
(katalog `profile_library/`, gałąź `master`).
Moduł `GithubProfileStore` pozwala pobierać i aktualizować pojedyncze profile
na żądanie - **bez klonowania całego repozytorium**.

```python
from powercalc_engine.remote import GithubProfileStore

store = GithubProfileStore(
    profile_dir="profile_library",   # lokalny katalog z profilami
    repo_owner="bramstroker",
    repo_name="homeassistant-powercalc",
    repo_ref="master",
)

# Sprawdź czy profil istnieje zdalnie (bez pobierania)
if store.profile_exists("signify", "LCA001"):
    wynik = store.download_profile("signify", "LCA001")
    print(wynik.message)
    # profile powiązane (linked_profile) są pobierane automatycznie
    print("Pobrano powiązane:", wynik.linked_profiles_downloaded)

# Pobierz tylko jeśli nie ma lokalnie
store.ensure_profile_available("signify", "LCA001")

# Zaktualizuj pojedynczy profil (porównuje SHA plików, nie daty)
aktualizacja = store.update_profile("signify", "LCA001")
if aktualizacja.updated:
    print("Zmienione pliki:", aktualizacja.files_changed)
else:
    print("Profil jest aktualny")

# Zaktualizuj wszystkie lokalnie pobrane profile
wyniki = store.update_all_local_profiles()
for r in wyniki:
    print(f"{r.manufacturer}/{r.model}: {r.message}")
```

### Limity GitHub API

Bez uwierzytelnienia dozwolone jest **60 zapytań/godzinę** per adres IP.
Ustaw zmienną środowiskową `GITHUB_TOKEN` (lub `GH_TOKEN`), aby podnieść limit do 5 000/godzinę:

```bash
export GITHUB_TOKEN=ghp_...
```

### Lokalny manifest

Każdy pobrany profil otrzymuje plik `.powercalc_source.json` przechowujący
sumy kontrolne SHA (Git blob SHA) dla wszystkich plików.
Plik ten jest używany przez `update_profile` do wykrywania zmian bez
ponownego pobierania niezmienioych plików.

### Obsługiwane tryby kolorów

| Tryb         | Plik CSV              | Kolumny               |
|--------------|-----------------------|-----------------------|
| `brightness` | `brightness.csv(.gz)` | `bri, watt`           |
| `color_temp` | `color_temp.csv(.gz)` | `bri, mired, watt`    |
| `hs`         | `hs.csv(.gz)`         | `bri, hue, sat, watt` |
| `effect`     | `effect.csv(.gz)`     | `effect, bri, watt`   |

### Zachowanie w trybie czuwania

| Warunek                                           | Wynik                              |
|---------------------------------------------------|------------------------------------|
| `is_on = False`                                   | `standby_power` z model.json       |
| `is_on = True`, `brightness = 0`, brak efektu     | `standby_power` z model.json       |
| Brak pola `standby_power` w model.json            | `0.0`                              |

### CLI - zarządzanie profilami

```bash
# Sprawdź czy profil istnieje zdalnie
python -m powercalc_engine.cli profile exists \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001

# Pobierz profil (automatycznie dociąga linked_profile)
python -m powercalc_engine.cli profile download \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001

# Zaktualizuj pojedynczy profil
python -m powercalc_engine.cli profile update \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001

# Zaktualizuj wszystkie lokalnie pobrane profile
python -m powercalc_engine.cli profile update-all \
  --profile-dir ./profile_library

# Oblicz pobór mocy
python -m powercalc_engine.cli get-power \
  --profile-dir ./profile_library \
  --manufacturer signify --model LCA001 \
  --is-on true --brightness 180 --color-mode hs \
  --hue 24000 --saturation 180
```

### Wyjątki

| Wyjątek                       | Kiedy jest rzucany                                           |
|-------------------------------|--------------------------------------------------------------|
| `ModelNotFoundError`          | Katalog profilu nie istnieje lokalnie                        |
| `MissingLookupTableError`     | Brak wymaganego pliku CSV/CSV.GZ                             |
| `InvalidModelJsonError`       | Plik model.json jest nieczytelny lub zawiera błędny JSON     |
| `LutCalculationError`         | Nieznana nazwa efektu w tabeli LUT                           |
| `RemoteProfileNotFoundError`  | Profil nie istnieje w zdalnym repozytorium (HTTP 404)        |
| `RemoteAccessError`           | Błąd sieci lub API GitHuba (limit zapytań, błąd 5xx, itp.)  |
| `ProfileUpdateError`          | `update_profile` wywołane bez lokalnej kopii profilu         |

Wszystkie dziedziczą po `PowercalcError`.

### Uruchamianie testów

```bash
pip install -e ".[dev]"
pytest
# Z pokryciem kodu:
pytest --cov=powercalc_engine --cov-report=term-missing
```

---

Made with ❤️ in Poland 🇵🇱