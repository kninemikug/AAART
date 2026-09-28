"""Category 6: settings_workflow queries (Q071 ~ Q080).

Distribution: 10 queries (factoid 5, complex 5 / usage 3, concept 0, ts 1, wf 6).
"""

from typing import Any, Dict, List
from scripts.query_seeds.common import slice_rawpedia_span


def get_queries() -> List[Dict[str, Any]]:
    return [
        {
            "slot_id": "Q071",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Sidecar_Files_-_Processing_Profiles",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee에서 편집 중인 사이드카 처리 프로필(PP3)이 디스크에 실제 파일로 기록되는 시점이나 트리거 조건들은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Sidecar_Files_-_Processing_Profiles.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Sidecar_Files_-_Processing_Profiles.md",
                        "The processing profile is written to disk:",
                        "[keyboard shortcut](keyboard_shortcuts) from the\n  Editor tab.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q072",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Sidecar_Files_-_Processing_Profiles",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee에서 부분 처리 프로필(partial profile)을 적용할 때 Fill 모드와 Preserve 모드의 동작 차이 및 누락된 파라미터 처리 방식은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Sidecar_Files_-_Processing_Profiles.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Sidecar_Files_-_Processing_Profiles.md",
                        "The processing profile fill mode allows you to decide what happens when",
                        "overwriting any edits you have made.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Sidecar_Files_-_Processing_Profiles.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Sidecar_Files_-_Processing_Profiles.md",
                        '"Preserve" mode applies only those parameters that are available in',
                        "leaves missing values unchanged.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q073",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Saving_Images",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee에서 에디터 탭의 즉시 저장(Save immediately)을 실행했을 때 에디터의 반응성에 미치는 영향과 큐(Queue) 사용을 권장하는 이유는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Saving_Images.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Saving_Images.md",
                        'If you choose to "*Save\nimmediately*", RawTherapee will be busy saving your photo as soon as you',
                        "photos\nright away.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q074",
            "category": "settings_workflow",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Saving_Images",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee에서 동일한 원본 파일로 여러 버전을 저장할 때 파일명 덮어쓰기 충돌을 방지하는 옵션과 Save 창을 통해 큐에 보낼 때 개별 설정 장점은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Saving_Images.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Saving_Images.md",
                        'The benefit of putting it to the queue using the "*Save*" window is that',
                        '"[Queue](queue)" tab.',
                    ),
                },
                {
                    "source_path": "data/rawpedia/Saving_Images.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Saving_Images.md",
                        'There is an option in the "*Save current image*" window: "*Automatically',
                        "[Queue](queue).",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q075",
            "category": "settings_workflow",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Queue",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee의 Queue 설정 중 Use template에서 원본 파일명(%f), 상위 폴더(%d1), 절대 경로(%p1) 및 사진 등급(%r) 서식 문자의 치환 규칙은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Queue.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Queue.md",
                        "<b>`/home/tom/photos/2010-10-31/photo1.raw`</b>",
                        "'`<i>`001`</i>`'.`",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q076",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Queue",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee에서 큐 탭의 전역 설정 대신 Save 창의 설정을 강제 적용하는 조건(Force saving options)과 큐의 지속성(Persistence) 동작은 어떠한가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Queue.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Queue.md",
                        "The queue is persistent - you can exit RawTherapee and restart it later;",
                        "survive a\ncrash.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Queue.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Queue.md",
                        "The Queue has several settings, such as the output file format and",
                        "settings from the Queue tab will be used.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q077",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Creating_processing_profiles_for_general_use",
            "expected_behavior": "grounded_answer",
            "query": "범용으로 재사용 가능한 처리 프로필을 만들 때 필요한 파라미터만 부분 저장(Ctrl+Save)하는 방법과, 다양한 사진 간 호환성을 위해 노출값 대신 Auto Levels 사용 및 불필요한 설정(WB, 노이즈 감소 등) 배제를 권장하는 이유는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Creating_processing_profiles_for_general_use.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Creating_processing_profiles_for_general_use.md",
                        "Sometimes, you will want to save only a subset of the parameters",
                        "share these profiles with your friends or in our forum.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/Creating_processing_profiles_for_general_use.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Creating_processing_profiles_for_general_use.md",
                        "Remember that in order for a profile to be universally applicable to all",
                        "Double-check these things before sharing your\nprofiles.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q078",
            "category": "settings_workflow",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:batch_adjustments_-_sync",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee File Browser의 일괄 조정(Sync) 도구 패널에서 Set 모드와 Add 모드의 차이점(파라미터 교체 vs 기존 값 누적 가산)은 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/batch_adjustments_-_sync.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "batch_adjustments_-_sync.md",
                        'Your tweaks can either replace the existing ones ("Set"',
                        "photo which was not previously tweaked would have +0.6EV in both modes.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q079",
            "category": "settings_workflow",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:Resize",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee의 Resize(크기 조정) 도구는 파이프라인에서 언제 실행되며, 다운스케일링 시 디테일 손실을 보완하기 위해 제공되는 구성요소는 무엇인가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/Resize.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "Resize.md",
                        "Resizing is one of the last things to happen when saving an image - this",
                        '"Post-Resize Sharpening" component which you can use to make the\ndownscaled image crisp.',
                    ),
                }
            ],
        },
        {
            "slot_id": "Q080",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "rawtherapee_reference",
            "source_type": "rawpedia",
            "source_group_id": "rawpedia:file_paths",
            "expected_behavior": "grounded_answer",
            "query": "RawTherapee에서 config 폴더와 cache 폴더의 주요 역할 차이와, 용량 확보를 위해 캐시 내 images 서브폴더를 삭제했을 때 설정 유지 여부는 어떠한가요?",
            "evidence_specs": [
                {
                    "source_path": "data/rawpedia/file_paths.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "file_paths.md",
                        "The RawTherapee config folder contains:",
                        "regain all\nof your settings and custom processing profiles if you install\nRawTherapee on a new system.",
                    ),
                },
                {
                    "source_path": "data/rawpedia/file_paths.md",
                    "role": "support",
                    "span_text": slice_rawpedia_span(
                        "file_paths.md",
                        "The RawTherapee cache folder contains sets of cached items, where each",
                        "RawTherapee will just have to regenerate the\nthumbnails.",
                    ),
                },
            ],
        },
    ]
