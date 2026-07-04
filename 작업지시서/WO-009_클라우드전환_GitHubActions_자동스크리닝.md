# WO-009 · 클라우드 전환(1안) — GitHub Actions 자동 스크리닝 + 텔레그램 통지

작성일 2026-07-04 · 작성 Claude(스펙) · 구현 **Codex(repo)** · 리뷰 경석님

> **한 줄 목적.** PC를 꺼도 매일 정해진 시간에 스크리닝(+성과추적)이 클라우드(GitHub Actions)에서 자동 실행되고, 결과를 텔레그램으로 받아본다. 백테스트·개발·데스크톱 UI는 로컬에 유지한다.

---

## 0. 역할 분담 (확정)

| 작업 | 실행 위치 | 방식 |
|------|-----------|------|
| 일일 스크리닝 (US/KR) | **클라우드** | Actions cron, 장 마감 후 자동 |
| 성과 추적(update_tracking_results) | **클라우드** | 스크리닝에 내장(`auto_update_tracking: true`) — 별도 작업 불필요 |
| 텔레그램 통지 | **클라우드** | `--notify telegram`, 실패 시에도 에러 통지 |
| 리포트 열람 | 웹 | top5/claude_input_report를 정적 페이지로 게시 |
| 백테스트 | **로컬 기본** | 무겁고 비정기적 — 옵션으로 workflow_dispatch 수동 실행 지원 |
| 데스크톱 앱 / 개발 | 로컬 | 변경 없음 |

## 1. 사전 확인된 전환 조건 (이미 충족)

- `main.py`가 CLI 완결(`--market {us,kr} --auto --notify telegram`), tkinter 비의존. exit code 스케줄러 친화적.
- `get_telegram_credentials`가 **환경변수 우선**(`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`) → GitHub Secrets 바로 연결 가능.
- 상태 크기: `data/screener_history.db` 124KB(git 커밋 가능), `data/cache/ohlcv` 54MB(actions/cache 한도 10GB 내).

## 2. 구현 스펙

### 2-1. 워크플로 `.github/workflows/daily_screen.yml`

```yaml
name: daily-screen
on:
  schedule:
    - cron: "30 7 * * 1-5"    # 07:30 UTC = 16:30 KST → KR장 (15:30 마감 후)
    - cron: "0 22 * * 1-5"    # 22:00 UTC = 07:00 KST → US장 (동부 16:00 마감 후)
  workflow_dispatch:
    inputs:
      market: {description: "us/kr/both", default: "both"}
      run_backtest: {description: "true면 오프라인 백테스트도 실행", default: "false"}
concurrency: daily-screen    # 중복 실행 방지
```

- 잡 구성: `ubuntu-latest`, Python 3.12, `pip install -r requirements.txt`(데스크톱 전용 requirements_desktop.txt 제외).
- **cron 트리거 시 시간대로 market 자동 결정**: 07:30 UTC 실행이면 `--market kr`, 22:00 UTC면 `--market us` (스케줄 이벤트의 `schedule` 값으로 분기하거나 UTC 시각으로 판별). dispatch 시 input 사용.
- 실행: `python main.py --market <m> --auto --notify telegram`.
- GitHub cron은 UTC 기준이며 최대 ~15분 지연 가능 — 마감 직후가 아닌 여유 시각으로 설정(위 값 반영됨). 미국 서머타임 종료(11월~) 시 마감이 22:00 UTC로 밀리므로 US cron을 `0 23 * * 1-5`로 계절 조정하거나 처음부터 23:00 UTC(08:00 KST)로 고정.

### 2-2. 상태 보존 (핵심)

| 데이터 | 보존 방식 | 이유 |
|--------|-----------|------|
| `data/screener_history.db` (추천+추적) | **실행 후 git commit & push** (github-actions bot) | 작고 누적형 — 유실되면 성과추적 무의미 |
| `data/cache/ohlcv/` | **actions/cache** (key: 주차 기반, restore-keys로 이월) | 54MB, 유실돼도 재다운로드 가능(비용만 증가) |
| `output/{us,kr}/` 산출물 | git commit(리포트 게시용) + run artifact(보관 90일) | 열람·이력 |

