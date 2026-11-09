"""Twenty fixed T19 inputs; frozen before live generation, all use sample1.nef."""

# Expected numeric tuples describe direction; exact numbers describe explicit requests.
CASES = [
    ("E01", "조금 밝게 해줘", {"Exposure.Compensation": (0, 12)}),
    ("E02", "조금 어둡게 해줘", {"Exposure.Compensation": (-12, 0)}),
    ("E03", "노출 +0.75 EV", {"Exposure.Compensation": 0.75}),
    ("E04", "노출 -0.4 EV", {"Exposure.Compensation": -0.4}),
    ("E05", "아주 약하게 밝게 해줘", {"Exposure.Compensation": (0, 12)}),
    ("E06", "어두운 사진이지만 노출은 -0.2 EV로 해줘", {"Exposure.Compensation": -0.2}),
    ("W01", "촬영 WB 유지", {"White Balance.Setting": "Camera"}),
    ("W02", "WB 5500 K", {"White Balance.Temperature": 5500, "White Balance.Green": 1}),
    ("W03", "색온도 6500 K Green=1.1", {"White Balance.Temperature": 6500, "White Balance.Green": 1.1}),
    ("W04", "화이트밸런스 4200 K Green=0.9", {"White Balance.Temperature": 4200, "White Balance.Green": 0.9}),
    ("S01", "채도 조금 올려줘", {"Saturation.Saturation": (0, 100)}),
    ("S02", "채도를 줄여줘", {"Saturation.Saturation": (-100, 0)}),
    ("S03", "채도를 12로 설정", {"Saturation.Saturation": 12}),
    ("S04", "생동감 18로 설정", {"Saturation.Vibrance": 18}),
    ("C01", "노출 +0.3 EV, 채도 -8", {"Exposure.Compensation": 0.3, "Saturation.Saturation": -8}),
    ("C02", "밝게 하고 채도 조금 올려줘", {"Exposure.Compensation": (0, 12), "Saturation.Saturation": (0, 100)}),
    ("C03", "노출 +0.25 EV, WB 5000K", {"Exposure.Compensation": 0.25, "White Balance.Temperature": 5000}),
    ("C04", "노출 -0.25 EV, WB 5500K Green=1.05", {"Exposure.Compensation": -0.25, "White Balance.Temperature": 5500, "White Balance.Green": 1.05}),
    ("C05", "WB 6000K, 채도 -5", {"White Balance.Temperature": 6000, "Saturation.Saturation": -5}),
    ("C06", "노출 +0.5 EV, WB 5200K, 채도 +10, 생동감 +5", {"Exposure.Compensation": 0.5, "White Balance.Temperature": 5200, "Saturation.Saturation": 10, "Saturation.Vibrance": 5}),
]


def matches_request(profile, expected):
    """Check request fulfillment separately from profile format validity."""
    for name, wanted in expected.items():
        group, key = name.split(".")
        value = profile.get("groups", {}).get(group, {}).get(key)
        if isinstance(wanted, (tuple, list)):
            if type(value) not in (int, float) or not wanted[0] < value < wanted[1]:
                return False
        elif value != wanted:
            return False
    return True
