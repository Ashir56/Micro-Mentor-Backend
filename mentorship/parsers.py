import io
import json
from urllib.parse import parse_qs

from rest_framework.exceptions import ParseError
from rest_framework.parsers import BaseParser, JSONParser


class ApplicationJSONParser(JSONParser):
    media_type = "application/json"

    def parse(self, stream, media_type=None, parser_context=None):
        raw_data = stream.read()
        if not raw_data:
            return {}

        try:
            return super().parse(io.BytesIO(raw_data), media_type=media_type, parser_context=parser_context)
        except (ParseError, ValueError, UnicodeDecodeError):
            text = raw_data.decode("utf-8", errors="replace")
            parsed = parse_qs(text, keep_blank_values=True)
            return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


class AnyContentTypeJSONParser(BaseParser):
    media_type = "*/*"

    def parse(self, stream, media_type=None, parser_context=None):
        raw_data = stream.read()
        if not raw_data:
            return {}

        try:
            return json.loads(raw_data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            text = raw_data.decode("utf-8", errors="replace")
            parsed = parse_qs(text, keep_blank_values=True)
            return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
