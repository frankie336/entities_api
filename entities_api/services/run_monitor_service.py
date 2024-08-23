import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from models.models import Run
from entities_api.services.run_service import RunService
from entities_api.services.loggin_service import LoggingUtility

logging_utility = LoggingUtility()


class RunMonitorService:
    def __init__(self, db: Session, max_run_duration: int = 3600):
        self.db = db
        self.run_service = RunService(db)
        self.max_run_duration = max_run_duration  # Maximum allowed run duration in seconds

    def check_and_update_runs(self):
        logging_utility.info("Starting periodic check of in-progress runs")
        current_time = int(time.time())
        expiration_threshold = current_time - self.max_run_duration

        # Query for runs that have been in progress for too long
        expired_runs = self.db.query(Run).filter(
            and_(
                Run.status == "in_progress",
                Run.started_at < expiration_threshold
            )
        ).all()

        for run in expired_runs:
            logging_utility.warning(f"Run {run.id} has exceeded the maximum duration and will be expired")
            try:
                self.run_service.expire_run(run.id)
                logging_utility.info(f"Run {run.id} has been expired")
            except Exception as e:
                logging_utility.error(f"Error expiring run {run.id}: {str(e)}")

        logging_utility.info(f"Periodic check completed. {len(expired_runs)} runs were expired.")

# The following code is not needed in this file anymore, as it's integrated into the main app
# def run_periodic_check(db: Session, interval: int = 300):
#     monitor = RunMonitorService(db)
#     while True:
#         monitor.check_and_update_runs()
#         time.sleep(interval)

# if __name__ == "__main__":
#     from db.database import SessionLocal
#     db = SessionLocal()
#     try:
#         run_periodic_check(db)
#     finally:
#         db.close()