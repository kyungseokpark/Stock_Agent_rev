# WO-004 · UI/UX 개편 — 다크+오렌지(시니어) 테마 · 점수기준 탭 · 실행/자동화

목적: ① 투박한 UI를 **다크+오렌지 시니어 친화 테마**로, ② **점수 산출 기준 탭** 추가, ③ **세력스캔 자동 포함 + 국장/미국장/둘다 실행** 으로 사용성 최대화.
대상: 주로 `desktop_app.py`(외형·UX). 점수 로직 변경 없음.

---

## A. 테마 (다크 + 오렌지, 시니어 친화)

확정 컨셉: 소프트 차콜 배경 + 오렌지 액센트. **아버님(시니어) 사용** → 고대비·큰 글씨·색맹 안전색. 순흑/순백 금지.

### 접근
- 1순위: `ttkbootstrap` 도입(`requirements_desktop.txt`). `ttkbootstrap.Window(themename="darkly")` + **primary를 오렌지로 오버라이드**. `bootstyle`로 강조.
- 폴백: 순수 `ttk`(clam) + 아래 토큰을 `ttk.Style`로 지정.

### 색 토큰(다크)
```
BG #1F2428 · SURFACE #2A3036 · SURFACE2 #323941 · BORDER #3D454E
TEXT #F2F4F6 · MUTED #B6BEC7
ACCENT #FB923C(오렌지) · ACCENT_STRONG #F97316 · SEL #3A2E22
POS #34D399 · NEG #F87171 · WARN #FBBF24
```
> 색맹: 상승/하락·등급을 **색만으로 구분 금지** — ▲/▼ + 텍스트 라벨 병행.

### 타이포(시니어용 상향) `Malgun Gothic`
```
Title 24 · Section 16 · Body 14 · Caption 12 · 핵심수치 16~18
최소 본문 13pt(12 이하 금지) · "글자 크게/보통" 토글(14↔16, 테이블·라벨 동시)
```
간격/형태: 카드 패딩 16~18 · rowheight 38 · 버튼 크게(클릭영역↑) · 라운드 8.

### 레이아웃
- 헤더: 좌 타이틀+서브카피, 우 상태배지(시장/실행상태, 색상).
- 사이드바: 카드(LabelFrame) 분리 — `조건 / 분석대상 / 분야(섹터) / 필터 / 실행 / 스케줄(WO-005) / 검색 / 진행`.
- 메인 탭: `Top 후보 / 전체 결과 / 상세·차트 / 점수 기준 / 요약`.
- 테이블: 헤더 굵게(SURFACE2), zebra(짝수 SURFACE2), 선택행 SEL(#3A2E22)+좌측 굵은 표시, 숫자 우측정렬.
- 상태 배지 색 태그: 판정(Strong=POS굵게/Candidate=ACCENT/Watchlist=WARN/Excluded=MUTED), 세력등급(강한유입=NEG/우세=WARN/중립=MUTED/약함=옅은회색/이탈=옅은파랑).
- 차트(matplotlib) 다크 통일: fig/axes BG #2A3036, 그리드 #3D454E, 종가선 TEXT, MA20 ACCENT, MA50 POS, 거래량 MUTED.
- 토글: 글자 크게/보통, **밝은(라이트) 테마 토글**(노안/난시 대비, 라이트도 오렌지 액센트).

### 시니어 접근성(필수)
대비 ≥7:1 목표 · 흐린 회색 글씨 금지 · 색+기호+텍스트 병행 · 순흑/순백 회피 · 클릭영역 크게 · 채도 높은 파랑 본문 회피.

---

## B. 점수 산출 기준 탭

신규 탭 **"점수 기준"** = (1)기준 설명 + (2)선택종목 분해.

### B-1. 기준 설명(레퍼런스) — 가중치·임계값은 **config에서 읽어 동적 표기**
- 차트점수(`scoring.py`): 추세(>MA20+10/>MA50+8/MA20>MA50+7/>MA200+5), 거래량(비≥1.5→15…), 모멘텀(RSI/수익률), MACD, 위치, 손익비, 패널티, 최종보정(`signal_weights`), 판정(≥80/65/50).
- 조정점수 = 최종 + 패턴보너스(`chart_type_bonus`) + 품질패널티.
- 세력점수(WO-003): real/proxy 서브신호+가중치, 등급 경계.
- 종합점수(WO-003): `w_chart×차트 + w_force×세력` + 결측 규칙.

### B-2. 선택종목 분해 — **이미 존재하는 행 컬럼 사용**
`trend_score, volume_score, momentum_score, macd_score, position_score, risk_reward_score, risk_penalty, base_score, vcp_score, rs_rank, chart_type_penalty, quality_penalty, final_score, adjusted_score` + (있으면) 세력 서브점수, `composite_score`. 표/막대로 기여도 표시.

### 구현
- `_build_criteria_tab()`: 상단 Text(영역1, config로 채움) + 하단 Treeview(영역2). `_on_row_selected`에서 분해 갱신. `_render_score_criteria(config)`는 시장 전환/실행 시 재생성.

### 검증
- [ ] 표시 가중치/임계값이 config와 일치(설정 바꾸면 탭도 바뀜). 항목 합이 base/final과 정합. 시장 전환 시 갱신.

---

## C. 실행/자동화 UX

### C-1. 세력스캔 자동 포함 (따로 클릭 X)
- 일반 스크리닝 실행 시 **세력점수·종합점수 자동 산출**(WO-003 `run_with_screening:true`).
- `main.run_screen` 끝에서 후보풀(유동성통과/거래대금 상위 `max_universe`)에 `compute_force_inflow`+종합점수 → 기본 정렬 `composite_score` 내림차순(토글 가능). 나머지는 `chart_only`.
- 단독 "세력 유입 스캔"은 **고급 옵션(하단 보조 버튼)**으로만 유지.
- 진행 로그 "세력유입 계산 320/500" 추가.

### C-2. 실행 버튼 3개로 단순화
| 버튼 | 동작 |
|------|------|
| **국장 실행** (Primary 오렌지 큰버튼) | KR(코스피+코스닥 기본, WO-002) |
| **미국장 실행** | US |
| **둘 다 실행** | KR→US 순차 자동, 둘 다 보관·탭 전환 |

- 기존 `run_market("한국"/"미국")` 재사용 + `run_both()` 신설(워커 스레드 순차, 진행 `[1/2 국장][2/2 미국장]`, 중복실행 방지). `_set_buttons_enabled`에 3종 반영.
- 결과는 `output/kr`·`output/us` 분리 저장, 상단 토글로 전환.

### 검증
- [ ] "국장 실행" 한 번에 차트·세력·종합 모두 채워짐(추가클릭 없음).
- [ ] 세력계산은 max_universe 내, 캐시 적중 시 빠름.
- [ ] "둘 다 실행" KR·US 순차 완료·토글 전환. 중복실행 방지.
- [ ] 기본 정렬 종합점수, 토글로 차트/세력 전환.

---

## 영향 파일
- `desktop_app.py`(테마·탭·버튼·run_both·정렬), `main.py`(세력·종합 자동 파이프라인), `configs/*.yaml`, `requirements_desktop.txt`, `build_windows_exe.bat`(ttkbootstrap 패키징/hiddenimports)

## 비고
- 외형 변경 전후 **수치·로직 불변**(검증). ttkbootstrap 미설치 시 폴백 정상 구동. 1920×1080/1280×720 레이아웃 유지.
