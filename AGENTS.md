# PROJECT KNOWLEDGE BASE

**Scope:** ART core repository and its external agentic AI pipeline.

## OVERVIEW

ART is a cross-platform RAW image editor, GPL-3 fork of RawTherapee (C++11/C11, GTK3/gtkmm, CMake ≥3.9). The repository also contains an external agentic pipeline around ART: LangGraph + RAG + `.arp` profile generation + ART-cli rendering.

**Execution authority for the pipeline:** `docs/ART_agentic_wbs.md` (v2.5, 2026-09-02; 12주, 9/1–11/21, 169h 계획). Scope is Master Q&A/RAG and FiveK correction recommendation only. Feedback summarization and translation are out of scope.

## STRUCTURE

```
AAART/
├── rtengine/            # processing engine (demosaic, color, tone, noise) — vendored jpeg_ijg/, klt/
├── rtgui/               # GTKmm GUI + ART-cli headless binary (main.cc, main-cli.cc)
├── rtdata/              # runtime data: iccprofiles, .arp profiles, luts, themes, languages, options
├── doc/                 # manpage only (doc/manpage/ART.1)
├── docs/                # strategy doc + agentic execution WBS
├── cmake/               # find-modules (FindKLT, FindMacIntegration, FindUnalignedMalloc, FindX87Math)
├── scripts/             # agentic pipeline build, RAW sample, corpus collection, integration test scripts
├── data/                # pipeline sample RAW/profile and corpus data
├── tools/               # dev utilities: build-art, bundle_ART.py, generate* scripts, wb/icc tools
├── licenses/            # third-party licenses (SLEEF, libiomp5, DroidSansMono, jdatasrc)
├── venv/                # Python 3.14 venv for agentic scripts — NOT git-tracked
├── .worktrees/          # local worktrees — gitignored
└── .serena/ .omo/ .codegraph/ .agents/   # local agent tooling state — NOT part of the codebase
```

## WHERE TO LOOK

| Task | Location | Notes |
|---|---|---|
| ART-cli (headless processing) | `rtgui/main-cli.cc` | entry `main()`; flags in `rtgui/printhelp.h` |
| GUI app | `rtgui/main.cc` | GTKmm entry point |
| Processing pipeline | `rtengine/improccoordinator.cc`, `rtengine/improcfun.cc` | full pipeline orchestration and core processing |
| RAW decoding | `rtengine/dcraw.c` | vendored dcraw — do not modernize |
| Build targets | `rtgui/CMakeLists.txt` | `art` + `art-cli` executables, `rtengine` library |
| CI | `.github/workflows/` | Linux/macOS/Windows builds and source tarball |
| Release tooling | `tools/generateSourceTarball`, `tools/generateReleaseInfo` | invoked by `source.yml` |
| CLI flag reference | `rtgui/printhelp.h` | authoritative; `doc/manpage/ART.1` is stale |
| Pipeline scope and schedule | `docs/ART_agentic_wbs.md` | current authority |
| Pipeline architecture and detailed tasks | `tasks/plan.md`, `tasks/todo.md` | dependency graph and task cards |
| `.arp` keys for generation | `docs/arp_schema.md` + `rtgui/ppversion.h` | format/version coupling |
| Pipeline corpus | `data/rawpedia/`, `data/issues/` | RawPedia and ART GitHub sources |

## CODE MAP

| Symbol | Type | Location | Role |
|---|---|---|---|
| `main` | fn | `rtgui/main.cc` | GUI entry |
| `main` | fn | `rtgui/main-cli.cc` | batch processing, `--make-icc`, `--check-lut` |
| `process` | fn | `rtengine/improccoordinator.cc` | full pipeline orchestration |
| `process` | fn | `rtengine/improcfun.cc` | core image processing |
| `ART_print_help` | fn | `rtgui/printhelp.h` | authoritative CLI flag reference |
| `rtengine` | lib | `rtengine/CMakeLists.txt` | shared engine library |
| `art` / `art-cli` | exe | `rtgui/CMakeLists.txt` | output names `ART` / `ART-cli` |
| `guidedFilter` | fn | `rtengine/guidedfilter.cc` | edge-preserving filter |

## CONVENTIONS

