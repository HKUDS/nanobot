from .resource import *


class V3(object):
    def __init__(self, config: Config) -> None:
        self.spreadsheet: Spreadsheet = Spreadsheet(config)
        self.spreadsheet_sheet: SpreadsheetSheet = SpreadsheetSheet(config)
        self.spreadsheet_sheet_filter: SpreadsheetSheetFilter = SpreadsheetSheetFilter(config)
        self.spreadsheet_sheet_filter_view: SpreadsheetSheetFilterView = SpreadsheetSheetFilterView(config)
        self.spreadsheet_sheet_filter_view_condition: SpreadsheetSheetFilterViewCondition = SpreadsheetSheetFilterViewCondition(
            config)
        self.spreadsheet_sheet_float_image: SpreadsheetSheetFloatImage = SpreadsheetSheetFloatImage(config)
