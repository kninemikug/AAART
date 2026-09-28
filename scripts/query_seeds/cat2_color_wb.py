"""Category 2: color_wb queries (Q017 ~ Q034).

Distribution: 18 queries (factoid 10, complex 8 / usage 6, concept 7, ts 2, wf 3).
"""

from typing import Any, Dict, List
from scripts.query_seeds.common import slice_rawpedia_span


def get_queries() -> List[Dict[str, Any]]:
    return [
        {
            "slot_id": "Q017",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:White_Balance",
            "expected_behavior": "grounded_answer",
            "query": "White Balance 도구의 temperature 슬라이더는 어떤 색상 축을 기준으로 이미지를 조절하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/White_Balance.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "White_Balance.md",
                        "The temperature slider adjusts colors along the blue-yellow axis.",
                        "makes it warmer (yellowish).",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q018",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:White_Balance",
            "expected_behavior": "grounded_answer",
            "query": "RAW 이미지에서 화이트 밸런스가 RGB 채널 가중치로 변환될 때 클리핑 제어 방식과, Temperature correlation 알고리즘이 잘못된 결과를 낼 수 있는 조명 조건은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/White_Balance.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "White_Balance.md",
                        "The white balance is described in temperature and tint,",
                        "when the raw channel is clipped.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/White_Balance.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "White_Balance.md",
                        "This algorithm may give erroneous results:",
                        "values, etc.).",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q019",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Color_Management",
            "expected_behavior": "grounded_answer",
            "query": "Color Management에서 카메라 RAW 데이터를 내부 작업 색공간으로 변환할 때 입력 프로필(Input Profile)이 없으면 어떤 문제가 발생하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Color_Management.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Color_Management.md",
                        "This conversion requires an input profile made",
                        "accurate color representation is\nimpossible.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q020",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Color_Management",
            "expected_behavior": "grounded_answer",
            "query": "Color Management에서 기본 작업 프로필(Working Profile)의 권장 설정과 출력 프로필(Output Profile)의 동작 특성은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Color_Management.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Color_Management.md",
                        "The default working profile is ProPhoto and should not be changed for\nnormal use.",
                        "chrominance, etc.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Color_Management.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Color_Management.md",
                        "Specify the output color profile; the saved image will be transformed",
                        "cannot be seen in the\npreview.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q021",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Gamut_compression",
            "expected_behavior": "grounded_answer",
            "query": "Gamut Compression 도구의 기본 목적은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Gamut_compression.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Gamut_compression.md",
                        "Gamut Compression is a tool that allows you to compress highly chromatic",
                        "into a smaller gamut.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q022",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Gamut_compression",
            "expected_behavior": "grounded_answer",
            "query": "Gamut Compression 도구에서 Threshold 슬라이더의 동작 방식과 별표(*) 표시 작업공간의 사전 계산 임계값 특성은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Gamut_compression.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Gamut_compression.md",
                        "controls the percentage of the outer gamut that will be affected.",
                        "gamut core will not be affected.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Gamut_compression.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Gamut_compression.md",
                        "* Workspaces marked with an asterisk (*) have pre-calculated threshold values",
                        "artifacts.\n\n[Aces gamut",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q023",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Film_Simulation",
            "expected_behavior": "grounded_answer",
            "query": "Film Simulation 도구는 필름 색감을 재현하기 위해 어떤 포맷의 참조 이미지를 요구하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Film_Simulation.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Film_Simulation.md",
                        "This tool requires the use of reference images in the",
                        "HaldCLUT pattern, in either PNG or TIFF format.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q024",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Film_Simulation",
            "expected_behavior": "grounded_answer",
            "query": "Film Simulation용 아이덴티티 HaldCLUT를 직접 생성할 때 하이라이트 버그가 있어 사용을 피해야 하는 프로그램은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Film_Simulation.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Film_Simulation.md",
                        "If you need to generate your own identity HaldCLUT, do not use the",
                        "causes issues with highlights.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q025",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Lab_Adjustments",
            "expected_behavior": "grounded_answer",
            "query": "Lab 색공간에서 L 컴포넌트는 인간의 시각 인지와 어떻게 연관되나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Lab_Adjustments.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Lab_Adjustments.md",
                        "- The L component closely matches human perception of lightness.",
                        "closely matches human perception of lightness.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q026",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Lab_Adjustments",
            "expected_behavior": "grounded_answer",
            "query": "Lab Adjustments에서 Chromaticity 슬라이더의 동작 방식과 슬라이더를 -100으로 설정했을 때의 결과는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Lab_Adjustments.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Lab_Adjustments.md",
                        "The Lab Chromaticity slider increases or decreases the chromaticity",
                        "b-channels of Lab\nspace.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Lab_Adjustments.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Lab_Adjustments.md",
                        "Setting this slider to -100 removes all color,",
                        "black and white.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q027",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Vibrance",
            "expected_behavior": "grounded_answer",
            "query": "Vibrance 도구의 기본 개념과 Pastel Tones 및 Saturated Tones 슬라이더의 분리 제어 기능은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Vibrance.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Vibrance.md",
                        "*Vibrance* is an intelligent saturation adjustment tuned to correlate",
                        "color sensitivity of human vision.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Vibrance.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Vibrance.md",
                        "can separately control the vibrance of *pastel* tones",
                        "tones of high\nsaturation).",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q028",
            "category": "color_wb",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Vibrance",
            "expected_behavior": "grounded_answer",
            "query": "Vibrance 도구에서 피부톤이 채도 조정의 영향을 받지 않도록 보호하려면 어떤 옵션을 활성화해야 하나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Vibrance.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Vibrance.md",
                        "When enabled, colors closely resembling natural skin tones are not",
                        "affected by the vibrance adjustments.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q029",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Black-and-White_addon",
            "expected_behavior": "grounded_answer",
            "query": "Black-and-White 도구의 Color Filter는 어떤 방식으로 흑백 변환 결과에 영향을 주나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Black-and-White_addon.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Black-and-White_addon.md",
                        "The color filter simulates shootings with a colored filter placed in",
                        "front of the lens.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q030",
            "category": "color_wb",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Black-and-White_addon",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee에서 Black-and-White 도구를 사용하지 않고 흑백 이미지를 만드는 대안적인 절차들은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Black-and-White_addon.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Black-and-White_addon.md",
                        "Please note that Rawtherapee can produce black-and-white images without",
                        "the use of this tool:",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Black-and-White_addon.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Black-and-White_addon.md",
                        "1.  by setting the [Saturation](exposure#saturation) slider",
                        "tab to -100",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q031",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:RGB_and_Lab",
            "expected_behavior": "grounded_answer",
            "query": "RGB와 CIE Lab 색공간의 정의와 두 색공간 간 보정 차이에 대한 일반적인 의문은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/RGB_and_Lab.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "RGB_and_Lab.md",
                        "*[RGB](https://en.wikipedia.org/wiki/RGB_color_space)* and *[CIE L\\*a\\*b\\*]",
                        "describing colors.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/RGB_and_Lab.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "RGB_and_Lab.md",
                        "Many people wonder what the differences are between adjusting lightness,",
                        "in the Lab color space.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q032",
            "category": "color_wb",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Channel_Mixer",
            "expected_behavior": "grounded_answer",
            "query": "Channel Mixer 도구는 어떤 용도로 사용되며 출력 채널 섹션은 어떻게 구성되어 있나요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Channel_Mixer.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Channel_Mixer.md",
                        "The *Channel Mixer* is used for special effects, for color and",
                        "color output channels in a RGB image.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q033",
            "category": "color_wb",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:How_to_create_DCP_color_profiles",
            "expected_behavior": "grounded_answer",
            "query": "디지털 카메라 센서의 물리적 한계와 이를 보정하기 위해 DCP 프로필이 필요한 이유는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/How_to_create_DCP_color_profiles.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "How_to_create_DCP_color_profiles.md",
                        "Technically, each photosite in a digital photography camera's [image sensor]",
                        "Photon) of light that hit that\nphotosite.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/How_to_create_DCP_color_profiles.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "How_to_create_DCP_color_profiles.md",
                        'DNG camera profile" (DCP for short',
                        "Digital_Cinema_Package)).",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q034",
            "category": "color_wb",
            "intent": "workflow",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:icc_profile_creator",
            "expected_behavior": "grounded_answer",
            "query": "ICC Profile Creator 도구를 사용하여 사용자 정의 ICC 프로필을 생성할 때 지원되는 값 설정 방식은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/icc_profile_creator.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "icc_profile_creator.md",
                        "The ICC Profile Creator allows you to generate your own ICC profiles.",
                        "standard presets as well as custom values.",
                    ),
                }
            ],
        },
    ]