- **커밋 및 PR 국문 작성 원칙:** 모든 커밋 메시지와 GitHub Pull Request(PR)의 제목 및 본문 설명은 국문(한국어)으로 명확하고 간결하게 작성한다.
- **C++11 / C11** — set globally via `-std=c++11`/`-std=c11` in CMake flags, not per target. GCC ≥4.9 required.
- **Formatting:** `.clang-format` = LLVM base, IndentWidth 4, ColumnLimit 80, WebKit braces, no tabs, no short single-line if/loops.
- **Build defaults:** `CMAKE_BUILD_TYPE` forced to Release when empty; `-DNDEBUG` in release, `-D_DEBUG` in debug. ccache auto-enabled if present.
- **Options (defaults):** `OPTION_OMP`=ON, `ENABLE_MIMALLOC`=ON (required on Linux unless `WITH_SAN`), `ENABLE_LIBRAW`=ON, `ENABLE_OCIO`=ON, `ENABLE_CTL`=OFF, `ENABLE_SIMDE`=OFF, `ENABLE_LCMS_FAST_FLOAT`=ON, `WITH_LTO`/`WITH_SAN`/`WITH_PROF`/`BUILD_SHARED`=OFF.
- **Pipeline Python:** use the root Python 3.14 `venv/`; do not add `requirements.txt`. Scripts use argparse, docstrings, and a `main()` guard; Bash scripts use `set -e`.
- **Pipeline dependencies:** install only when a consuming task needs them and record the installation then. Do not predeclare a package list, model, configuration loader, or file layout.
- **Version coupling:** bump `PPVERSION` in `rtgui/ppversion.h` whenever the `.arp` format or tool behavior changes. PPVERSION의 도구 동작은 저장된 프로필의 해석·기본값·영상 처리 의미를 말한다. 이를 보존하는 IPC 전송·수명·동기화 변경은 회귀 검증 근거를 남겨 증가를 생략할 수 있다.

## ANTI-PATTERNS

