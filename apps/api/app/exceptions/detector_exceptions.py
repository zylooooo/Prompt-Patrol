class DetectorTimeoutError(Exception):
    """The detector call exceeded DETECTOR_TIMEOUT_SECONDS."""


class DetectorUnavailableError(Exception):
    """The detector call failed for any other reason."""