- DB 커밋 충돌 방지: 워크플로 시작 시 `git pull --rebase`, concurrency로 동시 실행 차단.
- 저장소는 **private 권장** (추천 종목·계좌설정이 담김).

### 2-3. Secrets / 설정

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` → repo Settings > Secrets → env로 주입.
- `.env`는 클라우드에서 사용하지 않음(로컬 전용 유지).

### 2-4. 리포트 웹 게시

- 실행 말미에 `output/us/claude_input_report.md`·`output/kr/claude_input_report.md`·`top5.csv`를 간단한 `index.html`로 변환(마켓 탭 2개 + 갱신시각 + 데이터 기준일)하는 스크립트 `scripts/build_report_site.py` 신규.
- 게시는 **GitHub Pages(gh-pages 브랜치)** 기본. (Netlify 선호 시 동일 산출물 폴더를 Netlify에 연결 — AEGIS SENTINEL과 같은 방식. 단 private repo Pages는 유료 플랜 필요하므로 이 경우 Netlify가 무료 대안)
- 페이지에 면책 문구(추천이 아닌 스크리닝 결과, 데이터 기준일) 고정 표기.

### 2-5. 실패 알림

- 잡 마지막에 `if: failure()` 스텝 → 텔레그램으로 "스크리닝 실패: {run URL}" 발송 (curl로 직접 호출, 파이썬 실패와 무관하게 동작).

### 2-6. yfinance/pykrx 레이트리밋 대응

- 캐시 우선(read_ohlcv_cache) 구조 그대로 활용 — actions/cache 복원으로 대부분 히트.
- `fetch_ohlcv_batch` 실패 티커 재시도 1회 + 실패 수가 유니버스의 30% 초과 시 **경고 포함 통지**(무성과 실행을 정상으로 오인 방지). 클라우드 IP 차단 지속 시 self-hosted runner(집 PC 상시가동) 또는 2안(VPS)으로 폴백 — 이번 범위 아님, 기록만.

### 2-7. (옵션) 온디맨드 백테스트

- `workflow_dispatch` input `run_backtest=true` 시 `python run_us_backtest.py --label ci_<날짜> --offline` 실행 → summary를 텔레그램 발송 + artifact 업로드.
- 캐시 기반 오프라인이므로 러너 6시간 한도 내 충분.

## 3. 로컬에 남는 것 (변경 없음)

- `desktop_app.py`(수동 실행·백테스트 UI), 본격 백테스트/파라미터 실험(WO-008), 개발·테스트.
- Windows 작업 스케줄러 등록(WO-005)은 클라우드 안정화 확인 후 **중복 실행 방지 위해 비활성** 권장.

## 4. 판정 기준 (Acceptance)

1. 평일 KR/US 각 1회, **연속 3영업일 자동 실행 성공** (수동 개입 없이).
2. 텔레그램으로 Top 후보 요약 수신 + 실패 시 실패 통지 수신 확인(고의 실패 1회 테스트).
3. `screener_history.db` row가 실행마다 누적 증가(성과추적 갱신 포함), 캐시 히트율 로그 확인.
4. 리포트 URL에서 최신 결과·데이터 기준일 확인 가능.
5. 로컬 데스크톱 앱 실행에 회귀 없음.

## 5. 영향 파일

- 신규: `.github/workflows/daily_screen.yml`, `scripts/build_report_site.py`
- 수정: `requirements.txt`(클라우드 실행 최소 의존성 검증), `README.md`(클라우드 운용 절차·Secrets 등록법), `.gitignore`(DAD/ 등 배포 산출물 제외 — WO-008 §4-7과 병행)
- 불변: `main.py`(이미 CLI 완결), `src/telegram_sender.py`(이미 env 지원)

## 6. 완료(DoD)

1. §4 판정 5항목 충족, 실행 스크린샷/로그를 PR에 첨부.
2. Secrets 등록 절차를 README에 문서화(경석님이 직접 등록).
3. WO-005 로컬 스케줄러와의 중복 방지 방침 명기.
