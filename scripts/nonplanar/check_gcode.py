#!/usr/bin/env python3
"""Safety check for G-code with Z moves inside a layer (ZAA / non-planar).

Usage: check_gcode.py FILE.gcode [--max-slope DEG] [--tool-lift MM] [--max-z-speed MM_S]
                                 [--travel-tol MM]

For Z contouring (ZAA) output use --max-slope 45 --travel-tol LAYER_HEIGHT:
ZAA shifts roads by up to one layer height over short segments.

Reports, and exits non-zero on, any of:
  * a move below Z 0
  * an extruding move steeper than --max-slope
  * an extruding move whose Z component is faster than --max-z-speed
  * a non-extruding XY travel longer than 2 mm made more than --travel-tol
    below the highest material extruded so far in the same layer
  * a tool change (T<n>) started with the nozzle less than --tool-lift above
    the highest material extruded so far

Assumes absolute XYZ (G90). Relative mode (G91) blocks are followed for Z only.
The check is conservative: it knows nothing about where material is in XY.
"""
import argparse
import math
import re
import sys

WORD = re.compile(r"([XYZEF])(-?\d*\.?\d+)")
TOOL = re.compile(r"^T(\d+)\b")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--max-slope", type=float, default=15.0, help="degrees")
    ap.add_argument("--tool-lift", type=float, default=6.0, help="mm above printed material")
    ap.add_argument("--max-z-speed", type=float, default=20.0, help="mm/s")
    ap.add_argument("--travel-tol", type=float, default=0.0, help="mm a travel may run below printed material")
    ap.add_argument("--max-report", type=int, default=20)
    a = ap.parse_args()

    x = y = z = 0.0
    feed = 0.0
    absolute = True
    e_absolute = True
    e_last = 0.0
    layer_top = 0.0   # highest extruded Z in the current layer
    print_top = 0.0   # highest extruded Z overall
    steepest = 0.0
    deepest = 0.0     # largest drop of an extruding move below layer_top
    problems = []

    def bad(n, msg):
        problems.append(f"line {n}: {msg}")

    with open(a.file, errors="replace") as fh:
        for n, raw in enumerate(fh, 1):
            if raw.startswith(";LAYER_CHANGE"):
                layer_top = 0.0
                continue
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            if line == "G90":
                absolute = True
            elif line == "G91":
                absolute = False
            elif line == "M82":
                e_absolute = True
            elif line == "M83":
                e_absolute = False
            elif line.startswith("G92"):
                w = dict(WORD.findall(line))
                if "E" in w:
                    e_last = float(w["E"])
            elif TOOL.match(line):
                if print_top > 0 and z < print_top + a.tool_lift - 1e-6:
                    bad(n, f"tool change at Z {z:.3f}, needs >= {print_top + a.tool_lift:.3f}")
            elif line.startswith(("G0 ", "G1 ", "G2 ", "G3 ")) or line in ("G0", "G1"):
                w = {k: float(v) for k, v in WORD.findall(line)}
                if "F" in w:
                    feed = w["F"] / 60.0
                if absolute:
                    nx, ny, nz = w.get("X", x), w.get("Y", y), w.get("Z", z)
                else:
                    nx, ny, nz = x + w.get("X", 0.0), y + w.get("Y", 0.0), z + w.get("Z", 0.0)
                de = 0.0
                if "E" in w:
                    de = w["E"] - e_last if e_absolute else w["E"]
                    if e_absolute:
                        e_last = w["E"]
                dxy = math.hypot(nx - x, ny - y)
                dz = nz - z
                if nz < -1e-6:
                    bad(n, f"Z below zero ({nz:.3f})")
                if de > 0 and dxy > 1e-6:
                    slope = math.degrees(math.atan2(abs(dz), dxy))
                    steepest = max(steepest, slope)
                    if slope > a.max_slope + 1e-6:
                        bad(n, f"extruding slope {slope:.1f} deg > {a.max_slope}")
                    dist = math.hypot(dxy, dz)
                    if feed > 0 and abs(dz) / dist * feed > a.max_z_speed + 1e-6:
                        bad(n, f"Z speed {abs(dz) / dist * feed:.1f} mm/s > {a.max_z_speed}")
                    top = max(z, nz)
                    deepest = max(deepest, layer_top - min(z, nz))
                    layer_top = max(layer_top, top)
                    print_top = max(print_top, top)
                elif de <= 0 and dxy > 2.0 and layer_top > 0:
                    if min(z, nz) < layer_top - a.travel_tol - 1e-6:
                        bad(n, f"travel at Z {min(z, nz):.3f} below printed {layer_top:.3f}")
                x, y, z = nx, ny, nz

    print(f"steepest extruding slope: {steepest:.1f} deg")
    print(f"deepest extruding move below layer top: {deepest:.3f} mm")
    print(f"problems: {len(problems)}")
    for p in problems[: a.max_report]:
        print("  " + p)
    if len(problems) > a.max_report:
        print(f"  ... {len(problems) - a.max_report} more")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
