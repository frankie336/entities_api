import logging


class LoggingUtility:
    def __init__(self, app=None):
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        # Configure console handler
        self.console_handler = logging.StreamHandler()
        self.console_handler.setLevel(logging.DEBUG)  # Capture all log levels for the console
        self.console_handler.setFormatter(self.formatter)

        # Clear existing handlers
        if not self.logger.handlers:
            self.logger.addHandler(self.console_handler)

        # Set the logger's level
        self.logger.setLevel(logging.DEBUG)  # Set the logger to capture all log levels

        # Set the handler attribute
        self.handler = self.console_handler

        # Set the level attribute
        self.level = logging.DEBUG

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.logger = self.logger

    def debug(self, message, *args, **kwargs):
        self.logger.debug(message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        self.logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self.logger.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self.logger.error(message, *args, **kwargs)
        self.intercept_error_log(message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        self.logger.critical(message, *args, **kwargs)
        self.intercept_critical_log(message, *args, **kwargs)

    def exception(self, message, *args, **kwargs):
        self.logger.exception(message, *args, **kwargs)

    def intercept_error_log(self, message, *args, **kwargs):
        # Perform actions or send notifications for error logs
        print("Intercepted Error Log:")
        print(message % args)
        # Add your custom logic here

    def intercept_critical_log(self, message, *args, **kwargs):
        # Perform actions or send notifications for critical logs
        print("Intercepted Critical Log:")
        print(message % args)


if __name__ == "__main__":
    logging_utility = LoggingUtility()
