"""関数が返す、利用者向けのエラー。codeは、HttpsErrorの種類に対応する。"""


class ApiError(Exception):
    def __init__(self, code, message, reason=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason  # フロントが分岐に使う短い識別子(任意)
