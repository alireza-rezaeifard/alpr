import json

d = json.load(open("benchmarks/results/phase2d_safety.json",
                   encoding="utf-8"))
print("CLIPPING (real data):")
bad = {k: v for k, v in d["clipping_frequency_real_data"].items()
       if v["clipped"]}
print("  clipped crops:", bad if bad else "NONE — 0 clipping "
      "everywhere")
print()
print("EXPANSION MARGIN (cam2 small-crop regime, detector A):")
for k, v in d["expansion_margin_analysis"].items():
    if "cam2" in k and "detector_a" in k:
        print(f"  {k}: medianW={v['median_width']} "
              f"margin/side={v['linear_margin_per_side_px_at_median_width']}px "
              f"area_outside_box={v['area_fraction_outside_original_box']}")
print()
print("MULTI-BOX (real data):")
for k, v in d["multi_box_frames_real_data"].items():
    print(" ", k, v)
