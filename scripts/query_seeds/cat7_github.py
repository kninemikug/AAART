"""Category 7: GitHub queries (Q081 ~ Q100).

Distribution: 20 queries (factoid 6, complex 9, negative 5 / usage 7, concept 3, ts 6, wf 4).
12 curated candidate issues/discussions.
"""

from typing import Any, Dict, List
from scripts.query_seeds.common import slice_github_body_span


def get_queries() -> List[Dict[str, Any]]:
    return [
        {
            "slot_id": "Q081",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:412",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #412에 정리된 Windows 환경 ART 빌드 절차에서 MSYS2 환경 업데이트 및 패키지 설치 후 VS Code에서 설정해야 하는 CMake Kit과 Launch Target은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:412",
                    "curated_index": 0,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:412",
                        0,
                        "- Install [MSYS2](https://www.msys2.org)",
                        "`pacman -Syu`",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:discussion:412",
                    "curated_index": 0,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:412",
                        0,
                        "Open the command palette (Ctrl+Shift+P) and choose `CMake: Set Launch/Debug Target`.",
                        "Choose `art (Install)`.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q082",
            "category": "settings_workflow",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:420",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #420에서 Flatpak 기반 PhotoGIMP를 ART의 외부 편집기로 연동할 때 래퍼 셸 스크립트 작성 시 파일 인수를 어떻게 전달해야 하나요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:420",
                    "curated_index": 0,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:420",
                        0,
                        "The Rawtherapee's custom command:",
                        "@@u %U @@`",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:discussion:420",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:420",
                        1,
                        "Hi, try with a wrapper shell script, something like this:",
                        'org.gimp.GIMP "$1"\r\n```',
                    ),
                },
            ],
        },
        {
            "slot_id": "Q083",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:420",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #420에서 Flatpak 기반 외부 편집기를 연동하기 위해 래퍼 셸 스크립트를 작성하는 단계와, 이를 ART 환경설정(Preferences)에 등록할 때의 경로 지정 및 실행 권한 부여 절차는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:420",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:420",
                        1,
                        "Hi, try with a wrapper shell script, something like this:",
                        'org.gimp.GIMP "$1"\r\n```',
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:discussion:420",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:420",
                        1,
                        "If you call the script e.g.  `photogimp.sh`, then simply specify its path in the preferences",
                        "(and make sure that the script is actually executable)",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q084",
            "category": "color_wb",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:424",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #424 설명 기준, ART의 Film Simulation에서 LUT가 점 단위(point-wise) 연산만 지원하여 halation과 grain을 직접 포함하지 못하는 기술적 이유와 ART 내의 대체 도구 경로는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:424",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:424",
                        1,
                        'ART uses a LUT for the film simulations. This means that it can only apply "point-wise" functions',
                        'specifically in "Local Editing -> Smoothing" (mode "Halation" for halation, and mode "Add noise" for grain).',
                    ),
                }
            ],
        },
        {
            "slot_id": "Q085",
            "category": "settings_workflow",
            "intent": "workflow",
            "difficulty": "factoid",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:440",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #440 설명 기준으로, ART의 파일 브라우저 컨텍스트 메뉴에 별도의 'Move(이동)' 메뉴가 없을 때 파일을 다른 폴더로 이동시키는 공식 대안 기능은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:440",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:440",
                        1,
                        "There's rename which also works as a move.",
                        "HTH",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q086",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:442",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #442에서 한 도구에서 생성한 마스크를 다른 도구에서 재사용하려 할 때 마스크에 이름을 부여하는 방법과, 파이프라인에서 Linked mask가 나타나는 후속(subsequent) 도구들의 순서 조건은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:442",
                    "curated_index": 0,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:442",
                        0,
                        "Now I want to reuse this same mask elsewhere ... but I don't see / find a way how to refer to it.",
                        "How can I achieve the intended reuse?",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:discussion:442",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:442",
                        1,
                        "You just have to give a name to the mask, and then it will appear in subsequent tools as a \"Liked mask\".",
                        "(the order is the same as you see on the screen, from top to bottom).",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q087",
            "category": "mask_local",
            "intent": "concept",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:442",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #442 설명 기준, 마스크 재사용 시 파이프라인 후속 도구에 대한 Linked mask 연결 방식과 일반 복사/붙여넣기(copy/paste) 방식의 파이프라인 방향 제약 및 파라메트릭 마스크 결과 차이는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:442",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:442",
                        1,
                        '"Subsequent" here means that the tool / region follows the one in which you originally defined the mask in the processing pipeline',
                        "(the order is the same as you see on the screen, from top to bottom).",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:discussion:442",
                    "curated_index": 2,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:442",
                        2,
                        "However, you can copy/paste a mask from a tool to another freely.",
                        "depend on where they are applied in the pipeline), but should be close enough to give you a reasonable starting point.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q088",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "factoid",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:489",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #489 설명 기준으로, ART에서 타원형(ellipse) 마스크를 생성하고자 할 때 권장되는 설정 조작법은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:489",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:489",
                        1,
                        "You can just use a rectangle mask and set roundness to 100%.",
                        "HTH",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q089",
            "category": "settings_workflow",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:494",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Discussion #494에서 Fedora 환경의 Flatpak 패키지로 설치한 ART가 홈 디렉토리 외의 로컬 디스크 드라이브에 접근하지 못할 때 제시된 의심 원인과 검증된 해결 방법은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:494",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:494",
                        1,
                        "I am using the flatpack that was suggested by the Fedora Discover package, I am running\nFedora 44, KDE Plasma.",
                        "The menu does not list internal disk drives and manually enetering the path does nothing at all.",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:discussion:494",
                    "curated_index": 2,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:494",
                        2,
                        "I think it runs in a sandbox and that might be the reason for this behaviour.",
                        "Maybe you can try with the appimage that is available here on GitHub?",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:discussion:494",
                    "curated_index": 3,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:494",
                        3,
                        "I tried the appimage, it works perfectly :)",
                        "Thank you for your help!",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q090",
            "category": "demosaic_raw",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:issue:477",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Issue #477에서 Sony Alpha A7 V 무손실 .ARW 파일 열기 시 톤 커브 왜곡 및 검은 테두리 버그가 보고되었을 때 사용자의 실제 빌드로 정상 동작이 확인된 ART 소스 트리 계열은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:issue:477",
                    "curated_index": 2,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:477",
                        2,
                        "I built the latest master and the Sony A7 V raw files work perfectly now.",
                        "Thanks for the quick fix",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q091",
            "category": "settings_workflow",
            "intent": "concept",
            "difficulty": "factoid",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:issue:500",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Issue #500 설명 기준, ART의 JPEG XL(JXL) 이미지 내보내기 시 세부 압축 설정 옵션의 제공 여부와 고정된 품질 기준은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:issue:500",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:500",
                        1,
                        "Yes, there's no option.",
                        'The quality is fixed to "visually lossless"',
                    ),
                }
            ],
        },
        {
            "slot_id": "Q092",
            "category": "demosaic_raw",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:issue:516",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Issue #516에서 Canon EOS R8 RAW 파일이 흰색으로 표시될 때 구형 빌드 스크립트로 생성한 자가 빌드와 AppImage 간의 동작 차이 및 썸네일 정상화를 위해 확인된 조치는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:issue:516",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:516",
                        1,
                        "I've tried two versions: self-built and the AppImage.",
                        "- AppImage shows white in browser, but the actual image in the editor",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:issue:516",
                    "curated_index": 2,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:516",
                        2,
                        "That build script is very outdated, sorry about that.",
                        "if you clear the cache also the thumbnail should be fine.",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:issue:516",
                    "curated_index": 3,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:516",
                        3,
                        "Thanks, can confirm cache clearing helped - will use the AppImage going fwd!",
                        "will use the AppImage going fwd!",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q093",
            "category": "settings_workflow",
            "intent": "troubleshooting",
            "difficulty": "factoid",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:issue:521",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Issue #521에서 Xubuntu 사용자가 렌즈 보정 프로필 드롭다운이 비활성화되는 문제를 해결하기 위해 ART의 options 파일에 설정한 lensfun db 경로는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:issue:521",
                    "curated_index": 2,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:521",
                        2,
                        "On my system the lensfun db is at /usr/share/lensfun/**version_1**",
                        "After setting that path in ARTs option file, everything works as usual and no grayed-out dropdowns any more.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q094",
            "category": "mask_local",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:issue:524",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Issue #524에서 1.26.8 릴리스 및 1차 나이틀리 빌드(ART-165b246-linux64)에서 여전히 발생했던 크래시 증상과 최종적으로 해결이 확인된 나이틀리 빌드 식별자는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:issue:524",
                    "curated_index": 1,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:524",
                        1,
                        "I have downloaded the ART-165b246-linux64.tar.xz release, and installed it to test.",
                        "nightly binary does work occasionally, but not reliably  I'm afraid.",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:issue:524",
                    "curated_index": 3,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:524",
                        3,
                        "I have tested the new nightly build b11089b-linux64, and it works fine,",
                        "move around without any freezes or crashes.",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q095",
            "category": "mask_local",
            "intent": "troubleshooting",
            "difficulty": "complex",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:issue:524",
            "expected_behavior": "grounded_answer",
            "query": "GitHub Issue #524에서 스팟 제거 활성화 후 100% 확대 시 발생하는 동결/크래시 버그의 구체적인 재현 절차와 개발자가 안내한 Debug 빌드 생성 옵션은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:issue:524",
                    "curated_index": 0,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:524",
                        0,
                        "open the RAW in ART, apply the arp profile, then zoom into 100%",
                        "freezes for 20sec then crashes.",
                    ),
                },
                {
                    "cand_id": "github:artraweditor/ART:issue:524",
                    "curated_index": 2,
                    "role": "support",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:524",
                        2,
                        "To get a debug build, just replace `-DCMAKE_BUILD_TYPE=Release` with `-DCMAKE_BUILD_TYPE=Debug`",
                        "(configure and build ART)",
                    ),
                },
            ],
        },
        {
            "slot_id": "Q096",
            "category": "settings_workflow",
            "intent": "usage/how-to",
            "difficulty": "negative",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:issue:500",
            "expected_behavior": "unsupported_or_insufficient_evidence",
            "query": "GitHub Issue #500 설명 기준으로, ART의 내보내기 대화상자에서 JPEG XL(JXL) 전용 품질 슬라이더를 활성화하여 압축 품질을 50으로 직접 설정하는 절차는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:issue:500",
                    "curated_index": 1,
                    "role": "counterevidence",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:issue:500",
                        1,
                        "Yes, there's no option.",
                        'The quality is fixed to "visually lossless"',
                    ),
                }
            ],
        },
        {
            "slot_id": "Q097",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "negative",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:424",
            "expected_behavior": "unsupported_or_insufficient_evidence",
            "query": "GitHub Discussion #424 설명 기준으로, Film Simulation 모듈 내의 3D LUT 파일 하나만을 사용하여 주변 픽셀을 참조하는 halation(빛 번짐) 공간 연산을 직접 구현 및 적용하는 설정 절차는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:424",
                    "curated_index": 1,
                    "role": "counterevidence",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:424",
                        1,
                        'Both halation and grain are "spatial" operations, that need to look at a neighborhood of each pixel, and are not possible to implement with a LUT.',
                        "That's why they are not available in the film simulations.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q098",
            "category": "color_wb",
            "intent": "usage/how-to",
            "difficulty": "negative",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:424",
            "expected_behavior": "unsupported_or_insufficient_evidence",
            "query": "GitHub Discussion #424 설명 기준으로, Film Simulation LUT 자체 내부에서 공간 연산(spatial operation) 알고리즘을 구동하여 픽셀 이웃 기반의 필름 그레인(film grain)을 직접 생성하도록 설정하는 방법은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:424",
                    "curated_index": 1,
                    "role": "counterevidence",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:424",
                        1,
                        'ART uses a LUT for the film simulations. This means that it can only apply "point-wise" functions, i.e. effects that look at a single pixel at a time.',
                        "are not possible to implement with a LUT.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q099",
            "category": "mask_local",
            "intent": "usage/how-to",
            "difficulty": "negative",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:442",
            "expected_behavior": "unsupported_or_insufficient_evidence",
            "query": "GitHub Discussion #442 설명 기준으로, 파이프라인 뒤쪽에 위치한 도구에서 정의한 named mask를 파이프라인 앞쪽(upstream) 도구에 동적 'Linked mask'로 직접 연결하여 사용하는 절차는 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:442",
                    "curated_index": 2,
                    "role": "counterevidence",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:442",
                        2,
                        "you are right, you can only reuse masks in tools that appear later in the pipeline.",
                        "and I have no plans of changing it in the near future, sorry.",
                    ),
                }
            ],
        },
        {
            "slot_id": "Q100",
            "category": "mask_local",
            "intent": "workflow",
            "difficulty": "negative",
            "product_scope": "art_snapshot",
            "source_type": "github",
            "source_group_id": "github:artraweditor/ART:discussion:442",
            "expected_behavior": "unsupported_or_insufficient_evidence",
            "query": "GitHub Discussion #442 설명 기준으로, 파이프라인상 서로 다른 처리 위치를 갖는 도구 간에 parametric mask를 복사/붙여넣기할 때 생성되는 마스크 픽셀 결과가 완전히 100% 동일함을 강제 보장하는 워크플로우 설정법은 무엇인가요?",
            "evidence_specs": [
                {
                    "cand_id": "github:artraweditor/ART:discussion:442",
                    "curated_index": 2,
                    "role": "counterevidence",
                    "span_text": slice_github_body_span(
                        "github:artraweditor/ART:discussion:442",
                        2,
                        "The masks might not be identical (because the result of parametric masks depend on where they are applied in the pipeline),",
                        "give you a reasonable starting point.",
                    ),
                }
            ],
        },
    ]
