from pathlib import Path
from nanobot.cron.service import CronService

def test():
    # Create a dummy file if needed, but service handles missing file
    service = CronService(Path("test_jobs.json"))
    try:
        status = service.status()
        print(f"Status: {status}")
        if isinstance(status, dict):
             print("Success: status is a dict")
        else:
             print(f"Failure: status is {type(status)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test()
