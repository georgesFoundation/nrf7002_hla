"""The part of Logic 2's `saleae.analyzers` module the analyser uses, to run it outside Logic 2."""


class AnalyzerFrame:
    def __init__(self, type, start_time, end_time, data=None):
        self.type = type
        self.start_time = start_time
        self.end_time = end_time
        self.data = data or {}


class HighLevelAnalyzer:
    pass
