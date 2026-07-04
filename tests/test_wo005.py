from pathlib import Path


def test_scheduler_recommended_times_include_kst_and_wib():
    from src.scheduler import recommend_times

    items = recommend_times()

    assert [(item.market, item.kst_time, item.wib_time) for item in items] == [
        ("KR", "16:00", "14:00"),
        ("US", "08:00", "07:30"),
    ]


def test_build_schtasks_command_uses_auto_market_command():
    from src.scheduler import build_schtasks_command

    command = build_schtasks_command(
        task_name=r"StockAgent\KR_1600",
        start_time="16:00",
        market="kr",
        project_dir=Path("C:/StockAgent"),
        notify="telegram",
    )

    assert command[:4] == ["schtasks", "/Create", "/TN", r"StockAgent\KR_1600"]
    assert "/ST" in command
    assert command[command.index("/ST") + 1] == "16:00"
    run = command[command.index("/TR") + 1]
    assert "--market kr --auto --notify telegram" in run
