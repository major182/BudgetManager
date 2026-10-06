"""静的ファイルの保存の仕方（06 デプロイ設計書 4.2）。"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class StaticFilesStorage(CompressedManifestStaticFilesStorage):
    """WhiteNoise の標準から、JavaScript の中の参照の書き換えだけを外す。

    標準では、ファイル名にハッシュを付けて圧縮し、ファイルの中の参照もその名前に書き換える。

    同梱している Chart.js の末尾には、開発用の対応表（chart.umd.min.js.map）への参照が残っている。
    対応表は同梱していないため、書き換えようとすると collectstatic が失敗する。
    このアプリの JavaScript は、ほかのファイルを読み込まないため、書き換えなくても困らない。
    """

    patterns = tuple(p for p in CompressedManifestStaticFilesStorage.patterns if p[0] == "*.css")
