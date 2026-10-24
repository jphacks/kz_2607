"""関数が返す、利用者向けのエラー。codeは、HttpsErrorの種類に対応する。"""


class ApiError(Exception):
    def __init__(self, code, message, reason=None, extra=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason  # フロントが分岐に使う短い識別子(任意)
        self.extra = extra or {}  # details に足す項目(例: currentPetId)

    def details(self):
        d = dict(self.extra)
        if self.reason:
            d["reason"] = self.reason
        return d or None
