"""Windows Task Scheduler helpers for unattended screening runs."""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


WEEKDAYS = "MON,TUE,WED,THU,FRI"


@dataclass(frozen=True)
class ScheduleRecommendation:
    market: str
    task_name: str
    kst_time: str
    wib_time: str
    command_market: str
    reason: str


def recommend_times(profile: str = "kst") -> list[ScheduleRecommendation]:
    """Return recommended weekday screening times for Korea and Indonesia views."""
    return [
        ScheduleRecommendation(
            market="KR",
            task_name=r"StockAgent\KR_1600",
            kst_time="16:00",
            wib_time="14:00",
            command_market="kr",
            reason="Korea market close follow-up",
        ),
        ScheduleRecommendation(
            market="US",
            task_name=r"StockAgent\US_0800",
            kst_time="08:00",
            wib_time="07:30",
            command_market="us",
            reason="Morning run after prior US close",
        ),
    ]


def _default_python_command(project_dir: str | Path | None = None) -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    root = Path(project_dir or Path.cwd()).resolve()
    python = Path(sys.executable).resolve()
    main_py = root / "main.py"
    return f'"{python}" "{main_py}"'


def build_task_run_command(market: str, project_dir: str | Path | None = None, notify: str | None = None) -> str:
    command = f"{_default_python_command(project_dir)} --market {market} --auto"
    if notify:
        command += f" --notify {notify}"
    return command


def build_schtasks_command(
    *,
    task_name: str,
    start_time: str,
    market: str,
    project_dir: str | Path | None = None,
    notify: str | None = None,
) -> list[str]:
    return [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/SC",
        "WEEKLY",
        "/D",
        WEEKDAYS,
        "/ST",
        start_time,
        "/TR",
        build_task_run_command(market, project_dir, notify),
        "/RL",
        "LIMITED",
        "/F",
    ]


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess:
    if platform.system().lower() != "windows":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")
    return subprocess.run(args, check=False, capture_output=True, text=True)


def register_task(
    task_name: str,
    start_time: str,
    market: str,
    project_dir: str | Path | None = None,
    notify: str | None = None,
) -> subprocess.CompletedProcess:
    return _run_schtasks(
        build_schtasks_command(
            task_name=task_name,
            start_time=start_time,
            market=market,
            project_dir=project_dir,
            notify=notify,
        )
    )


def unregister_task(task_name: str) -> subprocess.CompletedProcess:
    return _run_schtasks(["schtasks", "/Delete", "/TN", task_name, "/F"])


def query_task(task_name: str) -> subprocess.CompletedProcess:
    return _run_schtasks(["schtasks", "/Query", "/TN", task_name])


def register_recommended_tasks(
    project_dir: str | Path | None = None,
    *,
    notify: str | None = None,
) -> list[subprocess.CompletedProcess]:
    results = []
    for item in recommend_times():
        results.append(
            register_task(
                item.task_name,
                item.kst_time,
                item.command_market,
                project_dir=project_dir,
                notify=notify,
            )
        )
    return results


def unregister_recommended_tasks() -> list[subprocess.CompletedProcess]:
    return [unregister_task(item.task_name) for item in recommend_times()]


def query_recommended_tasks() -> list[subprocess.CompletedProcess]:
    return [query_task(item.task_name) for item in recommend_times()]
