/*
 * 全画面に共通する画面の動き（画面設計書 1.4・1.6）。
 * htmx で足りない小さな動きだけを、ビルドの要らない素の JavaScript で書く（技術選定書 5.3）。
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- 完了の知らせ（画面設計書 1.6）
  // 画面の上部に数秒表示して消す
  function toast(message) {
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.textContent = message; // textContent なので HTML として解釈されない（S-02）
    document.body.append(el);
    setTimeout(() => el.remove(), 2500);
  }
  window.budgetToast = toast;

  // サーバーが Django の messages で返した知らせ（ページの読み込み時）
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-toast]").forEach((el) => {
      toast(el.dataset.toast);
      el.remove();
    });
  });

  // htmx の応答の HX-Trigger ヘッダーで送られた知らせ：{"showMessage": "登録しました"}
  document.body.addEventListener("showMessage", (event) => {
    toast(event.detail.value);
  });

  // ---------------------------------------------------------------- 確認ダイアログ（画面設計書 1.6）
  // hx-confirm を付けた要素は、ブラウザ標準の confirm ではなく、この画面のダイアログで確かめる。
  // ボタンの文言は data-confirm-ok（例：削除する）で指定する（画面設計書 6.2）
  document.body.addEventListener("htmx:confirm", (event) => {
    const question = event.detail.question;
    if (!question) return; // hx-confirm がない通信はそのまま送る
    event.preventDefault();

    const okLabel = event.detail.elt.dataset.confirmOk || "OK";
    const cancelLabel = event.detail.elt.dataset.confirmCancel || "キャンセル";
    const dialog = document.createElement("dialog");
    dialog.className = "confirm";
    const text = document.createElement("p");
    text.textContent = question;
    const row = document.createElement("div");
    row.className = "btn-row";
    const cancel = document.createElement("button");
    cancel.className = "btn";
    cancel.textContent = cancelLabel;
    const ok = document.createElement("button");
    ok.className = "btn danger";
    ok.textContent = okLabel;
    row.append(cancel, ok);
    dialog.append(text, row);
    document.body.append(dialog);

    const close = (confirmed) => {
      dialog.close();
      dialog.remove();
      if (confirmed) event.detail.issueRequest(true);
    };
    cancel.addEventListener("click", () => close(false));
    ok.addEventListener("click", () => close(true));
    dialog.addEventListener("cancel", () => dialog.remove());
    dialog.showModal();
  });

  // ---------------------------------------------------------------- 通信のエラー（画面設計書 6.6）
  // サーバーのエラー（MSG-S01）
  document.body.addEventListener("htmx:responseError", (event) => {
    if (event.detail.xhr.status === 404) {
      toast("ページが見つかりません。");
    } else {
      toast("エラーが発生しました。時間をおいて、もう一度お試しください。");
    }
  });
  // 通信そのものの失敗（MSG-S03。Tailscale の接続切れなど）
  document.body.addEventListener("htmx:sendError", () => {
    toast("通信できませんでした。接続を確かめてから、もう一度お試しください。");
  });
})();
