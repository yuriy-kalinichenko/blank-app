import io
import zipfile

from test_golden_discovery import app


class Upload:
    name = "commercial.xlsx"

    def __init__(self, payload):
        self._payload = payload

    def getvalue(self):
        return self._payload


def percentage_workbook(*, custom_format, percentage_style=True):
    num_fmts = (
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.00%"/></numFmts>'
        if custom_format and percentage_style
        else ""
    )
    percent_format_id = 164 if custom_format else 10
    cell_format_id = percent_format_id if percentage_style else 0
    parts = {
        "xl/workbook.xml": '''
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets><sheet name="Commercial" sheetId="1" r:id="rId1"/></sheets>
            </workbook>''',
        "xl/_rels/workbook.xml.rels": '''
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
            </Relationships>''',
        "xl/styles.xml": f'''
            <styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              {num_fmts}
              <cellXfs count="2">
                <xf numFmtId="0"/>
                <xf numFmtId="{cell_format_id}" applyNumberFormat="1"/>
              </cellXfs>
            </styleSheet>''',
        "xl/worksheets/sheet1.xml": '''
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData><row r="1">
                <c r="A1" t="inlineStr"><is><t>Gross margin</t></is></c>
                <c r="B1" s="1"><v>0.5</v></c>
              </row></sheetData>
            </worksheet>''',
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in parts.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def test_xlsx_percentage_style_is_imported_as_percentage_points(app):
    for custom_format in (False, True):
        result = app.parse_commercial_upload(
            Upload(percentage_workbook(custom_format=custom_format))
        )
        assert result["gross_margin"] == 50.0


def test_xlsx_plain_decimal_is_not_scaled(app):
    result = app.parse_commercial_upload(
        Upload(percentage_workbook(custom_format=False, percentage_style=False))
    )
    assert result["gross_margin"] == 0.5
