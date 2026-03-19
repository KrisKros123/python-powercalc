"""Command-line interface for powercalc_engine.

Local commands
--------------
  get-power   - calculate power draw
  inspect     - inspect a local profile

Remote profile commands  (subcommand group: profile)
----------------------------------------------------
  profile exists     - check if a profile exists in remote repo
  profile download   - download a profile from remote repo
  profile update     - update a locally cached profile
  profile update-all - update all locally cached profiles

Examples
--------
::

    python -m powercalc_engine.cli get-power \\
        --profile-dir ./profile_library \\
        --manufacturer signify --model LCA001 --is-on false

    python -m powercalc_engine.cli profile exists \\
        --profile-dir ./profile_library \\
        --manufacturer signify --model LCA001

    python -m powercalc_engine.cli profile download \\
        --profile-dir ./profile_library \\
        --manufacturer signify --model LCA001

    python -m powercalc_engine.cli profile update \\
        --profile-dir ./profile_library \\
        --manufacturer signify --model LCA001

    python -m powercalc_engine.cli profile update-all \\
        --profile-dir ./profile_library
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import PowercalcEngine
from .exceptions import PowercalcError, ProfileUpdateError, RemoteAccessError, RemoteProfileNotFoundError
from .remote.github_store import GithubProfileStore


# ---------------------------------------------------------------------------
# Shared argument helpers
# ---------------------------------------------------------------------------


def _add_profile_dir_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile-dir", required=True, metavar="PATH",
                   help="Local profile library directory.")


def _add_mfr_model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--manufacturer", required=True)
    p.add_argument("--model", required=True)


def _add_remote_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo-owner", default="bramstroker",
                   help="GitHub repository owner (default: bramstroker).")
    p.add_argument("--repo-name", default="homeassistant-powercalc",
                   help="GitHub repository name.")
    p.add_argument("--repo-ref", default="master",
                   help="Branch/tag/SHA (default: master).")


def _make_store(args: argparse.Namespace) -> GithubProfileStore:
    return GithubProfileStore(
        profile_dir=args.profile_dir,
        repo_owner=getattr(args, "repo_owner", "bramstroker"),
        repo_name=getattr(args, "repo_name", "homeassistant-powercalc"),
        repo_ref=getattr(args, "repo_ref", "master"),
    )


def _parse_bool(value: str) -> bool:
    return value.lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="powercalc_engine",
        description="Standalone powercalc LUT engine CLI",
    )
    sub = root.add_subparsers(dest="command", required=True)

    # ---- get-power --------------------------------------------------------
    gp = sub.add_parser("get-power", help="Calculate power draw in watts.")
    _add_profile_dir_arg(gp)
    _add_mfr_model_args(gp)
    gp.add_argument("--is-on", default="true",
                    choices=["true", "false", "1", "0", "yes", "no"])
    gp.add_argument("--brightness", type=int, default=None)
    gp.add_argument("--color-mode", default=None,
                    choices=["brightness", "color_temp", "hs", "effect"])
    gp.add_argument("--hue", type=int, default=None)
    gp.add_argument("--saturation", type=int, default=None)
    gp.add_argument("--color-temp", type=int, default=None)
    gp.add_argument("--effect", default=None)
    gp.add_argument(
        "--interpolation-mode",
        default="powercalc",
        choices=["powercalc", "multilinear"],
        dest="interpolation_mode",
        help="LUT interpolation strategy (default: powercalc)."
    )
    gp.add_argument("--output", default="plain", choices=["plain", "json"])

    # ---- inspect ----------------------------------------------------------
    ip = sub.add_parser("inspect", help="Inspect a local profile.")
    _add_profile_dir_arg(ip)
    _add_mfr_model_args(ip)
    ip.add_argument("--output", default="plain", choices=["plain", "json"])

    # ---- profile (sub-group) ----------------------------------------------
    pp = sub.add_parser("profile", help="Remote profile management.")
    psub = pp.add_subparsers(dest="profile_command", required=True)

    # profile exists
    pe = psub.add_parser("exists", help="Check if a profile exists in remote repo.")
    _add_profile_dir_arg(pe)
    _add_mfr_model_args(pe)
    _add_remote_args(pe)
    pe.add_argument("--output", default="plain", choices=["plain", "json"])

    # profile download
    pd = psub.add_parser("download", help="Download a profile from remote repo.")
    _add_profile_dir_arg(pd)
    _add_mfr_model_args(pd)
    _add_remote_args(pd)
    pd.add_argument("--output", default="plain", choices=["plain", "json"])

    # profile update
    pu = psub.add_parser("update", help="Update a locally cached profile.")
    _add_profile_dir_arg(pu)
    _add_mfr_model_args(pu)
    _add_remote_args(pu)
    pu.add_argument("--output", default="plain", choices=["plain", "json"])

    # profile update-all
    pua = psub.add_parser("update-all", help="Update all locally cached profiles.")
    _add_profile_dir_arg(pua)
    _add_remote_args(pua)
    pua.add_argument("--output", default="plain", choices=["plain", "json"])

    return root


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_get_power(args: argparse.Namespace) -> int:
    engine = PowercalcEngine(
        profile_dir=args.profile_dir,
        interpolation_mode=args.interpolation_mode,
    )
    state = {
        "is_on": _parse_bool(args.is_on),
        "brightness": args.brightness,
        "color_mode": args.color_mode,
        "hue": args.hue,
        "saturation": args.saturation,
        "color_temp": args.color_temp,
        "effect": args.effect,
    }
    try:
        watts = engine.get_power(manufacturer=args.manufacturer,
                                  model=args.model, state=state)  # type: ignore[arg-type]
    except PowercalcError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(json.dumps({
            "watts": watts,
            "interpolation_mode": args.interpolation_mode,
            "state": state,
        }, indent=2))
    else:
        print(f"{watts:.4f} W")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    engine = PowercalcEngine(profile_dir=args.profile_dir)
    try:
        profile = engine.get_profile(manufacturer=args.manufacturer, model=args.model)
    except PowercalcError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    data = {
        "manufacturer": profile.manufacturer,
        "model": profile.requested_model,
        "canonical_model": profile.canonical_model,
        "path": str(profile.path),
        "standby_power": profile.standby_power,
        "available_modes": sorted(profile.available_modes),
        "aliases": profile.aliases,
        "linked_profile": profile.linked_profile,
        "metadata": profile.metadata,
    }
    if args.output == "json":
        print(json.dumps(data, indent=2))
    else:
        print(f"Manufacturer   : {data['manufacturer']}")
        print(f"Model (req)    : {data['model']}")
        print(f"Model (canon.) : {data['canonical_model']}")
        print(f"Path           : {data['path']}")
        print(f"Standby power  : {data['standby_power']} W")
        print(f"Available LUTs : {', '.join(data['available_modes']) or '(none)'}")
        if data["aliases"]:
            print(f"Aliases        : {', '.join(data['aliases'])}")
        if data["linked_profile"]:
            print(f"Linked profile : {data['linked_profile']}")
    return 0


def cmd_profile_exists(args: argparse.Namespace) -> int:
    store = _make_store(args)
    try:
        exists = store.profile_exists(args.manufacturer, args.model)
    except RemoteAccessError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(json.dumps({"manufacturer": args.manufacturer,
                          "model": args.model, "exists": exists}))
    else:
        status = "EXISTS" if exists else "NOT FOUND"
        print(f"Remote profile {args.manufacturer}/{args.model}: {status}")
    return 0 if exists else 2   # exit code 2 = not found (distinguishable from error)


def cmd_profile_download(args: argparse.Namespace) -> int:
    store = _make_store(args)
    try:
        result = store.download_profile(args.manufacturer, args.model)
    except (RemoteProfileNotFoundError, RemoteAccessError, PowercalcError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        import dataclasses
        print(json.dumps({
            **dataclasses.asdict(result),
            "local_path": str(result.local_path) if result.local_path else None,
        }, indent=2))
    else:
        print(result.message)
        if result.linked_profiles_downloaded:
            print(f"  Linked profiles: {', '.join(result.linked_profiles_downloaded)}")
    return 0 if result.downloaded else 1


def cmd_profile_update(args: argparse.Namespace) -> int:
    store = _make_store(args)
    try:
        result = store.update_profile(args.manufacturer, args.model)
    except (ProfileUpdateError, RemoteAccessError, RemoteProfileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        import dataclasses
        print(json.dumps(dataclasses.asdict(result), indent=2))
    else:
        print(result.message)
    return 0


def cmd_profile_update_all(args: argparse.Namespace) -> int:
    store = _make_store(args)
    results = store.update_all_local_profiles()

    if not results:
        print("No locally cached profiles with a manifest found.")
        return 0

    errors = 0
    if args.output == "json":
        import dataclasses
        print(json.dumps([dataclasses.asdict(r) for r in results], indent=2))
    else:
        for r in results:
            print(f"  {r.manufacturer}/{r.model}: {r.message}")
            if not r.updated and not r.was_current:
                errors += 1

    return 0 if errors == 0 else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "get-power":
        return cmd_get_power(args)
    if args.command == "inspect":
        return cmd_inspect(args)
    if args.command == "profile":
        if args.profile_command == "exists":
            return cmd_profile_exists(args)
        if args.profile_command == "download":
            return cmd_profile_download(args)
        if args.profile_command == "update":
            return cmd_profile_update(args)
        if args.profile_command == "update-all":
            return cmd_profile_update_all(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
