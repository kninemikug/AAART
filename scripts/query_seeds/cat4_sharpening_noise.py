"""Category 4: sharpening_noise queries (Q047 ~ Q058).

Distribution: 12 queries (factoid 7, complex 5 / usage 4, concept 3, ts 3, wf 2).
"""

from typing import Any, Dict, List
from scripts.query_seeds.common import slice_rawpedia_span


def get_queries() -> List[Dict[str, Any]]:
    return [
        {
            "slot_id": "Q047",
            "category": "sharpening_noise",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Capture_Sharpening",
            "expected_behavior": "grounded_answer",
            "query": "Capture Sharpening 도구는 촬영 시 광학적으로 발생하는 어떤 요인들로 인한 블러를 보정하기 위해 사용되나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Capture_Sharpening.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Capture_Sharpening.md",
                        "diffraction](https://www.cambridgeincolour.com/tutorials/diffraction-photography.htm),",
                        "[Gaussian-type blur](https://en.wikipedia.org/wiki/Gaussian_blur)",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q048",
            "category": "sharpening_noise",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Capture_Sharpening",
            "expected_behavior": "grounded_answer",
            "query": "Capture Sharpening에서 RL Deconvolution 사용 시 아티팩트를 최소화하는 반경/임계값 설정 요령과 설정 변경의 전체 적용 범위는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Capture_Sharpening.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Capture_Sharpening.md",
                        "- with RL Deconvolution: find an appropriate radius value",
                        "keep artifacts (common with this tool) to a minimum.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Capture_Sharpening.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Capture_Sharpening.md",
                        "Any changes in the settings are applied to the whole image,",
                        "what the zoom level,",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q049",
            "category": "sharpening_noise",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Sharpening",
            "expected_behavior": "grounded_answer",
            "query": "Sharpening 도구의 Unsharp Mask 기법은 이미지의 어떤 시각적 특성을 향상시키는 전통적인 방식인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Sharpening.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Sharpening.md",
                        "[Unsharp masking](https://en.wikipedia.org/wiki/Unsharp_mask) (USM) is a",
                        "(edge contrast) of an\nimage",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q050",
            "category": "sharpening_noise",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Sharpening",
            "expected_behavior": "grounded_answer",
            "query": "Sharpening 도구에서 지나친 USM 샤프닝 시 후광을 억제하는 Halo Control의 동작 방식과 RL Deconvolution의 점 확산 함수(PSF) 기반 역변환 원리는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Sharpening.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Sharpening.md",
                        '"Halo Control" is used to avoid halo effects around light objects',
                        "USM filter.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Sharpening.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Sharpening.md",
                        "uses the [point spread function](https://en.wikipedia.org/wiki/Point_spread_function) (PSF) to",
                        "Gaussian-like blur.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q051",
            "category": "sharpening_noise",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Noise_Reduction",
            "expected_behavior": "grounded_answer",
            "query": "Noise Reduction 도구에서 휘도 노이즈(Luminance noise)와 색상 노이즈(Chrominance noise)에 대한 시각적 특성과 제거 필요성의 차이는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Noise_Reduction.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Noise_Reduction.md",
                        "Chrominance noise is endemic to digital images, it is generally",
                        "something you will always want to remove.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Noise_Reduction.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Noise_Reduction.md",
                        "Luminance noise, on the other hand, looks like film grain and can be",
                        "keep luminance noise.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q052",
            "category": "sharpening_noise",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Noise_Reduction",
            "expected_behavior": "grounded_answer",
            "query": "노이즈가 심한 고감도(예: ISO 6400) 사진에서 AMaZE 디모자이킹을 적용했을 때 어떤 아티팩트 패턴이 나타날 수 있나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Noise_Reduction.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Noise_Reduction.md",
                        "AMaZE demosaicing leads to small maze-like patterns.",
                        "small maze-like patterns.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q053",
            "category": "sharpening_noise",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Contrast_by_Detail_Levels",
            "expected_behavior": "grounded_answer",
            "query": "Contrast by Detail Levels 도구의 웨이블릿 분해 레벨 수와 Slider 0(Finest)부터 Slider 5까지의 대략적인 픽셀 반경은 얼마인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Contrast_by_Detail_Levels.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Contrast_by_Detail_Levels.md",
                        "wavelet decomposition to decompose the",
                        "image into six levels, each adjusted by a slider.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Contrast_by_Detail_Levels.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Contrast_by_Detail_Levels.md",
                        "Slider 0 (Finest) has\na pixel radius of 1,",
                        "2, 4, 8, 16 and 32 pixels.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q054",
            "category": "sharpening_noise",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Contrast_by_Detail_Levels",
            "expected_behavior": "grounded_answer",
            "query": "Contrast by Detail Levels 도구에서 특정 레벨 슬라이더 값을 1.0보다 작게 하거나 크게 할 때 로컬 대비는 각각 어떻게 변하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Contrast_by_Detail_Levels.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Contrast_by_Detail_Levels.md",
                        "Giving a slider a value less than 1.0",
                        "decreases local contrast at that level,",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Contrast_by_Detail_Levels.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Contrast_by_Detail_Levels.md",
                        "while giving it a higher value\nincreases it.",
                        "perceived sharpness of an\nimage,",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q055",
            "category": "sharpening_noise",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Edges_and_Microcontrast",
            "expected_behavior": "grounded_answer",
            "query": "Edges 도구가 일반적인 Unsharp Mask와 비교할 때 갖는 특징(후광, 노이즈 환경, 색공간)은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Edges_and_Microcontrast.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Edges_and_Microcontrast.md",
                        "Unlike *[Unsharp Mask](sharpening#unsharp_mask)*, *Edges* is",
                        "works in the Lab color space.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q056",
            "category": "sharpening_noise",
            "intent": "workflow",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Edges_and_Microcontrast",
            "expected_behavior": "grounded_answer",
            "query": "Microcontrast의 정의와 저주파 영역 대비를 다루는 local contrast와의 차이점은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Edges_and_Microcontrast.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Edges_and_Microcontrast.md",
                        '"Microcontrast" can be defined as contrast on a pixel',
                        '(lower frequency) areas.',
                    ),
                }
            ],
        },
        {
            "slot_id": "Q057",
            "category": "sharpening_noise",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Impulse_Noise_Reduction",
            "expected_behavior": "grounded_answer",
            "query": "Impulse Noise Reduction 도구는 어떤 형태의 노이즈를 제거하기 위해 사용되며 파이프라인의 어느 시점에서 작동하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Impulse_Noise_Reduction.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Impulse_Noise_Reduction.md",
                        "salt and pepper sprinkled over a photo. This is done after\ndemosaicing.",
                        "This is done after\ndemosaicing.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q058",
            "category": "sharpening_noise",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Defringe",
            "expected_behavior": "grounded_answer",
            "query": "Defringe 도구가 다루는 퍼플 프린지(Purple fringes)는 색수차의 어떤 형태이며 주로 어떤 가장자리에서 발생하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Defringe.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Defringe.md",
                        "Purple fringes are a form\nof axial (or longitudinal) chromatic aberration,",
                        "adjacent to bright areas",
                    ),
                }
            ],
        },
    ]
