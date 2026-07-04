# Stock Agent Rev

Streamlit 없이 실행하는 Stock Agent 데스크톱 UI입니다.

## 실행

```bat
START_DESKTOP.bat
```

또는:

```bat
python desktop_app.py
```

## EXE 빌드

```bat
build_windows_exe.bat
```

빌드 결과:

```text
dist\StockAgentRev\StockAgentRev.exe
```

## 구조

- `desktop_app.py`: tkinter 데스크톱 UI
- `main.py`: 현재 스크리너 실행 엔진
- `src/`: 현재 분석/점수/백테스트 관련 공통 로직
- `configs/`: 미국/한국 설정
- `data/`, `tickers*.csv`: 유니버스/관심종목 데이터
- `output/`: 실행 결과 저장 위치
## GitHub Actions daily screening

WO-009 adds `.github/workflows/daily_screen.yml` for cloud execution.

Required repository settings:

1. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
2. Enable GitHub Pages with source `GitHub Actions`.
3. Keep repository Actions permissions set to allow read/write access, because the workflow commits `output/`, `logs/run.log`, and `data/screener_history.db`.

Schedule:

- KR screening: `30 7 * * 1-5` UTC, 16:30 KST.
- US screening: `0 23 * * 1-5` UTC, 08:00 KST.
- Manual run: Actions > `daily-screen` > Run workflow, with `market` set to `us`, `kr`, or `both`.

The workflow runs `python main.py --market <market> --auto --notify telegram`, builds a static report site with `scripts/build_report_site.py`, uploads run artifacts, deploys GitHub Pages, and sends a Telegram failure message with `curl` if the job fails.

Local preview:

```bat
python scripts\build_report_site.py --output-dir public
```

Open `public\index.html` after the command completes.
