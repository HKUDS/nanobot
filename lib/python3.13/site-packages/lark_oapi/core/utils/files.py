import io
from email.utils import decode_rfc2231
from typing import Any, Dict, Optional
from urllib.parse import unquote

from lark_oapi.core import Content_Disposition


class Files(object):
    @staticmethod
    def parse_file_name(headers: Dict[str, str]) -> Optional[str]:
        content_disposition = headers.get(Content_Disposition)
        if content_disposition is None:
            return None

        parts = content_disposition.split(';')
        params = {}

        for part in parts:
            if '=' in part:
                k, v = part.strip().split('=', 1)
                params[k] = v.strip(' "')

        if 'filename*' in params:
            # Decode RFC2231 encoded format
            filename = decode_rfc2231(params['filename*'])[2]
            filename = unquote(filename)
        elif 'filename' in params:
            # Handle possible encoding issues with a basic unquote
            filename = unquote(params['filename'])
            # or try to decode using utf-8 if it seems like a valid utf-8 string
            try:
                filename = filename.encode('latin1').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        else:
            filename = None

        return filename

    @staticmethod
    def parse_form_data(obj: Any) -> Dict[str, Any]:
        fd = {}
        if isinstance(obj, dict):
            fd = obj
        elif not hasattr(obj, "__dict__"):
            return fd
        else:
            fd = vars(obj)

        for k, v in fd.items():
            if v is None or isinstance(v, io.IOBase) or isinstance(v, tuple):
                continue
            fd[k] = str(v)

        return fd

    @staticmethod
    def extract_files(obj: Any):
        if obj is None:
            return None
        files = {}
        if isinstance(obj, dict):
            to_del_keys = []
            for k, v in obj.items():
                if isinstance(v, io.IOBase):
                    files[k] = v
                    to_del_keys.append(k)
            for k in to_del_keys:
                del obj[k]
        elif not hasattr(obj, "__dict__"):
            return None
        else:
            for k, v in vars(obj).items():
                if isinstance(v, io.IOBase):
                    files[k] = v
                    setattr(obj, k, None)

        return files
