"""Category 3: demosaic_raw queries (Q035 ~ Q046).

Distribution: 12 queries (factoid 7, complex 5 / usage 3, concept 4, ts 3, wf 2).
"""

from typing import Any, Dict, List
from scripts.query_seeds.common import slice_rawpedia_span


def get_queries() -> List[Dict[str, Any]]:
    return [
        {
            "slot_id": "Q035",
            "category": "demosaic_raw",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Demosaicing",
            "expected_behavior": "grounded_answer",
            "query": "디지털 카메라 센서에서 가장 널리 사용되는 Bayer 필터의 2x2 컬러 매트릭스 구성은 어떻게 되나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Demosaicing.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Demosaicing.md",
                        'The "[Bayer filter](https://en.wikipedia.org/wiki/Bayer_filter)" is the most',
                        "green, blue, red and green\npatches.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q036",
            "category": "demosaic_raw",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Demosaicing",
            "expected_behavior": "grounded_answer",
            "query": "Dual Demosaic 방식(예: AMaZE+VNG4)의 영역 분할 장점과 연산상의 단점은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Demosaicing.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Demosaicing.md",
                        "The dual-demosaic methods, such as AMaZE+VNG4, allow you to demosaic",
                        "using the other\nalgorithm.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Demosaicing.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Demosaicing.md",
                        "The downside is that the image needs to\nbe demosaiced twice,",
                        "using a single demosaicing\nmethod.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q037",
            "category": "demosaic_raw",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Preprocessing",
            "expected_behavior": "grounded_answer",
            "query": "Preprocessing 단계에서 Hot pixel이 발생하는 물리적 원인은 센서에서 어떻게 설명되나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Preprocessing.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Preprocessing.md",
                        'Hot pixels" appear as bright and saturated',
                        "outputting a higher current than it should.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q038",
            "category": "demosaic_raw",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Preprocessing",
            "expected_behavior": "grounded_answer",
            "query": "센서 제조 공정의 한계로 두 초록 채널 간 감도 차이가 날 때 발생하는 보간 아티팩트와 Green equilibration의 임계값(threshold) 역할은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Preprocessing.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Preprocessing.md",
                        "Green equilibration suppresses interpolation artifacts that",
                        "response of the two green channels.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Preprocessing.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Preprocessing.md",
                        "The threshold sets the percentage",
                        "neighboring green values are equilibrated.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q039",
            "category": "demosaic_raw",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Flat-Field",
            "expected_behavior": "grounded_answer",
            "query": "Flat-Field 도구가 보정할 수 있는 렌즈 비네팅 및 렌즈 캐스트 현상과 플랫 필드 샷 촬영 시 권장 감도(ISO)는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Flat-Field.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Flat-Field.md",
                        "vignetting - a peripheral darkening of the image, more pronounced in the",
                        "luminance\nnon-uniformity of the image field.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Flat-Field.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Flat-Field.md",
                        "as the flat-field image gets\nblurred and should have a low ISO.",
                        "Shoot it at ISO-100 if possible.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q040",
            "category": "demosaic_raw",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Dark-Frame",
            "expected_behavior": "grounded_answer",
            "query": "장노출 사진에서 Dark-frame subtraction 기법이 대처할 수 있는 노이즈 유형들은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Dark-Frame.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Dark-Frame.md",
                        "[Dark-frame subtraction](https://en.wikipedia.org/wiki/Dark-frame_subtraction) is a",
                        "thermal, dark-current and fixed-pattern noise.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q041",
            "category": "demosaic_raw",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Raw_Black_Points",
            "expected_behavior": "grounded_answer",
            "query": "Raw Black Points 도구의 주된 사용 목적은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Raw_Black_Points.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Raw_Black_Points.md",
                        "It is unlikely you will ever need to use the Raw Black Points tool other",
                        "than for diagnostic purposes.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q042",
            "category": "demosaic_raw",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Raw_White_Points",
            "expected_behavior": "grounded_answer",
            "query": "Raw White Points 도구의 주된 사용 목적은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Raw_White_Points.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Raw_White_Points.md",
                        "It is unlikely you will ever need to use the Raw White Points tool other",
                        "than for diagnostic purposes.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q043",
            "category": "demosaic_raw",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Chromatic_Aberration",
            "expected_behavior": "grounded_answer",
            "query": "Raw Tab에 위치한 Chromatic Aberration 도구는 파이프라인의 어느 시점에서 작동하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Chromatic_Aberration.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Chromatic_Aberration.md",
                        'This "Chromatic Aberration" tool\nworks on the image **before** demosaicing,',
                        "that's why it's located in\nthe *Raw* tab.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q044",
            "category": "demosaic_raw",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:bit_depth",
            "expected_behavior": "grounded_answer",
            "query": "디지털 이미지에서 비트 심도가 높아질 때의 이점과 그에 따른 대가(트레이드오프)는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/bit_depth.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "bit_depth.md",
                        "The higher the bit depth, the more precisely a color can be described,",
                        "more RAM and more storage\nspace.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/bit_depth.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "bit_depth.md",
                        "Bit depth is expressed as a value which describes either the number of",
                        "**bits per pixel** (BPP), or **bits per channel** (BPC).",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q045",
            "category": "demosaic_raw",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Flat-Field",
            "expected_behavior": "grounded_answer",
            "query": "Flat-Field 도구의 Blur Radius 슬라이더의 기본값(32) 역할과 0으로 설정했을 때의 동작은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Flat-Field.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Flat-Field.md",
                        'The "Blur Radius" slider controls the degree of blurring of the',
                        "variations of raw data due to noise.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Flat-Field.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Flat-Field.md",
                        "Setting the blur\nradius to 0",
                        "skips the blurring process",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q046",
            "category": "demosaic_raw",
            "intent": "workflow",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Dark-Frame",
            "expected_behavior": "grounded_answer",
            "query": "다크 프레임 Auto-selection 모드 설정 시 RawTherapee가 최적의 매칭을 탐색하는 참조 디렉터리는 환경설정의 어디에 지정하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Dark-Frame.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Dark-Frame.md",
                        'Auto-Selection" and let RT choose the best\nmatch from the directory specified in',
                        '"[Preferences](preferences) \\> Image Processing \\>\nDark-Frame".',
                    ),
                }
            ],
        },
    ]