- **NEVER build with `-ffast-math`** — it introduces artifacts; `rtgui/main.cc` and `rtgui/main-cli.cc` reject it.
- **No x86 intrinsics in `rtengine/helpersse2.h` / `helperavx.h`** — use GCC vector extensions (“Don't use intrinsics here”). The `#error` guards require `-msse2` / `-mavx`.
- **Do not “fix” warnings in vendored code** — `dcraw.c`, `cJSON.c`, `canon_cr3_decoder.cc`, `klt/`, and `jpeg_ijg/` intentionally suppress warnings.
- **No `floor()` in `LUT.h` hot paths** (negative-index truncation correctness); no `std::list` in `lcp.h`; do not call the functions marked “do not use in a loop” in `color.h` from loops.
- **Do not use CameraCalibration matrices for DNGs** (`dcraw.cc`, #4129); do not reuse a `ProcessingJob` after destroy or while processing; `RefreshMapEvent` must not combine with other events.
- **No in-source builds** — stale generated files cause CMake errors.
- **파이프라인 기능을 위한 `rtengine/`·`rtgui/` 수정은 원칙적으로 금지한다. 다만 실행 중 GUI의 로컬 IPC 파라미터 조정에 한해, 승인된 설계와 검증 계획에 따라 조건부로 허용한다.**
  - **허용 조건:** 대상 기능, 허용 파라미터, 지원 OS·편집 모드, 변경 예정 지점, PPVERSION 판정, GUI/CLI 회귀 항목을 착수 전에 기록한다. 외부 입력 검증, GUI 메인루프 전달, 편집 대상과 revision 검사, 종료 시 수명 관리를 갖춘다. 초기 상태는 기능 비활성화로 한다.
  - **허용 범위:** `rtgui/`의 로컬 수신, GUI 명령 처리, 패널·히스토리·저장 상태 동기화, 편집기 열기·닫기 관리와 필요한 GUI 빌드 등록. `rtengine/`은 기존 단계의 안전한 파라미터 전달, 확인된 공유 상태의 동기화, 세대 번호를 포함한 프레임 통지에 필요한 최소 변경으로 한정한다. 기존 명시 파일에 대한 `main-cli.cc` 처리 예외는 유지한다.
  - **유지하는 금지 사항:** 실행 중 `ProcessingJob` 수정·재사용·destroy, 무보호 파라미터/이미지 버퍼 교환, `MINUPDATE`와 다른 이벤트 결합, 미검증 무효화 범위 축소, 헤드리스 상주화, 미인증 외부 네트워크 공개, vendored 코드 정리를 이 예외에 포함하지 않는다. 처리식·처리 순서·프로필 형식을 바꾸려면 이 예외를 확대 해석하지 않고 별도 설계와 PPVERSION 판정을 수행한다.
  - **검증 절차:** GUI·CLI 아웃오브소스 빌드, 기존 프로필 로드/저장/렌더 회귀, 수동 GUI 조작과 일치, 연속 요청·GUI 충돌·팬/줌·닫기/종료를 포함한 스레드/메모리 검사, 세대·오류 계약, 대상 OS의 화면 반영을 확인하고 결과를 기록한다. 하나라도 미검증이면 지원 범위를 한정하고 통과를 추측하여 보고하지 않는다. 공통 엔진 변경은 GUI와 CLI 양쪽의 회귀 결과를 필요로 한다.
- **Do not download the full FiveK dataset.** ART-cli confirmation uses 1–2 samples; the later recommendation subset and split follow WBS B-01/B-02.
- **Do not present Lightroom↔ART `.arp` mapping as exact.** Record mapping limits.

## UNIQUE STYLES

- ART-cli argument parsing uses `processLineParams` with per-OS console handling in `main-cli.cc`; `printhelp.h` is the flag source of truth.
- Theme retirement uses filename suffix `-DEPRECATED` matched in `rtgui/options.h:83` and the `GENERAL_DEPRECATED` i18n string.
- macOS/Windows GUI builds use `BUILD_BUNDLE`; Linux uses `bundle_ART.py` and AppImage, with `AppRun` dispatching `--cli` to ART-cli.
- CI build workflows trigger on version tags matching `[1-9].[0-9]+` or `[1-9].[0-9]+.[0-9]+` and `workflow_dispatch`; they do not run PR builds or CI tests. `mirror.yml` triggers on every push/delete. All platform builds produce x86_64 and arm64 artifacts: Linux tar.xz+AppImage, macOS .dmg, Windows .exe+.7z.

## COMMANDS

```bash
# GUI build (from repo root; creates build/)
cmake -DCMAKE_BUILD_TYPE=Release -B build && cmake --build build -j$(sysctl -n hw.logicalcpu 2>/dev/null || nproc) --target art
# → build/rtgui/ART

# CLI-only build
cmake --build build -j$(sysctl -n hw.logicalcpu 2>/dev/null || nproc) --target art-cli
# → build/rtgui/ART-cli   (target is lowercase art-cli, binary is ART-cli)

# Run ART-cli on a RAW with a profile
build/rtgui/ART-cli -a -Y -p <profile.arp> -c <raw-file>

# Pipeline integration test
./scripts/build_art_cli.sh && python3 scripts/download_sample_raw.py && ./scripts/test_art_cli.sh

# RawPedia RAG corpus fetch
python3 scripts/fetch_rawpedia.py -o data/rawpedia -s 50
```

## PIPELINE WORKING RULES

- **커밋·PR 언어:** 모든 파이프라인 태스크의 커밋 메시지와 PR 내용은 국문(한국어) 작성을 원칙으로 한다.
- The fixed 9/1~9/11 sequence is in WBS §5. Use `tasks/todo.md` for detailed acceptance criteria.
- Keep RawPedia source Markdown, ART GitHub source snapshots, search candidates, chunks, and vector-store state separately traceable.
- Chroma is the selected vector store. Do not choose an embedding model or final chunk rule before comparing candidates with the fixed question set.
- Generate structured profile data, validate it against `docs/arp_schema.md`, and use ART-cli rendering as the final format check.

## NOTES

- `-DENABLE_GUI=OFF` used by `build_art_cli.sh` is not a real CMake option; it is harmless intent documentation.
- No unit-test framework is wired into CMake; `rtengine/rtetest.cc` and `rtgui/test_guidedfilter.cpp` are manual harnesses.
- `TODO.txt` at root is an in-flight scratchpad for profile-change/ParamsEdited refactoring and batch-mode CLI work.
- `tools/` has its own `AGENTS.md` for bundling, release, and camera-data tooling.
- `rtdata/` is mostly static data; its related conventions are documented in `rtgui/AGENTS.md`. Theme `-DEPRECATED` retirement and per-OS `options.*` conventions live there.
- Root JSONs (`camconst.json`, `dcraw.json`, `rt.json`, `wbpresets.json`) use C-style comments; strip comments before parsing.
- `doc/manpage/ART.1` is stale (July 2019): it lacks `--make-icc`, `--check-lut`, `-Ttype`, `-f`, `-V`, `--progress`, and `-b<16f|32>`. Update `printhelp.h`, not the manpage, when CLI flags change.
