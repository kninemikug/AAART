"""Category 1: exposure_tone queries (Q001 ~ Q016).

Distribution: 16 queries (factoid 9, complex 7 / usage 6, concept 6, ts 3, wf 1).
"""

from typing import Any, Dict, List
from scripts.query_seeds.common import slice_rawpedia_span


def get_queries() -> List[Dict[str, Any]]:
    return [
        {
            "slot_id": "Q001",
            "category": "exposure_tone",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Exposure",
            "expected_behavior": "grounded_answer",
            "query": "RawPedia 설명에서 Auto Levels는 무엇을 분석해 Exposure 설정을 조정하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Exposure.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Exposure.md",
                        "The *Auto Levels* tool analyzes the histogram and then adjusts the",
                        "controls in the Exposure section to achieve a well-exposed image.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q002",
            "category": "exposure_tone",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Exposure",
            "expected_behavior": "grounded_answer",
            "query": "RawPedia 기준으로 하이라이트 복원(Highlight Reconstruction) 시 Color Propagation 방식의 동작 원리와 한계는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Exposure.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Exposure.md",
                        "This is the most powerful recovery method.",
                        "missing clipped\n    area.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Exposure.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Exposure.md",
                        "Its weakness is that it may\n    sometimes 'bleed' the incorrect colors,",
                        "slower than the other methods.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q003",
            "category": "exposure_tone",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Dynamic_Range_Compression",
            "expected_behavior": "grounded_answer",
            "query": "Dynamic Range Compression 도구의 Anchor 슬라이더는 어떤 역할을 하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Dynamic_Range_Compression.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Dynamic_Range_Compression.md",
                        "Biases the compression towards the shadows or highlights,",
                        "functioning as an exposure compensation.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q004",
            "category": "exposure_tone",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Dynamic_Range_Compression",
            "expected_behavior": "grounded_answer",
            "query": "Dynamic Range Compression을 적용할 때 압축 강도(Amount)와 로컬 대비(Detail) 슬라이더는 이미지 톤과 대비에 각각 어떤 영향을 주나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Dynamic_Range_Compression.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Dynamic_Range_Compression.md",
                        "Sets the strength of the compression.",
                        "observing the\nhistogram).",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Dynamic_Range_Compression.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Dynamic_Range_Compression.md",
                        "Sets how much local contrast is preserved.",
                        "negative values reduce the\ncontrast.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q005",
            "category": "exposure_tone",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Shadows & Highlights",
            "expected_behavior": "grounded_answer",
            "query": "Shadows & Highlights 도구에서 Lab 색공간 대신 RGB 색공간을 사용할 때의 장점과 주의할 점은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Shadows & Highlights.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Shadows & Highlights.md",
                        "Adjusting shadows and highlights in the RGB space preserves image",
                        "desaturate affected areas.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q006",
            "category": "exposure_tone",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Shadows & Highlights",
            "expected_behavior": "grounded_answer",
            "query": "Shadows & Highlights 도구에서 Tonal Width와 Radius 슬라이더는 효과 적용 범위를 각각 어떻게 제어하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Shadows & Highlights.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Shadows & Highlights.md",
                        "Shadows/Highlights Tonal Width allows you to control how bright an area",
                        "affected by the shadows slider.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Shadows & Highlights.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Shadows & Highlights.md",
                        "The value of the Radius slider influences the effective area",
                        "Shadows and Highlights sliders.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q007",
            "category": "exposure_tone",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Tone_Mapping",
            "expected_behavior": "grounded_answer",
            "query": "Tone Mapping 도구에서 Gamma 슬라이더의 동작 원리는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Tone_Mapping.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Tone_Mapping.md",
                        "Gamma moves the action of tone-mapping to shadows or highlights.",
                        "action of tone-mapping to shadows or highlights.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q008",
            "category": "exposure_tone",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Tone_Mapping",
            "expected_behavior": "grounded_answer",
            "query": "Tone Mapping 적용 후 만화 같은 과장된 외관(cartoonish appearance)이나 소프트 후광 문제가 발생할 때 어떤 옵션 값을 올려야 하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Tone_Mapping.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Tone_Mapping.md",
                        "In some cases tone mapping may result in a cartoonish appearance,",
                        "help fight some of these problems.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q009",
            "category": "exposure_tone",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Local_Contrast",
            "expected_behavior": "grounded_answer",
            "query": "Local Contrast 도구의 Amount 슬라이더는 이미지 대비에 어떤 영향을 주나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Local_Contrast.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Local_Contrast.md",
                        "Determines the overall strength of the effect. Higher values amplify the",
                        "blurred image, thereby\nincreasing contrast.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q010",
            "category": "exposure_tone",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Local_Contrast",
            "expected_behavior": "grounded_answer",
            "query": "Local Contrast 도구에서 Darkness Level과 Lightness Level 슬라이더는 각각 어떤 영역을 변경하며, 둘 다 0으로 설정하면 도구는 어떻게 동작하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Local_Contrast.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Local_Contrast.md",
                        'The "Darkness Level" parameter modifies only those areas',
                        "making the image lighter.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Local_Contrast.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Local_Contrast.md",
                        'The "Lightness Level" parameter works similarly,',
                        'effectively disables the tool.',
                    ),
                },
            ],
        },
        {
            "slot_id": "Q011",
            "category": "exposure_tone",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:RGB_Curves",
            "expected_behavior": "grounded_answer",
            "query": "RGB Curves 도구의 Luminosity Mode는 어떤 목적으로 사용되며, 다른 도구(HSV Equalizer, Channel Mixer)와 비교할 때 어떤 제어 특성을 갖나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/RGB_Curves.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "RGB_Curves.md",
                        "The purpose of *Luminosity Mode* in the *RGB Curves* tool is to alter",
                        "while keeping image color the same.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/RGB_Curves.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "RGB_Curves.md",
                        "The effect is somewhat similar to *V* changes in the",
                        "allow a finer\ncontrol.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q012",
            "category": "exposure_tone",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:RGB_Curves",
            "expected_behavior": "grounded_answer",
            "query": "RawPedia 설명 기준으로 RGB curves를 각 채널별로 다르게 적용하면 어떤 색조 효과를 연출할 수 있나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/RGB_Curves.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "RGB_Curves.md",
                        "Using RGB\ncurves one could make warmer highlights or colder shadows,",
                        "cross-processing effect, etc.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q013",
            "category": "exposure_tone",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Clipping_Indication",
            "expected_behavior": "grounded_answer",
            "query": "에디터의 클리핑 표시기(Clipping Indication)에서 clipped highlight 경고는 어떤 조건에서 표시되나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Clipping_Indication.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Clipping_Indication.md",
                        "The clipped **highlight** indicator will highlight areas where at least",
                        "at or above the specified highlight threshold.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q014",
            "category": "exposure_tone",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Haze_Removal",
            "expected_behavior": "grounded_answer",
            "query": "Haze Removal 도구 사용 시 안개 제거 효과가 가장 강하게 적용되는 영역을 시각적으로 확인하려면 어떤 기능을 켜야 하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Haze_Removal.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Haze_Removal.md",
                        "You can visualize which areas",
                        "more that area is dehazed.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q015",
            "category": "exposure_tone",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Soft_Light",
            "expected_behavior": "grounded_answer",
            "query": "Soft Light 도구는 어떤 소프트웨어의 블렌드 모드를 모방하며, 결과 이미지에 어떤 시각적 변화를 주나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Soft_Light.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Soft_Light.md",
                        "This tool emulates the effect of blending an image with a copy of itself",
                        'in ["soft-light"](https://en.wikipedia.org/wiki/Blend_modes#Soft_Light)\nmode in GIMP.',
                    ),
                },
                {
                    "source_path": "data/rawpedia/Soft_Light.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Soft_Light.md",
                        "The resulting image has a little extra contrast and",
                        "which is usually visually pleasing.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q016",
            "category": "exposure_tone",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Unclipped",
            "expected_behavior": "grounded_answer",
            "query": "Unclipped 프로필을 적용하여 저장할 때 요구되는 출력 ICC 프로필 조건과 권장 저장 파일 포맷은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Unclipped.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Unclipped.md",
                        "Ensure\n    that your output ICC profile is either v4,",
                        "linear tone response\n    curve v2.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Unclipped.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Unclipped.md",
                        "Save the image as either a 16-bit floating-point TIFF",
                        "32-bit\n    floating-point TIFF.",
                    ),
                },
            ],
        },
    ]
