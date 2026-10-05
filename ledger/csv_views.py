"""SC-13 CSV 出力・取り込み（画面設計書 4.14）。"""

import base64
from datetime import date

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import AppSettings
from core.periods import month_containing, month_period
from ledger import csv_io
from reports.stats import year_range

SESSION_KEY = "csv_import"
MSG_E30 = "ファイルを選んでください。"


def page(request: HttpRequest) -> HttpResponse:
    """出力と取り込みの画面。"""
    current = month_containing(timezone.localdate()).month
    return render(
        request, "ledger/csv.html", {"menu": "settings", "month": current, "year": current.year}
    )


def export(request: HttpRequest) -> HttpResponse:
    """CSV の出力（F-IO-01）。?unit=month&month=2026-10 または ?unit=year&year=2026"""
    settings = AppSettings.load()
    try:
        if request.GET.get("unit") == "year":
            year = int(request.GET.get("year", ""))
            span = year_range(year, settings)
            start, end, name = span.start, span.end, f"budget_{year}.csv"
        else:
            y, m = (int(x) for x in request.GET.get("month", "").split("-"))
            period = month_period(date(y, m, 1), settings)
            start, end, name = period.start, period.end, f"budget_{y:04d}-{m:02d}.csv"
    except ValueError:
        messages.error(request, "出力する期間を選んでください。")
        return redirect("ledger:csv")
    response = HttpResponse(csv_io.export(start, end), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@require_POST
def check(request: HttpRequest) -> HttpResponse:
    """取り込みの1段階目：ファイルを読み、すべての行をチェックする（画面設計書 4.14）。

    まだ登録しない。
    """
    upload = request.FILES.get("file")
    context: dict[str, object] = {
        "menu": "settings",
        "month": month_containing(timezone.localdate()).month,
    }
    if upload is None:
        context["errors"] = [MSG_E30]
        return render(request, "ledger/csv.html", context)
    content = upload.read(csv_io.MAX_BYTES + 1)
    result = csv_io.parse(content)
    context["year"] = timezone.localdate().year
    if not result.ok:
        request.session.pop(SESSION_KEY, None)
        context["errors"] = result.errors
        return render(request, "ledger/csv.html", context)
    # 誤りがなければ、2段階目（取り込む）まで中身を覚えておく
    request.session[SESSION_KEY] = base64.b64encode(content).decode("ascii")
    context["result"] = result
    return render(request, "ledger/csv.html", context)


@require_POST
def run(request: HttpRequest) -> HttpResponse:
    """取り込みの2段階目：覚えておいた中身をもう一度チェックし、すべてを1つの更新処理で登録する。"""
    stored = request.session.pop(SESSION_KEY, None)
    if not stored:
        messages.error(
            request, "取り込む内容がありません。もう一度ファイルを選んで「確認」してください。"
        )
        return redirect("ledger:csv")
    result = csv_io.parse(base64.b64decode(stored))
    if not result.ok:
        # 確認のあとでマスタが変わった場合など
        messages.error(request, "取り込めませんでした。もう一度「確認」してください。")
        return redirect("ledger:csv")
    count = csv_io.import_all(result)
    messages.success(request, f"{count}件の明細を取り込みました")  # MSG-I04
    return redirect("ledger:csv")
