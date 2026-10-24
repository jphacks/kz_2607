"""ペット引き継ぎアプリのバックエンド(開発期間中に新規作成)。"""
from firebase_functions import https_fn, options
from firebase_admin import initialize_app

initialize_app()
options.set_global_options(region="asia-northeast1", max_instances=10)


@https_fn.on_call()
def ping(req: https_fn.CallableRequest):
    """動作確認用。デプロイできているかを確かめる。"""
    return {"ok": True}
