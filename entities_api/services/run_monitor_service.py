import time
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from models.models import Run
from entities_api.services.run_service import RunService
from entities_api.services.loggin_service import LoggingUtility

logging_utility = LoggingUtility()


class RunMonitorService:
    def __init__(self, db: Session, max_run_duration: int = 3600, inactivity_threshold: int = 900):
        self.db = db
        self.run_service = RunService(db)
        self.max_run_duration = max_run_duration  # Maximum allowed run duration in seconds (1 hour)
        self.inactivity_threshold = inactivity_threshold  # Inactivity threshold in seconds (15 minutes)

    def check_and_update_runs(self):
        logging_utility.info("Starting periodic check of in-progress runs")
        current_time = int(time.time())
        long_running_threshold = current_time - self.max_run_duration
        inactivity_threshold = current_time - self.inactivity_threshold

        # Query for runs that have been in progress for too long or inactive
        expired_runs = self.db.query(Run).filter(
            and_(
                Run.status == "in_progress",
                or_(
                    Run.started_at < long_running_threshold,
                    Run.last_activity_at < inactivity_threshold
                )
            )
        ).all()

        for run in expired_runs:
            if run.started_at < long_running_threshold:
                reason = "exceeded maximum duration"
            else:
                reason = "inactive for too long"

            logging_utility.warning(f"Run {run.id} has {reason} and will be expired")
            try:
                self.run_service.expire_run(run.id)
                logging_utility.info(f"Run {run.id} has been expired")
            except Exception as e:
                logging_utility.error(f"Error expiring run {run.id}: {str(e)}")

        logging_utility.info(f"Periodic check completed. {len(expired_runs)} runs were expired.")

    def update_run_activity(self, run_id: str):
        """Update the last activity timestamp for a run"""
        try:
            run = self.db.query(Run).filter(Run.id == run_id).first()
            if run and run.status == "in_progress":
                run.last_activity_at = int(time.time())
                self.db.commit()
                logging_utility.info(f"Updated last activity for run {run_id}")
            else:
                logging_utility.warning(
                    f"Attempted to update activity for non-existent or non-in-progress run {run_id}")
        except Exception as e:
            logging_utility.error(f"Error updating activity for run {run_id}: {str(e)}")