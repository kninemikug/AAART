"""Category 5: mask_local queries (Q059 ~ Q070).

Distribution: 12 queries (factoid 6, complex 6 / usage 6, concept 2, ts 2, wf 2).
"""

from typing import Any, Dict, List
from scripts.query_seeds.common import slice_rawpedia_span


def get_queries() -> List[Dict[str, Any]]:
    return [
        {
            "slot_id": "Q059",
            "category": "mask_local",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:local_adjustments",
            "expected_behavior": "grounded_answer",
            "query": "RawPedia 설명 기준으로 Local adjustments의 RT-spots는 어떤 소프트웨어들의 U-Point 개념과 유사한 원리로 동작하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/local_adjustments.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "local_adjustments.md",
                        "RT-spots, which are similar in",
                        "Capture NXD.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q060",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:local_adjustments",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee Local adjustments에서 RT-spot을 구성하는 요소(중심점 C 및 4개 경계점 TBLR)와 이를 기반으로 형성되는 3가지 그래디언트(Dissymetry, Transition, Color)의 동작 방식은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/local_adjustments.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "local_adjustments.md",
                        "When the user selects an RT-spot, the image on the screen shows:",
                        "(left), R (right) whose positions can be varied with the mouse or\n  cursors.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/local_adjustments.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "local_adjustments.md",
                        "### The 3 types of gradient",
                        "point for the start of the gradient.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q061",
            "category": "mask_local",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Local_Lab_Controls",
            "expected_behavior": "grounded_answer",
            "query": "Local Lab Controls에서 컨트롤 포인트 조작 편의를 위해 도입된 GUI 인터페이스의 특징과 긴 메뉴 회피 설계는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Local_Lab_Controls.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Local_Lab_Controls.md",
                        "control points, as done in Nik Software.",
                        "nor code\nportability.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Local_Lab_Controls.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Local_Lab_Controls.md",
                        "In order to improve manipulation and avoid long menus on screen, I added",
                        "used in the Wavelet tab,",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q062",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Local_Lab_Controls",
            "expected_behavior": "grounded_answer",
            "query": "Local Lab Controls에서 Scope 슬라이더 조절 시 각 사분면(quadrant)에서 tint 및 deltaE(색차) 기반으로 적용량을 계산하는 알고리즘 원리와, 슬라이더 값을 증감할 때의 선택 영역 변화는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Local_Lab_Controls.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Local_Lab_Controls.md",
                        "- For each quadrant, depending on the the value of the “Scope” slider,",
                        "based on the specific the case.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Local_Lab_Controls.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Local_Lab_Controls.md",
                        "- By increasing the value of “Scope”, progressively more of the selected",
                        "the reference zone.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q063",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Spot_Removal",
            "expected_behavior": "grounded_answer",
            "query": "Spot Removal 도구에서 새로운 스팟을 추가할 때 마우스 조작 방법(Ctrl-click 및 드래그)은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Spot_Removal.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Spot_Removal.md",
                        'Ctrl-click on the location that you want to mask ("destination", solid',
                        'area of the\ndestination.',
                    ),
                }
            ],
        },
        {
            "slot_id": "Q064",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Spot_Removal",
            "expected_behavior": "grounded_answer",
            "query": "Spot Removal 도구에서 기존 스팟을 제거하는 마우스 조작 방법과 스팟 편집 모드를 토글하는 절차는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Spot_Removal.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Spot_Removal.md",
                        "### Removing spots",
                        "Right click on any part of the spot to remove it.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Spot_Removal.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Spot_Removal.md",
                        "### Activate spot editing mode",
                        '![edit-point.png>](edit-point.png "edit-point.png") button.',
                    ),
                },
            ],
        },
        {
            "slot_id": "Q065",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Graduated_Filter",
            "expected_behavior": "grounded_answer",
            "query": "Graduated Filter 도구는 실제 어떤 사진 광학 필터를 모방하며 주로 어떤 상황에 사용되나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Graduated_Filter.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Graduated_Filter.md",
                        "The graduated filter tool simulates a real neutral density graduated",
                        "limit the brightness of the sky.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q066",
            "category": "mask_local",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Graduated_Filter",
            "expected_behavior": "grounded_answer",
            "query": "Graduated Filter 도구의 적용 강도(Strength) 단위는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Graduated_Filter.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Graduated_Filter.md",
                        "The strength of the filter, in stops.",
                        "in stops.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q067",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Vignetting_Filter",
            "expected_behavior": "grounded_answer",
            "query": "Vignetting Filter 도구에서 크롭(Crop)이 적용되었을 때 비네팅 효과는 어디를 기준으로 배치되나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Vignetting_Filter.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Vignetting_Filter.md",
                        "This vignetting filter is placed relative to the crop, if",
                        "cropping is used.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q068",
            "category": "mask_local",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Vignetting_Filter",
            "expected_behavior": "grounded_answer",
            "query": "Vignetting Filter에서 예술적 비네팅과 렌즈 광량 저하(Flat-Field/Raw Tab) 보정의 차이점 및 원형/직사각형 모양 제어 방식은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Vignetting_Filter.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Vignetting_Filter.md",
                        "For correcting vignetting caused by the lens light fall-off (as opposed",
                        "[Flat Field](flat_field) tool.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Vignetting_Filter.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Vignetting_Filter.md",
                        "The roundness slider controls the geometry of the filter.",
                        "the range 50 to 100.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q069",
            "category": "mask_local",
            "intent": "workflow",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Preview_Modes",
            "expected_behavior": "grounded_answer",
            "query": "Preview Modes에서 Focus mask의 미리보기 목적은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Preview_Modes.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Preview_Modes.md",
                        "Focus mask, to see which areas are in focus",
                        "which areas are in focus",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q070",
            "category": "mask_local",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Tutorials/game_changer/rocks",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee 설명 기준 튜토리얼(rocks.md)에서 Selective Editing 시 몇 개의 RT-spots를 사용하며 첫 번째 spot에는 어떤 도구(GHS 등)가 적용되었나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Tutorials/game_changer/rocks.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Tutorials/game_changer/rocks.md",
                        "Selective Editing - 5 RT-spots",
                        "Selective Editing - 5 RT-spots",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Tutorials/game_changer/rocks.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Tutorials/game_changer/rocks.md",
                        "### First spot : Generalized hyperbolic stretch (GHS)",
                        "### First spot : Generalized hyperbolic stretch (GHS)",
                    ),
                },
            ],
        },
    ]
